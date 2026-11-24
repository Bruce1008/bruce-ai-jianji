"""Freeze holds: pages the 口播稿 marks （画面…停留N秒） stay on screen N s after the speaker stops.

No automatic freezes. Only a
TIMELINE entry with hold=N (and usually done=<end of the last word on that page>) is held. MIN_HOLD defaults to 0;
a scenes.py may still set MIN_HOLD = 2.0 to bring back the old automatic rule for every MG page.

Everything is authored on the voice timeline (word times from words.txt); the holds are added at render/mix time.
For every MG page with a hold (hold=N on the entry, else MIN_HOLD):
  done  = the entry's done=<t> if given, else when its last animation finishes, measured by rendering the page just
          before it leaves and recording every short prog() it evaluates (lib.PROG_LOG; d <= 1.6 s, longer is drift)
  leave = when its outgoing transition starts (next t - td/2; for the last page, the final fade)
  need  = hold - (leave - done). If > 0 the video gets `need` s longer at this page:
    pic  the stage, TOC and SFX freeze on the finished page, just before the outgoing transition, or just before the
         stage shrinks back from full screen when that happens after done (the page is then held big)
    aud  the voice pauses (silence), the talking head freezes and the subtitle is hidden, at the quietest point of
         the narration around the page change, so no word is cut
  Both freezes are `need` long, so picture and voice are back in sync before the next page's first word.
Material clips are never held.

render.py builds the plan, renders with it and writes <video>.holds.json next to the video; mix_master.py reads that
file, so the sound always matches the rendered picture. `python render.py holds` prints the plan without rendering.
"""
import json, subprocess
import tools
import numpy as np
import lib

MIN_HOLD = 0.0              # no automatic holds; scenes.py MIN_HOLD = 2.0 makes every page stay >= 2 s
ENV_HZ = 100                 # voice envelope resolution (frames per second)


def _td(e):
    return lib._td(e) if e else 0.0


def _leave(tl, i, dur):
    return tl[i + 1]['t'] - _td(tl[i + 1]) / 2 if i + 1 < len(tl) else dur - 0.4


def voice_env(path):
    """loudness envelope of the narration: dB per 10 ms, smoothed over 50 ms"""
    raw = subprocess.run([tools.FFMPEG, '-v', 'error', '-i', path, '-vn', '-ac', '1', '-ar', '16000', '-f', 'f32le', '-'],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.float32).astype(np.float64)
    hop = 16000 // ENV_HZ
    n = len(x) // hop
    p = np.convolve((x[:n * hop].reshape(n, hop) ** 2).mean(1), np.ones(5) / 5, 'same')
    return 10 * np.log10(p + 1e-12)


def _quietest(env, lo, hi, near):
    """(time, dB): inside [lo, hi], the quietest stretch of the voice (within 3 dB of its minimum) closest to near"""
    a, b = max(0, int(lo * ENV_HZ)), min(len(env), int(hi * ENV_HZ) + 1)
    if b <= a:
        return near, float(env[min(len(env) - 1, int(near * ENV_HZ))])
    seg = env[a:b]
    ok = np.nonzero(seg <= seg.min() + 3)[0]
    k = ok[np.argmin(np.abs((a + ok) / ENV_HZ - near))]
    return (a + k) / ENV_HZ, float(seg[k])


def measure_done(SC, dur, draw):
    """{TIMELINE index: done time} for MG pages without done=. draw(i, t) renders page i at voice time t."""
    tl = SC.TIMELINE
    mh0 = getattr(SC, 'MIN_HOLD', MIN_HOLD)
    out = {}
    for i, d in enumerate(tl):
        if 'mg' not in d or 'done' in d or not d.get('hold', mh0):
            continue
        ts = _leave(tl, i, dur) - 0.02
        lib.PROG_LOG = []
        try:
            draw(i, ts)
        finally:
            log, lib.PROG_LOG = lib.PROG_LOG, None
        ends = [e for s, e in log if s <= ts]
        out[i] = max(ends) if ends else None
    return out


def _moving(windows):
    """[(m0, m1)]: when the stage is growing to full screen or shrinking back"""
    out = []
    for a, b, d in windows:
        d = min(d, (b - a) / 2)
        out.append((a, a + d))
        if b < 1e8:
            out.append((b - d, b))
    return out


def plan(SC, dur, done_of, windows, env):
    """-> (holds, warnings); holds = [dict(i, name, done, leave, need, pic, aud, depth)]"""
    tl = SC.TIMELINE
    mh0 = getattr(SC, 'MIN_HOLD', MIN_HOLD)
    mv = _moving(windows)
    loud = float(np.percentile(env, 90))
    holds, warn, last_aud = [], [], -1.0
    for i, d in enumerate(tl):
        if 'mg' not in d:
            continue
        mh = d.get('hold', mh0)
        if not mh:
            continue
        name = getattr(d['mg'], '__name__', f'#{i}')
        nxt = tl[i + 1] if i + 1 < len(tl) else None
        start = d['t'] + _td(d) / 2
        leave = _leave(tl, i, dur)
        done = d['done'] if 'done' in d else done_of.get(i)
        done = start if done is None else max(done, start)
        if done > leave + 0.1:
            warn.append(f'{name} @ {d["t"]:.2f}: still animating when it leaves ({done:.2f} > {leave:.2f}); '
                        f'move the last element earlier or the next scene later')
        done = min(done, leave - 0.01)
        need = round(mh - (leave - done), 2)
        if need < 0.15:                                   # a few frames short: not worth a pause
            continue
        # picture: hold the finished page where the stage is still, preferring full screen, else as late as possible
        cands = [leave - 0.01] + [x for m0, m1 in mv for x in (m0 - 0.01, m1 + 0.01)]
        cands = [x for x in cands if done - 1e-6 <= x <= leave - 0.01 and not any(m0 < x < m1 for m0, m1 in mv)]
        if cands:
            pic = max(cands, key=lambda x: (-round(lib.full_amount(x, windows), 3), x))
        else:
            pic = leave - 0.01
            warn.append(f'{name} @ {d["t"]:.2f}: the stage is moving when the page leaves; the freeze catches it mid-move')
        # voice: pause in the gap between this page's last words and the next page's first word
        if nxt is None:
            aud, gap = dur, -120.0
        else:
            aud, gap = _quietest(env, max(done, pic - 0.8, last_aud + 0.05), nxt['t'] + 0.4, pic)
            if loud - gap < 15:
                warn.append(f'{name} @ {d["t"]:.2f}: no clear pause near {aud:.2f} (only {loud - gap:.0f} dB under the '
                            f'speech); the voice freeze may clip a word, check it')
        last_aud = aud
        holds.append(dict(i=i, name=name, done=round(done, 2), leave=round(leave, 2), need=need,
                          pic=round(pic, 3), aud=round(aud, 3), depth=round(loud - gap, 1)))
    return holds, warn


def report(holds, warn, dur):
    add = sum(h['need'] for h in holds)
    print(f'holds: {len(holds)} pages frozen, +{add:.1f} s  ->  {dur:.1f} s voice, {dur + add:.1f} s video')
    for h in holds:
        print(f"  {h['name']:<22} done {h['done']:7.2f}  leaves {h['leave']:7.2f}  freeze {h['need']:.2f} s"
              f"  picture @ {h['pic']:.2f}  voice @ {h['aud']:.2f}")
    for w in warn:
        print('  WARNING', w)


def save(path, holds, warn, dur):
    json.dump(dict(voice_dur=dur, holds=holds, warnings=warn), open(path, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


def load(path):
    return json.load(open(path, encoding='utf-8'))['holds']


class TimeMap:
    """output (video) time <-> voice time. pic = stage, TOC, SFX; aud = voice, talking head, subtitles."""
    def __init__(self, holds, dur):
        self.P = sorted((h['pic'], h['need']) for h in holds)
        self.A = sorted((h['aud'], h['need']) for h in holds)
        self.dur = dur + sum(h['need'] for h in holds)

    @staticmethod
    def _v(o, hs):
        off = 0.0
        for x, d in hs:
            if o < x + off:
                break
            if o < x + off + d:
                return x, True
            off += d
        return o - off, False

    @staticmethod
    def _o(v, hs):
        return v + sum(d for x, d in hs if x < v)

    def pic(self, o):
        """voice time the picture shows at output time o, and whether it is frozen"""
        return self._v(o, self.P)

    def aud(self, o):
        """voice time heard at output time o, and whether the voice is paused"""
        return self._v(o, self.A)

    def pic_o(self, v):
        return self._o(v, self.P)

    def aud_o(self, v):
        return self._o(v, self.A)

    def subs(self, cues):
        """subtitle cues on output time; a line is hidden while the voice is paused (and comes back after the
        pause only if words of it are still to be said, not for the short bridge to the next line)"""
        out = []
        for t0, t1, s in cues:
            cut = next((x for x, _ in self.A if t0 < x < t1), None)
            if cut is None:
                out.append((self.aud_o(t0), self.aud_o(t1), s))
                continue
            out.append((self.aud_o(t0), self.aud_o(cut), s))
            if t1 - cut >= 0.45:
                out.append((self.aud_o(cut) + dict(self.A)[cut], self.aud_o(t1), s))
        return sorted(out)

    def voice(self, v, sr):
        """insert silence into a (n, ch) voice array at the voice pauses, with 8 ms fades at each cut"""
        if not self.A:
            return v
        f = int(0.008 * sr)
        ramp = np.linspace(1.0, 0.0, f)[:, None]
        parts, last = [], 0
        for x, d in self.A:
            k = min(len(v), int(round(x * sr)))
            seg = v[last:k].copy()
            if last > 0 and len(seg) >= f: seg[:f] *= ramp[::-1]
            if len(seg) >= f: seg[-f:] *= ramp
            parts += [seg, np.zeros((int(round(d * sr)),) + v.shape[1:], v.dtype)]
            last = k
        seg = v[last:].copy()
        if len(seg) >= f: seg[:f] *= ramp[::-1]
        parts.append(seg)
        return np.concatenate(parts)

    def cue(self, c):
        """move an SFX cue with the picture; a cue with an anchor keeps its lead on that event"""
        t, name, db, kw = c
        kw = dict(kw)
        a = kw.pop('_anchor', t)
        return (self.pic_o(a) + (t - a), name, db, kw)
