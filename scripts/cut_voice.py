"""粗剪（剪气口）：在给画面对时间之前先剪口播——收紧停顿、删掉重录和说一半重来的半句、删掉口头指示
（「这段不要了」「重来」）。停顿规则来自大师的AI小灶公开的气口提示词。默认不变速（SPEED = 1.0）。

重录挑哪一遍：没有口误、卡壳、吞音，语调最饱满、重音准的那遍；差别不明显时把候选列给用户选；
条件相同用后录的一遍。人物姿势或位置差很多的两遍不拼。

usage (in _工程, after `python transcribe.py "<raw take>"`):
  python cut_voice.py scan "<raw take>" [--script ../口播稿.rtf]
      -> 粗剪_扫描.md   every pause > 0.35 s and what it becomes; each stretch between those pauses transcribed ALONE
                        with no prompt (so a repeated take is not swallowed); suspected retakes / false starts with
                        ready-made DROP lines; voiced bits with no words; script lines not recorded; said lines not in
                        the script.  Also writes cut_plan.py (only if missing) for you to fill in.
  python cut_voice.py cut "<raw take>" [--script ...]
      -> 口播_粗剪.mp4 (口播_粗剪.wav for an audio-only take), cut_map.json (raw <-> cut times, see cutmap.py),
         粗剪说明.md (what was cut and why, splice points to re-check, speed)
Then set VOICE = '口播_粗剪.mp4' in scenes.py, run transcribe.py on it, and time everything on that file.
The first scan renames transcribe.py's transcript.json / words.txt to transcript_raw.json / words_raw.txt.

Pause rules (OUTPUT seconds, i.e. after the speed-up). Onsets and offsets are measured on the audio envelope, not
taken from Whisper's word times:
  * the take starts 0.15 s before the first onset and ends 0.20 s after the last offset
  * a pause up to 0.35 s stays as it is
  * a longer pause shrinks to: hesitation inside a sentence 0.40, comma 0.40, full stop / question 0.55, paragraph 0.70
    (paragraph turns come from the script; add more in PARA). The kept silence is 55 % after the offset (the tail /
    尾音 rings out) and 45 % before the next onset
  * a filler cut inside a sentence leaves 0.04 s (DROP entry with gap=0.04)
  * breaths and clicks in a pause are not kept for their own sake; cuts land only in measured silence, never inside a
    word; the picture hard-cuts with the sound (口播片段之间一律硬切)
  * no compression / EQ / denoise here (mix_master.py does the voice chain and the noise gate)
"""
import sys, os, re, json, shutil, argparse, subprocess, difflib
import tools
import numpy as np
from scipy.io import wavfile

ap = argparse.ArgumentParser()
ap.add_argument('mode', choices=['scan', 'cut'])
ap.add_argument('take')
ap.add_argument('--script', default=None, help='口播稿；默认用 intake.py 存的 _工程/口播稿.txt')
ap.add_argument('--plan', default='cut_plan.py')
a = ap.parse_args()

NATURAL = 0.35                                   # output s: pauses up to this stay as they are
TARGET = dict(hes=0.40, comma=0.40, period=0.55, para=0.70)
HEAD, TAIL = 0.15, 0.20                          # before the first onset / after the last offset
TAIL_SHARE = 0.55                                # share of a shortened pause kept after the offset
FILLER_GAP = 0.04
HOP = 0.01
TARGET_RATE = 5.5                                # 字/秒 SPEED='auto' 时加速到的语速（中文口播常见 5.0–5.9）
STOP, SOFT = '。？！?!…', '，,、；;：:'
SR = 48000

PLAN_TEMPLATE = '''"""粗剪 plan for cut_voice.py (raw-take seconds). Fill it from 粗剪_扫描.md, then: python cut_voice.py cut <take>"""
SPEED = 1.0          # 默认不变速。用户要加速时写数字（1.1、1.2，音调不变），或 'auto'（加速到约 5.5 字/秒，最多 1.2 倍）
DROP = [             # (raw start, raw end, why[, gap]) — gap = output seconds left at the splice (default: pause rules;
                     # 0.04 for a filler cut inside a sentence). Edges snap to the nearest measured silence.
    # (41.20, 44.85, '重说：第一遍「质数就是」说到一半卡壳，留后一遍'),
]
PARA = []            # extra raw times of paragraph turns (that pause becomes 0.70 s)
KEEP = {}            # {raw time inside a pause: output seconds to keep}, e.g. a beat before a chapter card
'''


# ------------------------------------------------------------------ audio + envelope
def load_audio(path):
    tmp = '_cut_tmp.wav'
    subprocess.run([tools.FFMPEG, '-v', 'error', '-y', '-i', path, '-vn', '-ac', '1', '-ar', str(SR), '-c:a', 'pcm_f32le', tmp],
                   check=True)
    sr, x = wavfile.read(tmp)
    os.remove(tmp)
    return x.astype(np.float64)


def envelope(x):
    hop = int(SR * HOP)
    n = len(x) // hop
    p = (x[:n * hop].reshape(n, hop) ** 2).mean(1)
    p = np.convolve(p, np.ones(2) / 2, 'same')
    return 10 * np.log10(p + 1e-12)


def runs(mask):
    d = np.diff(np.r_[0, mask.astype(np.int8), 0])
    return list(zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]))


def speech_regions(db, words):
    """voiced runs that are speech: they overlap a Whisper word, or are long and loud (speech Whisper skipped).
    Short, quiet runs with no word (breaths, clicks, chair) count as silence. Returns (speech [(a, b)] s,
    unworded voiced [(a, b, dB)] s, threshold)"""
    floor, top = np.percentile(db, 10), np.percentile(db, 95)
    thr = floor + max(10.0, (top - floor) * 0.30)
    m = db > thr
    for s, e in runs(~m):                       # holes < 80 ms inside a word (stops, plosives)
        if e - s < 8 and s > 0:
            m[s:e] = True
    sp, odd = [], []
    med = np.median(db[m]) if m.any() else top
    for s, e in runs(m):
        if e - s < 4:                           # < 40 ms: a click
            continue
        t0, t1 = s * HOP, e * HOP
        worded = any(w['start'] - 0.08 < t1 and w['end'] + 0.08 > t0 for w in words)
        lv = float(db[s:e].mean())
        if worded:
            sp.append((t0, t1))
        elif (t1 - t0) >= 0.25 and lv > med - 8:
            sp.append((t0, t1)); odd.append((t0, t1, lv))
        elif (t1 - t0) >= 0.15:
            odd.append((t0, t1, lv))            # quiet: breath / noise, treated as silence
    merged = []
    for s, e in sp:
        if merged and s - merged[-1][1] < 0.06:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged, odd, thr


# ------------------------------------------------------------------ transcript + script
def load_words():
    if not os.path.exists('transcript_raw.json'):
        if not os.path.exists('transcript.json'):
            sys.exit('run transcribe.py on the raw take first')
        shutil.copy('transcript.json', 'transcript_raw.json')
        if os.path.exists('words.txt'):
            shutil.copy('words.txt', 'words_raw.txt')
        print('NOTE: transcript.json -> transcript_raw.json (raw-take word times)')
    r = json.load(open('transcript_raw.json', encoding='utf-8'))
    out = []
    for s in r['segments']:
        ws = [w for w in s.get('words', []) if w['word'].strip()]
        if ws and sum(w['end'] - w['start'] < 0.02 for w in ws) >= 0.6 * len(ws):
            continue                            # zero-length words: Whisper hallucinating over room noise
        out += ws
    return out


def norm(s):
    return re.sub(r'[^\w]', '', s.lower()).replace('_', '')


def script_text(path):
    if path is None:
        path = '口播稿.txt' if os.path.exists('口播稿.txt') else None
        if path is None:
            return None
    if path.endswith('.txt') or path.endswith('.md'):
        t = open(path, encoding='utf-8').read()
    else:
        import intake
        t = intake.read_script(path)
    t = re.sub(r'[（(]\s*画面[^）)]*[）)]', '', t)          # on-screen directions are not spoken
    t = re.sub(r'【[^】]*】', '', t)                          # notes to himself
    paras = [p.strip() for p in t.splitlines() if norm(p)]
    paras = [p for p in paras if re.search(r'[。？！?!，,]', p) or len(norm(p)) > 10]   # drop headings
    return paras


def align_script(paras, words):
    """char-level alignment script <-> transcript. Returns (paragraph-end times, missing script sentences,
    extra said spans [(t0, t1, text)])"""
    tc, tt = [], []                             # transcript chars and their times
    for w in words:
        s = norm(w['word'])
        for i, ch in enumerate(s):
            tc.append(ch); tt.append(w['start'] + (w['end'] - w['start']) * (i + 0.5) / max(1, len(s)))
    sc, owner = [], []                          # script chars, (paragraph, sentence) each belongs to
    sents = []
    for pi, p in enumerate(paras):
        for s in re.split(r'(?<=[。？！?!])', p):
            if not norm(s): continue
            sents.append((pi, s.strip()))
            for ch in norm(s):
                sc.append(ch); owner.append(len(sents) - 1)
    sm = difflib.SequenceMatcher(None, sc, tc, autojunk=False)
    m_s2t = {}
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            m_s2t[blk.a + k] = blk.b + k
    para_end = []
    for pi in range(len(paras) - 1):
        idx = [i for i, o in enumerate(owner) if sents[o][0] == pi]
        if not idx: continue
        hit = [m_s2t[i] for i in idx if i in m_s2t]
        if hit:
            para_end.append(tt[max(hit)])
    missing = []
    for si, (pi, s) in enumerate(sents):
        idx = [i for i, o in enumerate(owner) if o == si]
        cov = sum(1 for i in idx if i in m_s2t) / max(1, len(idx))
        if cov < 0.5 and len(idx) >= 4:
            missing.append(s)
    matched_t = set(m_s2t.values())
    extra, cur = [], []
    for j in range(len(tc) + 1):
        if j < len(tc) and j not in matched_t:
            cur.append(j)
        else:
            if len(cur) >= 5:
                extra.append((tt[cur[0]], tt[cur[-1]], ''.join(tc[k] for k in cur)))
            cur = []
    return para_end, missing, extra, ''.join(sc)


# ------------------------------------------------------------------ pauses
def pauses_of(speech, dur):
    return [(speech[i][1], speech[i + 1][0]) for i in range(len(speech) - 1)]


def kind_of(p, words, para_times, para_extra):
    a0, b0 = p
    if any(a0 - 0.6 <= t <= b0 + 0.3 for t in para_times) or any(a0 - 0.05 <= t <= b0 + 0.05 for t in para_extra):
        return 'para'
    before = [w for w in words if w['start'] < a0 + 0.05]
    if not before:
        return 'hes'
    last = before[-1]['word'].strip()
    if last and last[-1] in STOP: return 'period'
    if last and last[-1] in SOFT: return 'comma'
    return 'hes'


def snap(t, speech, side):
    """move t into the nearest measured silence: side='start' -> the end of the speech run t is in / just before;
    side='end' -> the start of the speech run t is in / just after"""
    for s, e in speech:
        if s - 1e-6 <= t <= e + 1e-6:
            return e if side == 'start' else s
    return t


# ------------------------------------------------------------------ scan
def scan():
    import transcribe as TR
    words = load_words()
    x = load_audio(a.take)
    dur = len(x) / SR
    db = envelope(x)
    speech, odd, thr = speech_regions(db, words)
    paras = script_text(a.script)
    pe, missing, extra, sc = align_script(paras, words) if paras else ([], [], [], '')
    plan = load_plan()
    sp, rate = resolve_speed(plan['SPEED'], words)
    P = pauses_of(speech, dur)
    lines = [f'# 粗剪扫描 · {os.path.basename(a.take)}', '',
             f'- 原始 {dur:.1f} s，说话 {sum(e - s for s, e in speech):.1f} s，静音门限 {thr:.0f} dB（实测包络）',
             f'- 停顿 {len(P)} 处，其中超过 {NATURAL} s（按 {sp}x 后算）的 {sum((b - s_) / sp > NATURAL for s_, b in P)} 处',
             f'- 语速 {rate:.2f} 字/秒 → SPEED {sp}x（默认不变速；cut_plan.py 里可以改）',
             f'- 口播稿：{"读到 %d 段" % len(paras) if paras else "没找到，段落停顿只能靠 PARA 手填"}', '']
    # chunks between pauses > 0.35 s raw, each transcribed alone with no prompt
    cuts = [p for p in P if p[1] - p[0] > 0.35]
    bounds, s0 = [], speech[0][0] if speech else 0.0
    for p in cuts:
        bounds.append((s0, p[0])); s0 = p[1]
    bounds.append((s0, speech[-1][1] if speech else dur))
    x16 = x[::3].astype(np.float32)             # 48k -> 16k (the envelope already showed where speech is)
    chunks = []
    for c0, c1 in bounds:
        if c1 - c0 < 0.2: continue
        seg = x16[max(0, int((c0 - 0.1) * 16000)):int((c1 + 0.1) * 16000)]
        r = TR.transcribe(seg, words=False, prev_text=False)
        txt = r['text'].strip()
        main = ''.join(w['word'] for w in words if c0 - 0.3 <= w['start'] < c1 - 0.05)
        chunks.append(dict(t0=c0, t1=c1, text=txt, main=main))
        print(f'{c0:7.2f}-{c1:7.2f}  {txt}', flush=True)
    # suspected retakes: a chunk whose text the next one or two chunks start with again
    sus = []
    for i, c in enumerate(chunks):
        ci = norm(c['text'])
        if len(ci) < 2: continue
        for j in (i + 1, i + 2):
            if j >= len(chunks): break
            cj = norm(chunks[j]['text'])
            k = min(len(ci), len(cj))
            if k < 2: continue
            r = difflib.SequenceMatcher(None, ci[:k], cj[:k]).ratio()
            if r >= 0.6 and (ci + ci[:k]) not in sc and ci[:k] + cj[:k] not in sc:
                sus.append((i, j, r)); break
    lines += ['## 疑似重说 / 说一半重来（挑最好的一遍：没口误、语调饱满；差不多就列候选让用户选；分不出来留后录的）', '']
    if not sus:
        lines += ['没发现。', '']
    for i, j, r in sus:
        c, d = chunks[i], chunks[j]
        lines += [f'- {c["t0"]:.2f}–{c["t1"]:.2f}「{c["text"]}」→ {d["t0"]:.2f} 又说「{d["text"]}」（相似 {r:.0%}）',
                  f'  听两遍再定。留后一遍：`({c["t0"]:.2f}, {d["t0"]:.2f}, \'重说：留 {d["t0"]:.1f} 那遍\'),`'
                  f'；留前一遍：删掉 {d["t0"]:.2f} 开始的那遍（DROP 写它的起止）']
    flag = [c for c in chunks if re.search('不要了|重来|再来一遍|重新说|说错了|剪掉|这段删', c['text'])]
    if flag:
        lines += ['', '## 录音里的口头指示（"这个不要了"之类）', '']
        lines += [f'- {c["t0"]:.2f}–{c["t1"]:.2f}「{c["text"]}」' for c in flag]
    swallowed = [c for c in chunks if len(norm(c['text'])) - len(norm(c['main'])) >= 3]
    lines += ['', '## 主转写漏掉的话（单独转写多出来的，常是被吞掉的重说）', '']
    lines += [f'- {c["t0"]:.2f}–{c["t1"]:.2f} 单独转写「{c["text"]}」，主转写只有「{c["main"]}」' for c in swallowed] or ['没有。']
    lines += ['', '## 有声音但没字（口癖、吸气、杂音；长而响的按说话保留）', '']
    lines += [f'- {s:.2f}–{e:.2f}（{e - s:.2f} s，{lv:.0f} dB）' for s, e, lv in odd] or ['没有。']
    if paras:
        lines += ['', '## 稿子里有、录音里没有', '']
        lines += [f'- {s}' for s in missing] or ['没有。']
        lines += ['', '## 录了、稿子里没有（即兴、口误或重说）', '']
        lines += [f'- {t0:.2f}–{t1:.2f}「{s}」' for t0, t1, s in extra] or ['没有。']
    lines += ['', '## 停顿（原始时间 → 粗剪后，单位秒，已按倍速）', '']
    for p in P:
        if p[1] - p[0] <= 0.12: continue
        k = kind_of(p, words, pe, plan['PARA'])
        o = (p[1] - p[0]) / sp
        new = o if o <= NATURAL else min(o, TARGET[k])
        lines.append(f'- {p[0]:.2f}–{p[1]:.2f} {k:6s} {o:.2f} → {new:.2f}')
    lines += ['', '## 分段单独转写', '']
    lines += [f'- {c["t0"]:.2f}–{c["t1"]:.2f} {c["text"]}' for c in chunks]
    open('粗剪_扫描.md', 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print('->', '粗剪_扫描.md', f'({len(sus)} suspected retakes, {len(missing)} script lines not found)')


def load_plan():
    if not os.path.exists(a.plan):
        open(a.plan, 'w', encoding='utf-8').write(PLAN_TEMPLATE)
        print('wrote', a.plan, '(empty plan: only pauses and speed)')
    g = {}
    exec(open(a.plan, encoding='utf-8').read(), g)
    return dict(SPEED=g.get('SPEED', 1.0), DROP=g.get('DROP', []), PARA=g.get('PARA', []), KEEP=g.get('KEEP', {}))


def units(s):
    return len(re.findall(r'[\u4e00-\u9fff]', s)) + len(re.findall(r'[A-Za-z]+|\d+', s))


def speech_rate(words):
    """字/秒：说话时每秒几个字（汉字 + 英文单词 + 数字，停顿最多算 0.6 秒）"""
    ws = [w for w in words if w['end'] - w['start'] > 0.02]
    sp = sum(min(b['start'] - a['start'], 0.6) for a, b in zip(ws, ws[1:]))
    return units(''.join(w['word'] for w in ws)) / max(sp, 1e-6)


def resolve_speed(v, words):
    r = speech_rate(words)
    if v == 'auto':
        v = round(min(1.2, max(1.0, TARGET_RATE / r)) * 20) / 20
        print(f'speech rate {r:.2f} 字/秒 -> SPEED auto = {v}x (target {TARGET_RATE} 字/秒)')
    return float(v), r


# ------------------------------------------------------------------ cut
def probe_v(path):
    out = subprocess.run([tools.FFPROBE, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                          'stream=width,height,r_frame_rate,start_time', '-of', 'json', path],
                         capture_output=True, text=True).stdout
    st = json.loads(out).get('streams') or []
    return st[0] if st else None


def cut():
    plan = load_plan()
    words = load_words()
    sp, rate = resolve_speed(plan['SPEED'], words)
    x = load_audio(a.take)
    dur = len(x) / SR
    db = envelope(x)
    speech, odd, thr = speech_regions(db, words)
    paras = script_text(a.script)
    pe = align_script(paras, words)[0] if paras else []
    v = probe_v(a.take)
    fps = 30.0
    grid = lambda t: round(t * fps) / fps
    start, end = max(0.0, speech[0][0] - HEAD * sp), min(dur, speech[-1][1] + TAIL * sp)
    removes, log = [], dict(drop=[], pause={k: [0, 0.0] for k in TARGET})
    # drops first: each one is widened to the silences around it, and the whole gap follows the pause rules
    drops = []
    for d in plan['DROP']:
        d0, d1, why = d[0], d[1], d[2]
        gap = d[3] if len(d) > 3 else None
        a0 = snap(d0, speech, 'start')                    # offset of the speech before the cut
        before = [s for s in speech if s[1] <= a0 + 1e-6]
        a0 = before[-1][1] if before else start
        b1 = snap(d1, speech, 'end')
        after = [s for s in speech if s[0] >= b1 - 1e-6]
        b1 = after[0][0] if after else end
        k = kind_of((a0, b1), words, pe, plan['PARA'])
        tgt = gap if gap is not None else TARGET[k]
        drops.append((a0, b1, tgt, why, d0, d1))
    for a0, b1, tgt, why, d0, d1 in drops:
        tr = tgt * sp
        r0, r1 = a0 + tr * TAIL_SHARE, b1 - tr * (1 - TAIL_SHARE)
        if r1 > r0:
            removes.append((r0, r1))
        said = ''.join(w['word'] for w in words if d0 - 0.05 <= w['start'] < d1)
        log['drop'].append((d0, d1, why, said, r0))
    for p in pauses_of(speech, dur):
        if any(dd[0] - 0.01 <= p[0] < dd[1] + 0.01 or dd[0] - 0.01 < p[1] <= dd[1] + 0.01 for dd in drops):
            continue
        o = (p[1] - p[0]) / sp
        k = kind_of(p, words, pe, plan['PARA'])
        tgt = TARGET[k]
        for kt, kv in plan['KEEP'].items():
            if p[0] - 0.05 <= kt <= p[1] + 0.05:
                tgt = kv
        if o <= NATURAL or o <= tgt:
            continue
        tr = tgt * sp
        removes.append((p[0] + tr * TAIL_SHARE, p[1] - tr * (1 - TAIL_SHARE)))
        log['pause'][k][0] += 1; log['pause'][k][1] += o - tgt
    # keep = [start, end] minus removes, on the source frame grid
    removes = sorted((grid(r0), grid(r1)) for r0, r1 in removes if grid(r1) > grid(r0))
    keep, cur = [], grid(start)
    for r0, r1 in removes:
        if r0 > cur: keep.append((cur, r0))
        cur = max(cur, r1)
    if grid(end) > cur: keep.append((cur, grid(end)))
    # map raw -> cut
    segs, n = [], 0.0
    for k0, k1 in keep:
        segs.append([round(k0, 4), round(k1, 4), round(n, 4), round(n + (k1 - k0) / sp, 4)])
        n += (k1 - k0) / sp
    json.dump(dict(take=os.path.abspath(a.take), speed=sp, raw_dur=round(dur, 3), new_dur=round(n, 3), segs=segs),
              open('cut_map.json', 'w', encoding='utf-8'), indent=1)
    # audio: slice in numpy (8 ms fades at each join, all of them inside silence), then atempo in ffmpeg
    tmp = '_cut_tmp.wav'
    subprocess.run([tools.FFMPEG, '-v', 'error', '-y', '-i', a.take, '-vn', '-ac', '2', '-ar', str(SR), '-c:a', 'pcm_f32le', tmp],
                   check=True)
    _, xa = wavfile.read(tmp)
    os.remove(tmp)
    f = int(0.008 * SR)
    parts = []
    for k0, k1 in keep:
        y = xa[int(round(k0 * SR)):int(round(k1 * SR))].astype(np.float64).copy()
        if len(y) > 2 * f:
            ramp = np.linspace(0, 1, f)[:, None]
            y[:f] *= ramp; y[-f:] *= ramp[::-1]
        parts.append(y)
    wavfile.write('_cut_audio.wav', SR, np.concatenate(parts).astype(np.float32))
    if v is None:
        out = '口播_粗剪.wav'
        subprocess.run([tools.FFMPEG, '-v', 'error', '-y', '-i', '_cut_audio.wav', '-af', f'atempo={sp}', '-c:a', 'pcm_f32le', out],
                       check=True)
    else:
        out = '口播_粗剪.mp4'
        sel = '+'.join(f'between(t,{k0 - 0.5 / fps:.4f},{k1 - 0.5 / fps:.4f})' for k0, k1 in keep)   # frames k0 .. k1-1/fps
        fg = f"[0:v]fps={fps:g},select='{sel}',setpts=N/({fps:g}*{sp})/TB,fps={fps:g}[v];[1:a]atempo={sp}[a]"
        subprocess.run([tools.FFMPEG, '-v', 'error', '-y', '-i', a.take, '-i', '_cut_audio.wav', '-filter_complex', fg,
                        '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-preset', 'medium', '-crf', '16',
                        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '320k', '-ar', str(SR), '-movflags', '+faststart', out],
                       check=True)
    os.remove('_cut_audio.wav')
    # report
    to_new = lambda t: next((s[2] + (t - s[0]) / sp for s in segs if s[0] <= t <= s[1]),
                            next((s[2] for s in segs if s[0] > t), n))
    L = [f'# 粗剪说明 · {os.path.basename(a.take)} → {out}', '',
         f'- 时长：原始 {dur:.1f} s → 粗剪 {n:.1f} s（{sp}x，音调不变；停顿和剔除共去掉 {(dur - (end - start)) + sum(r1 - r0 for r0, r1 in removes):.1f} s 原始时间）',
         f'- 语速：说话时约 {rate:.1f} 字/秒 → {rate * sp:.1f} 字/秒（{sp}x；常见口播 5.0–5.9 字/秒）',
         f'- 开头留 {HEAD} s、结尾留 {TAIL} s；超过 {NATURAL} s 的停顿压到：犹豫/逗号 0.40、句号 0.55、换段 0.70（粗剪后秒数）',
         '']
    L += ['## 停顿', '']
    names = dict(hes='句内犹豫', comma='逗号', period='句号/问号', para='换段')
    for k, (cnt, saved) in log['pause'].items():
        L.append(f'- {names[k]}：压短 {cnt} 处，省 {saved:.1f} s')
    L += ['', '## 剔除（重说挑最好的一遍；说一半重来的半句删掉）', '']
    if not log['drop']:
        L.append('没有。')
    for d0, d1, why, txt, r0 in log['drop']:
        L.append(f'- 原始 {d0:.2f}–{d1:.2f} → 粗剪 {to_new(r0):.2f} 处拼接：{why}。去掉的是「{txt}」')
    if paras:
        _, missing, extra, _ = align_script(paras, words)
        L += ['', '## 稿子里有、录音里没有（粗剪前就缺）', '']
        L += [f'- {s}' for s in missing] or ['没有。']
        kept_extra = [(t0, t1, s) for t0, t1, s in extra if not any(d0 - 0.1 <= t0 <= d1 + 0.1 for d0, d1, *_ in log['drop'])]
        L += ['', '## 录了、稿子里没有（保留了，按录音走）', '']
        L += [f'- 粗剪 {to_new(t0):.2f}「{s}」' for t0, t1, s in kept_extra] or ['没有。']
    L += ['', '## 需复查', '']
    chk = [f'- 粗剪 {to_new(r0):.2f}：剔除后的拼接（{why}）' for d0, d1, why, txt, r0 in log['drop']]
    chk += [f'- 粗剪 {to_new(s):.2f}：有声音但没字（{e - s:.2f} s），没剪' for s, e, lv in odd if e - s >= 0.25 and start < s < end]
    L += chk or ['没有。']
    open('粗剪说明.md', 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print(f'{dur:.1f} s -> {n:.1f} s ({len(keep)} pieces, {len(log["drop"])} drops) -> {out}, cut_map.json, 粗剪说明.md')


scan() if a.mode == 'scan' else cut()
