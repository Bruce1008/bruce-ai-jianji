"""Subtitles in two passes (run in _工程, after transcribe.py).

1. python make_subs.py
   -> subs_draft.txt: Whisper's text split into subtitle lines, one per line (≤ --max units, Latin ≈ 0.55)
2. Correct it into subs.txt. Use the script for wording and names (Whisper writes Cue as "Q", Manus as "Mena's",
   转 as 赚, 连上 as 脸上 ...), but keep what the speaker actually SAID. Re-split lines at natural word boundaries, one
   subtitle per line, no punctuation. Don't time anything.
3. python make_subs.py --align subs.txt
   -> subs.srt: every character is aligned to the transcript's word timestamps, so each line starts and ends on
   the words it shows. render.py burns subs.srt into the picture.
"""
import json, re, argparse, difflib

ap = argparse.ArgumentParser()
ap.add_argument('--align', metavar='SUBS_TXT', help='time a corrected subs.txt -> subs.srt')
def _default_max():
    """一行最多几个字：横屏 18，竖屏 13（看 project.json）"""
    import os
    for p in ('project.json', os.path.join('_工程', 'project.json')):
        if os.path.exists(p):
            return 13.0 if json.load(open(p, encoding='utf-8')).get('orient') == '竖屏' else 18.0
    return 18.0


ap.add_argument('--max', type=float, default=_default_max(), help='draft: max line length in CJK-character units')
ap.add_argument('--pause', type=float, default=0.45, help='draft: a silence this long ends a line')
a = ap.parse_args()

STOP = '。？！?!'
SOFT = '，,、；;：:'
PUNCT = '，。、；：！？,.;:!?…'


def units(s):
    return sum(1.0 if ord(ch) > 0x2E7F else (0.3 if ch == ' ' else 0.55) for ch in s)


def clean(s):
    s = re.sub(f'[{PUNCT}]+$', '', s.strip())             # no punctuation at the end of a line
    s = re.sub(r'(?<=\d)\.(?=\d)', '\0', s)                # keep decimal points (15.7 分钟)
    s = re.sub(f'[{PUNCT}]+', ' ', s).replace('\0', '.')   # inside a line a pause becomes a space
    return re.sub(r'\s+', ' ', s).strip()


def norm(s):
    return [ch for ch in s.lower() if ch.isalnum()]


r = json.load(open('transcript.json', encoding='utf-8'))
words = [(w['word'], w['start'], w['end']) for seg in r['segments'] for w in seg.get('words', [])]


def ts(x):
    ms = int(round(x * 1000))
    return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'


def write_srt(cues, path):
    for k, cu in enumerate(cues):                          # hold each line a little; bridge short gaps (no flicker)
        nxt = cues[k + 1][0] if k + 1 < len(cues) else None
        cu[1] = max(cu[1] + 0.15, cu[0] + 0.7)
        if nxt is not None and (nxt - cu[1] < 0.4 or cu[1] > nxt):
            cu[1] = nxt
    with open(path, 'w', encoding='utf-8') as f:
        for k, (s, e, txt) in enumerate(cues, 1):
            f.write(f'{k}\n{ts(s)} --> {ts(e)}\n{txt}\n\n')


if not a.align:
    lines, cur = [], []
    for i, (w, t0, t1) in enumerate(words):
        if cur and units(clean(''.join(x[0] for x in cur) + w)) > a.max:
            k = len(cur)                                   # don't split an English phrase across two lines
            if re.match(r'\s?[A-Za-z0-9]', w) and re.search(r'[A-Za-z0-9]$', cur[-1][0].strip()):
                while k > 1 and re.match(r'\s?[A-Za-z0-9]', cur[k - 1][0]):
                    k -= 1
            lines.append(cur[:k]); cur = cur[k:]
        cur.append((w, t0, t1))
        txt = clean(''.join(x[0] for x in cur))
        nxt = words[i + 1][1] if i + 1 < len(words) else None
        gap = (nxt - t1) if nxt is not None else 9
        end = w.strip()[-1:] if w.strip() else ''
        if end in STOP or (end in SOFT and units(txt) >= 6) or (gap > a.pause and units(txt) >= 4):
            lines.append(cur); cur = []
    if cur:
        lines.append(cur)
    out = [clean(''.join(x[0] for x in ln)) for ln in lines]
    open('subs_draft.txt', 'w', encoding='utf-8').write('\n'.join(t for t in out if t) + '\n')
    print(len(out), 'lines -> subs_draft.txt  (correct it into subs.txt, then: python make_subs.py --align subs.txt)')
else:
    # transcript characters with times (a token's characters share its span evenly)
    tc, tt0, tt1 = [], [], []
    for w, t0, t1 in words:
        cs = norm(w)
        for i, ch in enumerate(cs):
            tc.append(ch)
            tt0.append(t0 + (t1 - t0) * i / len(cs)); tt1.append(t0 + (t1 - t0) * (i + 1) / len(cs))
    subs = [ln.strip() for ln in open(a.align, encoding='utf-8') if ln.strip()]
    sc, owner = [], []
    for k, ln in enumerate(subs):
        for ch in norm(ln):
            sc.append(ch); owner.append(k)
    m = [None] * len(sc)
    for blk in difflib.SequenceMatcher(None, sc, tc, autojunk=False).get_matching_blocks():
        for j in range(blk.size):
            m[blk.a + j] = blk.b + j
    known = [i for i, v in enumerate(m) if v is not None]
    if not known:
        raise SystemExit('nothing in subs.txt matches the transcript')

    def t_of(i, end=False):
        """time of subtitle char i; unmatched chars (corrected words) are interpolated between matched neighbours"""
        if m[i] is not None:
            return tt1[m[i]] if end else tt0[m[i]]
        lo = max((k for k in known if k < i), default=None)
        hi = min((k for k in known if k > i), default=None)
        if lo is None: return tt0[m[hi]]
        if hi is None: return tt1[m[lo]]
        # at a line's edge (他 said, 它 written) stick to this line's own words, not the middle of the pause before it
        if owner[lo] != owner[i] and owner[hi] == owner[i]: return max(tt1[m[lo]], tt0[m[hi]] - .18 * (hi - i))
        if owner[hi] != owner[i] and owner[lo] == owner[i]: return min(tt0[m[hi]], tt1[m[lo]] + .18 * (i - lo))
        f = (i - lo) / (hi - lo)
        return tt1[m[lo]] + (tt0[m[hi]] - tt1[m[lo]]) * f
    cues = []
    for k, ln in enumerate(subs):
        idx = [i for i, o in enumerate(owner) if o == k]
        if idx:
            cues.append([t_of(idx[0]), t_of(idx[-1], True), clean(ln)])
    matched = len(known) / max(1, len(sc))
    write_srt(cues, 'subs.srt')
    print(f'{len(cues)} lines -> subs.srt  ({matched:.0%} of characters matched the transcript)')
    if matched < 0.8:
        print('WARNING: low match — check that subs.txt follows the recording, not the script')
