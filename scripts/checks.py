"""Automatic picture checks, run before the render (the ideas come from dashi-animationstyle's
卡点 / 丰富度 / 480 宽 checks). Cheap: frames only, no video. Times are voice times (scenes.py / cues.py).

usage (in _工程): python checks.py [all|marks|rich|phone] [t0 t1]
writes 检查/卡点.png, 检查/丰富度.png, 检查/手机.png and 检查/检查报告.md, and prints every flag.

  marks  every scene sound (cues.scene_cues(), or all_cues() minus the automatic transition sounds) stands for a visual
         event. The stage 0.1 s before the sound and 0.35 s after it: the change must happen between the two.
         Flags 「音效响了画面没动」 (nothing changes around the sound) and 「画面提前动了」 (most of the change is
         already done 0.1 s before the sound: move the sound earlier or the animation later).
  rich   the stage every 0.5 s. Flags every stretch of > 2.5 s where it hardly changes (talking-head beats are
         not counted): give it a secondary move — the next element landing, a push-in, a highlight, a focus pull.
  phone  one frame per page shrunk to 480 px wide (how a phone shows it), for a readability look; plus every text
         drawn smaller than 12 px at that size (48 px on a 1920-wide frame, 27 px on a 1080-wide one), with its page.
"""
import sys, os, inspect, bisect, json
import numpy as np
from scipy import ndimage
import lib

# ---- log the size every text is drawn at (patched before scenes.py imports lib's names)
_rec, _log = [False], []
_text = lib.text


def _logged_text(c, s, x, y, size, *args, **kw):
    if _rec[0] and s and s.strip():
        m = c.getTotalMatrix()
        sc = (m.getScaleX() ** 2 + m.getSkewY() ** 2) ** 0.5
        kind = kw.get('kind', args[1] if len(args) > 1 else 'cn')
        align = kw.get('align', args[2] if len(args) > 2 else 'c')
        w = lib.text_w(s, size, kind)
        x0 = x - w / 2 if align == 'c' else (x if align == 'l' else x - w)
        r = m.mapRect(skia.Rect.MakeXYWH(x0, y - size * 0.55, w, size * 1.1))
        _log.append((s, size * sc, (r.left(), r.top(), r.right(), r.bottom())))
    return _text(c, s, x, y, size, *args, **kw)


import skia
lib.text = _logged_text
import render as R
import scenes as SC
import cues
import cuelib
from PIL import Image, ImageDraw, ImageFont

OUT = '检查'
os.makedirs(OUT, exist_ok=True)
mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
T0 = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
T1 = float(sys.argv[3]) if len(sys.argv) > 3 else R.DUR
MIN_PX = 12 * lib.W / 480
FPS = lib.FPS
try:
    import fonts
    FNT = ImageFont.truetype(fonts.path('noto_sans_sc'), 22)
except Exception:
    FNT = ImageFont.load_default()
import layout

# ---- words (for labels) and pages
words = []
if os.path.exists('transcript.json'):
    tj = json.load(open('transcript.json', encoding='utf-8'))
    words = [w for s in tj['segments'] for w in s.get('words', []) if w['word'].strip()]
w0 = [w['start'] for w in words]


def said_at(t, n=4):
    i = bisect.bisect_right(w0, t + 0.12) - 1
    return ''.join(w['word'].strip() for w in words[max(0, i - 1):i + n - 1])


TL = SC.TIMELINE


def page_at(t):
    i = max(0, bisect.bisect_right([d['t'] for d in TL], t) - 1)
    d = TL[i]
    if d.get('host'):
        return i, '出镜'
    if 'mg' in d:
        return i, getattr(d['mg'], '__name__', 'mg')
    return i, 'clip:' + os.path.basename(d['clip'][0])


# ---- one ascending pass over every time needed (embedded clips can only be read forwards)
Rd = R.Renderer()
_stage_args = len(inspect.signature(Rd.stage).parameters)
SMALL = 240


def stage_img(t):
    f = int(round(t * FPS))
    img = Rd.stage(t, f) if _stage_args == 2 else Rd.stage(t, f, False)
    a = img.toarray()[:, :, :3] if hasattr(img, 'toarray') else np.array(img)[:, :, :3]
    return Image.fromarray(a)


def gray(im):
    """small RGB copy; differences take the largest channel, so a yellow highlight on beige paper still shows"""
    h = round(im.height * SMALL / im.width)
    return np.asarray(im.convert('RGB').resize((SMALL, h), Image.BILINEAR), np.float32)


def dmap(a, b):
    return np.abs(a - b).max(2)


need = {}                                         # t -> set of uses
def want(t, use):
    if T0 - 0.6 <= t <= T1 + 0.4 and 0 <= t < R.DUR:
        need.setdefault(round(t, 3), set()).add(use)


events = []
if mode in ('all', 'marks'):
    if hasattr(cues, 'scene_cues'):
        cl = [c_ for c_ in cues.scene_cues() if c_]
    else:
        auto = set(map(repr, cuelib.transition_cues(SC)))
        cl = [c for c in cues.all_cues() if c and repr(c) not in auto]
    ts = sorted(c[3].get('_anchor', c[0]) for c in cl)
    for t in ts:                                  # sounds within 0.12 s of each other are one event
        if T0 <= t <= T1 and (not events or t - events[-1] > 0.12):
            events.append(t)
    for t in events:
        for dt in (-0.3, -0.1, 0.35):
            want(t + dt, 'marks')
if mode in ('all', 'rich'):
    k = np.arange(np.ceil(T0 * 2) / 2, T1, 0.5)
    for t in k:
        want(float(t), 'rich')
phone_t = []
if mode in ('all', 'phone'):
    for i, d in enumerate(TL):
        a_ = d['t']; b_ = TL[i + 1]['t'] if i + 1 < len(TL) else R.DUR
        if b_ < T0 or a_ > T1: continue
        t = min(max(a_ + 1.2, (a_ + b_) / 2), b_ - 0.3)
        phone_t.append(round(t, 3)); want(t, 'phone')

G, THUMB, PHONE, TXT = {}, {}, {}, {}
print(f'rendering {len(need)} frames ...', flush=True)
for t in sorted(need):
    uses = need[t]
    if 'phone' in uses:
        f = int(round(t * FPS))
        _rec[0] = True; _log.clear()
        fr = Rd.render(t, f)
        _rec[0] = False
        TXT[t] = list(_log)
        im = Image.fromarray(fr[:, :, :3].copy())
        PHONE[t] = im.resize((480, round(480 * im.height / im.width)), Image.LANCZOS)
    if uses & {'marks', 'rich'}:
        im = stage_img(t)
        G[t] = gray(im)
        if 'marks' in uses:
            THUMB[t] = im.resize((320, round(320 * im.height / im.width)), Image.BILINEAR)

diff = lambda a, b: float(dmap(G[round(a, 3)], G[round(b, 3)]).mean()) if round(a, 3) in G and round(b, 3) in G else None
report = [f'# 自动检查 · {T0:.1f}–{T1:.1f} s', '']
flags_total = 0

# ---- marks
if mode in ('all', 'marks'):
    # a page transition moves the whole stage: sounds inside one are not judged
    trw = [(d['t'] - lib._td(d) / 2 - 0.1, d['t'] + lib._td(d) / 2 + 0.45) for d in TL[1:] if lib._td(d) > 0]
    rows, judged = [], []
    for t in events:
        k = [round(t + dt, 3) for dt in (-0.3, -0.1, 0.35)]
        if any(x not in G for x in k): continue
        i, name = page_at(t)
        if name == '出镜' or any(a <= t <= b for a, b in trw): continue
        # net change over the window (-0.3 -> +0.35 s), split into before / after the sound. Paper pages jitter at 12
        # drawings/s all the time; that jitter adds to both halves alike, so only the split is judged
        net = dmap(G[k[2]], G[k[0]])
        R_ = ndimage.binary_opening(net > 24, np.ones((3, 3)))   # jitter leaves thin edges; an element is a blob
        area = float(R_.mean())
        why = None
        if area < 0.0008:
            why = '音效响了画面没动'
        else:
            pre, post = dmap(G[k[1]], G[k[0]])[R_].mean(), dmap(G[k[2]], G[k[1]])[R_].mean()
            if pre > 1.2 * post:
                why = '画面提前动了'
        judged.append((t, name, why, area))
        if why: rows.append((t, name, why, area))
    report += [f'## 卡点（{len(events)} 个音效事件，判了 {len(judged)} 个，{len(rows)} 个可疑）', '',
               '音效前 0.3 s 到后 0.35 s 的净变化，大半要发生在音效之后（0.1 s 前那帧为界）；转场中、出镜段的音效不判。', '']
    report += [f'- {t:.2f} {name}「{said_at(t)}」：{why}（变化面积 {area:.2%}）' for t, name, why, area in rows] or ['没有。']
    flags_total += len(rows)
    show = judged if len(judged) <= 40 else rows      # a short range shows every pair for a visual look
    if show:
        th = THUMB[round(show[0][0] - 0.1, 3)]
        W_, H_ = th.width, th.height
        cols = 2 if W_ > H_ else 4
        cw = W_ * 2 + 16
        sheet = Image.new('RGB', (cols * (cw + 24), ((len(show) + cols - 1) // cols) * (H_ + 40)), 'white')
        dr = ImageDraw.Draw(sheet)
        for r, (t, name, why, area) in enumerate(show):
            x, y = (r % cols) * (cw + 24), (r // cols) * (H_ + 40)
            dr.text((x + 4, y + 6), f'{t:.2f} {name}「{said_at(t, 3)}」' + (f' {why}' if why else ''),
                    fill='red' if why else 'black', font=FNT)
            sheet.paste(THUMB[round(t - 0.1, 3)], (x, y + 36)); sheet.paste(THUMB[round(t + 0.35, 3)], (x + W_ + 16, y + 36))
        sheet.save(f'{OUT}/卡点.png')

# ---- richness
if mode in ('all', 'rich'):
    ks = sorted(t for t in G if 'rich' in need.get(t, ()))
    d_ = [(a, diff(a, b)) for a, b in zip(ks, ks[1:])]
    stretches, cur = [], []
    for a, v in d_:
        quiet = v < 0.8 and page_at(a)[1] != '出镜'
        if quiet: cur.append(a)
        if not quiet or a == d_[-1][0]:
            if cur and (cur[-1] + 0.5 - cur[0]) > 2.5:
                stretches.append((cur[0], cur[-1] + 0.5))
            cur = []
    mean = np.mean([v for _, v in d_]) if d_ else 0
    report += ['', f'## 丰富度（每 0.5 s 一帧，平均变化 {mean:.1f}；{len(stretches)} 段超过 2.5 s 几乎不动）', '']
    report += [f'- {a:.1f}–{b:.1f}（{b - a:.1f} s）{page_at(a)[1]}「{said_at(a, 8)}」' for a, b in stretches] or ['没有。']
    flags_total += len(stretches)
    if ks:                                    # strip: one cell per 2.5 s, red frame on quiet stretches
        cells = [t for t in ks if abs((t * 2) % 5) < 1e-6]
        cw = 160; ch = round(G[cells[0]].shape[0] * 160 / SMALL)
        cols = 8
        sheet = Image.new('RGB', (cols * (cw + 6), ((len(cells) + cols - 1) // cols) * (ch + 30)), 'white')
        dr = ImageDraw.Draw(sheet)
        for n, t in enumerate(cells):
            x, y = (n % cols) * (cw + 6), (n // cols) * (ch + 30)
            sheet.paste(Image.fromarray(G[t].astype(np.uint8)).resize((cw, ch)), (x, y + 24))
            q = any(a <= t < b for a, b in stretches)
            dr.text((x + 2, y + 2), f'{t:.1f}', fill='red' if q else 'black', font=FNT)
            if q: dr.rectangle([x, y + 24, x + cw - 1, y + 24 + ch - 1], outline='red', width=3)
        sheet.save(f'{OUT}/丰富度.png')

# ---- phone
if mode in ('all', 'phone'):
    small = {}
    under = {}
    for t in phone_t:
        pip = (Rd.host is not None and lib.full_amount(t, Rd.windows) < 0.01 and Rd.pip_amount(t) > 0.5)
        for s, px, box in TXT.get(t, []):
            if px < MIN_PX and s.strip():
                key = (page_at(t)[1], s.strip())
                small[key] = min(px, small.get(key, 1e9))
            sx0, sy0, sx1, sy1 = layout.PIP_SAFE
            if pip and box[0] < sx1 and box[2] > sx0 and box[1] < sy1 and box[3] > sy0 and px >= MIN_PX * 0.6:
                under[(page_at(t)[1], s.strip())] = t
    report += ['', f'## 手机上看（缩到 480 宽；字小于 {MIN_PX:.0f} px 的列出来，装饰性小字可以不管）', '']
    report += [f'- {name}：「{s[:20]}」{px:.0f} px' for (name, s), px in sorted(small.items(), key=lambda kv: kv[1])] or ['没有。']
    flags_total += len(small)
    if Rd.host is not None:
        report += ['', f'## 被人物小窗挡住（横屏左上角 {layout.PIP_SAFE[2]}x{layout.PIP_SAFE[3]} 这块）', '']
        report += [f'- {t:.1f} {name}：「{s[:20]}」' for (name, s), t in under.items()] or ['没有。']
        flags_total += len(under)
    if phone_t:
        ims = [PHONE[t] for t in phone_t]
        cols = 4 if ims[0].height < ims[0].width else 5
        cw, ch = ims[0].width, ims[0].height
        sheet = Image.new('RGB', (cols * (cw + 8), ((len(ims) + cols - 1) // cols) * (ch + 30)), 'white')
        dr = ImageDraw.Draw(sheet)
        for n, (t, im) in enumerate(zip(phone_t, ims)):
            x, y = (n % cols) * (cw + 8), (n // cols) * (ch + 30)
            dr.text((x + 2, y + 2), f'{t:.1f} {page_at(t)[1]}', fill='black', font=FNT)
            sheet.paste(im, (x, y + 28))
        sheet.save(f'{OUT}/手机.png')

open(f'{OUT}/检查报告.md', 'w', encoding='utf-8').write('\n'.join(report) + '\n')
print('\n'.join(report))
print(f'-> {OUT}/检查报告.md  ({flags_total} flags)')
