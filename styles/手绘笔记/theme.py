"""手绘笔记：米白纸上的墨蓝钢笔线稿 + 一种橙色。线一笔笔描出来，字一个个写出来，页边的铅笔小涂鸦一直在画。
风格卡.md 是给人看的说明；这个文件是给 scenes.py 用的部件。

scenes.py 开头：
    import theme as T          # 要在 from lib import * 之前
    from lib import *

每个画面函数第一行先铺纸：T.paper(c, t)
部件（t = 当前时间，t0 = 这个东西开始出现的时间，都是口播时间秒数）：
  线稿    T.hline  T.hbox  T.hcircle  T.hunder  T.harrow  T.hcheck  T.hcross  T.hdash  T.squiggle  T.hatch  T.lead
  文字    T.write（逐字写出，可带笔尖） T.tag（@标签） T.title（虚线框标题） T.stamp（橡皮章） T.block_word（实心色块词）
          T.marker（马克笔淡橙高亮） T.en（错影英文）
  纸和图  T.sheet（纸片 / 便签） T.photo（贴在纸上的照片，图片或视频帧） T.clip_img（取视频帧）
  动      T.cam（整页慢推） T.pen（笔尖） T.shake（盖章震一下）
转场：scroll（往下读，默认）、page（翻页）、erase（橡皮擦掉）；内置的 zoom 也合适。
"""
import math, functools
from contextlib import contextmanager
import numpy as np
import skia
import lib
from lib import *  # noqa: F401,F403
from lib import clamp, prog, e_out, e_in, e_io, e_back, lerp, paint, col, text, text_w, xf, partial_path, wobble_path

# ---------- 配色 ----------
PAPER = (246, 246, 239)       # 纸：全屏底
SHEET = (252, 252, 248)       # 白纸：纸片、照片白边、字幕纸条
INK = (21, 25, 45)            # 墨蓝：线稿、字、标签底
PENCIL = (152, 153, 154)      # 铅笔灰：涂鸦、占位线
PENCIL2 = (185, 186, 186)
PENCIL3 = (212, 213, 211)     # 浅灰：虚线、格子
ORANGE = (248, 113, 28)       # 唯一的强调色：圈、勾、下划线、印章
ORANGE_DK = (166, 61, 10)
ORANGE_LT = (253, 230, 210)   # 马克笔扫过的淡橙
ACCENT, ACCENT2, MUTE = ORANGE, INK, PENCIL   # 所有风格通用的名字：强调色 A、强调色 B、次要灰
lib.use_palette(INK=INK, SUBINK=(64, 68, 88), MUTE=PENCIL, LINE=PENCIL3, BG=PAPER, ACC=ORANGE, ACC2=INK)

# ---------- 字体（全部开源可商用，第一次用时自动下载） ----------
#   hand：小赖（手写），正文、标签、字幕；round：站酷快乐体（圆粗），标题、印章；en / num：Nunito（圆头英文、数字）
lib.use_kinds(hand=('xiaolai', 400, 0.34), round=('zcool_kuaile', 400, 0.36), en=('nunito', 800, 0.35),
              num=('nunito', 900, 0.35), sub=('xiaolai', 400, 0.34),
              cn=('xiaolai', 400, 0.34), cn_med=('xiaolai', 400, 0.34), cn_reg=('xiaolai', 400, 0.34),
              cn_black=('zcool_kuaile', 400, 0.36))

# ---------- 转场 ----------
lib.DEFAULT_TR = 'scroll'
ALT_TR = 'page'               # 换话题时用的第二种转场：scenes.py 里写 tr=T.ALT_TR
lib.TR_D.update(scroll=0.5, page=0.62, erase=0.78)

# ---------- 音效（cues.py 里写 cue(t, '@drop') 这类，按这张表换成具体声音） ----------
SFX = {'write': ('pen', -8), 'drop': ('paper_drop', -6), 'pop': ('pop', -4), 'mark': ('marker', -4),
       'stamp': ('stamp', 0), 'stick': ('tape', -8), 'tick': ('pen', -6), 'number': ('pop', -3),
       'whoosh': ('paper_slide', -6)}


# ======================================================================
# 纸：底色 + 纸纹 + 慢慢漂的光影 + 页边铅笔涂鸦（背景一直在动）
# ======================================================================

@functools.lru_cache(4)
def _paper_tile(n=384, seed=11):
    surf = skia.Surface(n, n)
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    rng = np.random.default_rng(seed)
    for _ in range(14):                                   # 大块的淡斑
        c.drawCircle(*rng.uniform(0, n, 2), rng.uniform(30, 90), paint((120, 110, 90), rng.uniform(0.012, 0.025), blur=30))
    for _ in range(1100):                                 # 墨点
        c.drawCircle(*rng.uniform(0, n, 2), rng.uniform(0.3, 0.9), paint(INK, rng.uniform(0.03, 0.09)))
    for _ in range(70):                                   # 纤维
        x, y = rng.uniform(0, n, 2)
        a = rng.uniform(0, math.pi)
        L = rng.uniform(5, 16)
        c.drawLine(x, y, x + L * math.cos(a), y + L * math.sin(a), paint(PENCIL, rng.uniform(0.06, 0.12), stroke=0.6))
    return surf.makeImageSnapshot()


def _paper_paint():
    p = skia.Paint()
    p.setShader(_paper_tile().makeShader(skia.TileMode.kRepeat, skia.TileMode.kRepeat, lib.SAMP))
    return p


def _light(c, t):
    """两组很淡的斜向明暗带往两个方向慢慢漂，像纸页轻轻起伏"""
    for k, (ang, speed, amp) in enumerate(((0.35, 26.0, 0.035), (-0.55, -18.0, 0.028))):
        dx, dy = math.cos(ang), math.sin(ang)
        off = t * speed
        L = 900.0
        p0 = skia.Point(W / 2 + dx * (off - L), H / 2 + dy * (off - L))
        p1 = skia.Point(W / 2 + dx * off, H / 2 + dy * off)
        cs = [col((110, 95, 70), 0), col((110, 95, 70), amp), col((110, 95, 70), 0), col((255, 252, 240), amp * 0.8),
              col((110, 95, 70), 0)]
        sh = skia.GradientShader.MakeLinear([p0, p1], cs, [0, 0.25, 0.5, 0.75, 1.0], skia.TileMode.kRepeat)
        pt = skia.Paint()
        pt.setShader(sh)
        c.drawRect(skia.Rect.MakeWH(W, H), pt)


# 涂鸦：单位坐标（-1..1）的折线，一笔笔画出来
def _star():
    pts = []
    for i in range(6):
        a = -math.pi / 2 + i * 4 * math.pi / 5
        pts.append((math.cos(a), math.sin(a)))
    return [pts]


def _spiral():
    return [[(0.12 * th / 2 * math.cos(th), 0.12 * th / 2 * math.sin(th)) for th in np.linspace(0, 5.2 * math.pi, 46)]]


def _arrow():
    body = [(-1, 0.6), (-0.4, -0.2), (0.3, -0.4), (0.9, -0.1)]
    return [body, [(0.55, -0.45), (0.9, -0.1), (0.5, 0.15)]]


def _cloud():
    pts = []
    for k, (cx, cy, r) in enumerate(((-0.55, 0.15, 0.4), (-0.1, -0.2, 0.5), (0.45, 0.05, 0.42))):
        for th in np.linspace(math.pi * 0.95, math.pi * 2.05, 10):
            pts.append((cx + r * math.cos(th), cy + r * math.sin(th)))
    pts.append((0.85, 0.45))
    pts.append((-0.95, 0.45))
    pts.append(pts[0])
    return [pts]


def _bulb():
    ring = [(0.6 * math.cos(th), -0.2 + 0.6 * math.sin(th)) for th in np.linspace(math.pi * 0.75, math.pi * 2.25, 22)]
    return [ring, [(-0.3, 0.55), (0.3, 0.55)], [(-0.25, 0.75), (0.25, 0.75)], [(-0.1, 0.1), (0, -0.15), (0.1, 0.1)]]


def _sun():
    ring = [(0.42 * math.cos(th), 0.42 * math.sin(th)) for th in np.linspace(0, 2 * math.pi, 20)]
    rays = [[(0.62 * math.cos(a), 0.62 * math.sin(a)), (0.95 * math.cos(a), 0.95 * math.sin(a))]
            for a in np.linspace(0, 2 * math.pi, 9)[:-1]]
    return [ring] + rays


def _checkbox():
    return [[(-0.8, -0.8), (0.8, -0.8), (0.8, 0.8), (-0.8, 0.8), (-0.8, -0.8)], [(-0.45, 0.0), (-0.05, 0.4), (0.9, -0.9)]]


def _plane():
    return [[(-1, 0.1), (1, -0.6), (-0.2, 0.7), (-0.35, 0.15), (1, -0.6)], [(-0.35, 0.15), (-1, 0.1)]]


def _wave():
    return [[(x, 0.25 * math.sin(x * 7)) for x in np.linspace(-1, 1, 30)],
            [(x, 0.4 + 0.25 * math.sin(x * 7 + 1)) for x in np.linspace(-0.8, 0.8, 24)]]


DOODLES = [_star(), _spiral(), _arrow(), _cloud(), _bulb(), _sun(), _checkbox(), _plane(), _wave()]
DOODLE_ALPHA = 0.62


def _margin_spots():
    """页边的空位：横屏避开左上角人物小窗和字幕带，竖屏避开字幕"""
    if lib.VERTICAL:
        xs = (62, W - 62)
        return [(x, H * f) for f in (0.07, 0.24, 0.42, 0.6) for x in xs] + [(W * 0.5, 64)]
    right = [(W - 70, H * f) for f in (0.09, 0.33, 0.57, 0.8)]
    top = [(W * f, 52) for f in (0.42, 0.62, 0.82)]
    left = [(78, H * f) for f in (0.6, 0.8)]
    return right + top + left


@functools.lru_cache(512)
def _doodle_paths(k, seed):
    rng = np.random.default_rng(seed)
    rot = rng.uniform(-0.5, 0.5)
    out = []
    for poly in DOODLES[k % len(DOODLES)]:
        pts = [(x * math.cos(rot) - y * math.sin(rot), x * math.sin(rot) + y * math.cos(rot)) for x, y in poly]
        out.append(wobble_path(pts, seed=seed + len(out), amt=0.05))
    return out


def doodles(c, t, a=1.0, size=42, period=6.0, slots=3):
    """页边的铅笔小涂鸦：画出来（1 秒）→ 停一会儿 → 淡掉 → 换个地方再画一个"""
    spots = _margin_spots()
    for s in range(slots):
        tt = t + s * period / slots
        n = int(tt // period)
        ph = tt - n * period
        seed = n * 7 + s * 131
        rng = np.random.default_rng(seed)
        spot = spots[(s + slots * int(rng.integers(0, 99))) % len(spots)]
        k = int(rng.integers(0, len(DOODLES)))
        draw_p = clamp(ph / 1.0)
        alpha = (1 - clamp((ph - 4.4) / 0.8)) * DOODLE_ALPHA * a
        if alpha <= 0.01:
            continue
        paths = _doodle_paths(k, seed)
        c.save()
        c.translate(spot[0], spot[1])
        c.scale(size, size)
        pnt = paint(PENCIL, alpha, stroke=2.6 / size)
        per = 1 / len(paths)
        for i, pth in enumerate(paths):
            q = clamp((draw_p - i * per) / per)
            if q <= 0:
                break
            c.drawPath(partial_path(pth, q), pnt)
        c.restore()


def paper(c, t, head=None, doodle=True, light=True, color=None):
    """铺一页纸。head = 页眉小字（这一段讲什么，可以不给）；doodle=False 不画页边涂鸦（画面很满时）"""
    c.clear(col(color or PAPER))
    c.drawRect(skia.Rect.MakeWH(W, H), _paper_paint())
    if light:
        _light(c, t)
    if doodle:
        doodles(c, t)
    if head:
        import layout as L
        x = 60 if lib.VERTICAL else L.PIP_SAFE[2] + 40
        y = 76
        w = text(c, head, x, y, 32, SUBINK, 'hand', 'l')
        hdash(c, x, y + 30, x + w + 40, y + 30, 1.0, PENCIL2, 2.5, seed=91)


@contextmanager
def cam(c, t, t0, amt=0.04, dur=7.0, cx=None, cy=None):
    """整页慢推：从 1.0 推到 1+amt（dur 秒推完，之后停住）。纸要画在 with 外面，不然边会露出来"""
    s = 1 + amt * e_io(clamp((t - t0) / dur))
    with xf(c, CX if cx is None else cx, CY if cy is None else cy, s):
        yield


def shake(t, t0, d=0.2, amp=7.0):
    """盖章、砸下那一下的震动：返回 (dx, dy)，在 xf(dx=, dy=) 里用"""
    x = (t - t0) / d
    if x < 0 or x > 1:
        return 0.0, 0.0
    k = (1 - x) * amp
    return k * math.sin(x * 37.0), k * math.cos(x * 29.0) * 0.6


# ======================================================================
# 手绘线：同一个 seed 永远画出同一条线；p = 画到哪（0..1）
# ======================================================================

@functools.lru_cache(4096)
def _wp(pts, seed, amt, closed=False, over=0.0):
    return wobble_path(list(pts), seed=seed, amt=amt, closed=closed, overshoot=over)


def _stroke(c, path, color, w, p=1.0, a=1.0, dash=None):
    if p <= 0 or a <= 0:
        return
    pt = paint(color, a, stroke=w)
    if dash:
        pt.setPathEffect(skia.DashPathEffect.Make(list(dash), 0))
    c.drawPath(partial_path(path, p) if p < 1 else path, pt)


def hline(c, x0, y0, x1, y1, p=1.0, color=None, sw=4, seed=0, a=1.0, amt=None, dash=None):
    L = math.hypot(x1 - x0, y1 - y0)
    _stroke(c, _wp(((x0, y0), (x1, y1)), seed, amt or max(1.2, L * 0.012)), color or INK, sw, p, a, dash)


@functools.lru_cache(1024)
def _quad(x, y, w, h, seed, amt):
    rng = np.random.default_rng(seed)
    j = lambda: rng.uniform(-amt, amt)
    p = skia.Path()
    p.moveTo(x + j(), y + j())
    p.lineTo(x + w + j(), y + j())
    p.lineTo(x + w + j(), y + h + j())
    p.lineTo(x + j(), y + h + j())
    p.close()
    return p


def hbox(c, x, y, w, h, p=1.0, color=None, sw=4, seed=0, a=1.0, fill=None, over=12, dash=None, shadow=0.0):
    """手绘框：四条边各画一笔，转角出头不闭合。fill = 底色（SHEET 白纸）"""
    if p <= 0:
        return
    if shadow:
        c.drawPath(_quad(x + 6, y + 9, w, h, seed + 5, 3.0), paint(BLACK, shadow * a * clamp(p * 3), blur=12))
    if fill is not None:
        c.drawPath(_quad(x, y, w, h, seed, max(1.5, min(w, h) * 0.008)), paint(fill, a * clamp(p * 3)))
    amt = max(1.5, min(w, h) * 0.012)
    sides = (((x, y), (x + w, y)), ((x + w, y), (x + w, y + h)), ((x + w, y + h), (x, y + h)), ((x, y + h), (x, y)))
    for k, (q0, q1) in enumerate(sides):
        q = clamp(p * 4 - k)
        if q <= 0:
            break
        _stroke(c, _wp((q0, q1), seed * 31 + k, amt, False, over), color or INK, sw, q, a, dash)


@functools.lru_cache(512)
def _ellipse(cx, cy, rx, ry, seed, turns, tilt):
    rng = np.random.default_rng(seed)
    st = rng.uniform(0, 2 * math.pi)
    n = 72
    ct, s_ = math.cos(math.radians(tilt)), math.sin(math.radians(tilt))
    pts = []
    for i in range(n + 1):
        th = st + 2 * math.pi * turns * i / n
        r = 1 + 0.035 * math.sin(3 * th + seed) + 0.07 * i / n
        x, y = rx * r * math.cos(th), ry * r * math.sin(th)
        pts.append((cx + x * ct - y * s_, cy + x * s_ + y * ct))
    path = skia.Path()
    path.moveTo(*pts[0])
    for i in range(1, len(pts) - 1, 2):
        path.quadTo(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
    return path


def hcircle(c, cx, cy, rx, ry=None, p=1.0, color=None, sw=6, seed=0, a=1.0, turns=1.12, tilt=-6):
    """圈出来：一笔绕 1.1 圈，首尾错开"""
    _stroke(c, _ellipse(round(cx, 1), round(cy, 1), round(rx, 1), round(ry or rx * 0.6, 1), seed, turns, tilt),
            color or ORANGE, sw, e_io(p), a)


@functools.lru_cache(512)
def _wave_path(x0, x1, y, amp, wl, seed):
    rng = np.random.default_rng(seed)
    path = skia.Path()
    n = max(8, int((x1 - x0) / 6))
    for i in range(n + 1):
        x = x0 + (x1 - x0) * i / n
        yy = y + amp * math.sin((x - x0) / wl * 2 * math.pi) + rng.uniform(-0.6, 0.6)
        (path.moveTo if i == 0 else path.lineTo)(x, yy)
    return path


def hunder(c, x0, x1, y, p=1.0, color=None, sw=6, seed=0, a=1.0, amp=4.5, wl=34):
    """波浪下划线（马克笔）"""
    _stroke(c, _wave_path(round(x0, 1), round(x1, 1), round(y, 1), amp, wl, seed), color or ORANGE, sw, p, a)


@functools.lru_cache(256)
def _scribble(x, y, w, seed):
    """一段段长短不一的连笔小波浪，像没写完的字"""
    rng = np.random.default_rng(seed)
    path = skia.Path()
    cx = x
    while cx < x + w - 30:
        seg = min(rng.uniform(70, 190), x + w - cx)
        n = max(6, int(seg / 4))
        wl, amp, ph = rng.uniform(15, 24), rng.uniform(4, 7), rng.uniform(0, 6.28)
        for i in range(n + 1):
            xx = cx + seg * i / n
            yy = y + amp * math.sin((xx - cx) / wl * 6.283 + ph) * (0.6 + 0.4 * math.sin(i * 0.7 + seed)) + rng.uniform(-0.8, 0.8)
            (path.moveTo if i == 0 else path.lineTo)(xx, yy)
        cx += seg + rng.uniform(16, 30)
    return path


def squiggle(c, x, y, w, p=1.0, color=None, sw=3, seed=0, a=1.0):
    """没写完的字：一行铅笔灰的连笔波浪（一段段的，像字）"""
    _stroke(c, _scribble(round(x, 1), round(y, 1), round(w, 1), seed + 7), color or PENCIL2, sw, p, a)


def hdash(c, x0, y0, x1, y1, p=1.0, color=None, sw=3, seed=0, a=1.0):
    hline(c, x0, y0, x1, y1, p, color or PENCIL, sw, seed, a, dash=(16, 11))


@functools.lru_cache(512)
def _arrow_paths(x0, y0, x1, y1, curve, seed, head):
    L = math.hypot(x1 - x0, y1 - y0) or 1
    nx, ny = -(y1 - y0) / L, (x1 - x0) / L
    mx, my = (x0 + x1) / 2 + nx * curve * L, (y0 + y1) / 2 + ny * curve * L
    rng = np.random.default_rng(seed)
    shaft = skia.Path()
    shaft.moveTo(x0, y0)
    shaft.quadTo(mx + rng.uniform(-3, 3), my + rng.uniform(-3, 3), x1, y1)
    ang = math.atan2(y1 - my, x1 - mx)
    hp = skia.Path()
    for s in (1, -1):
        a = ang + math.pi + s * math.radians(28 + rng.uniform(-4, 4))
        hp.moveTo(x1 + head * math.cos(a), y1 + head * math.sin(a))
        hp.lineTo(x1, y1)
    return shaft, hp


def harrow(c, x0, y0, x1, y1, p=1.0, color=None, sw=4, seed=0, a=1.0, curve=0.15, head=22):
    """手绘箭头：先画杆，最后两笔画头"""
    shaft, hp = _arrow_paths(round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1), curve, seed, head)
    _stroke(c, shaft, color or INK, sw, clamp(p / 0.8), a)
    _stroke(c, hp, color or INK, sw, clamp((p - 0.8) / 0.2), a)


def hcheck(c, x, y, s, p=1.0, color=None, sw=7, seed=0, a=1.0):
    _stroke(c, _wp(((x - s * 0.5, y), (x - s * 0.12, y + s * 0.4), (x + s * 0.6, y - s * 0.55)), seed, s * 0.03),
            color or ORANGE, sw, e_out(p), a)


def hcross(c, x, y, s, p=1.0, color=None, sw=7, seed=0, a=1.0):
    col_ = color or ORANGE
    _stroke(c, _wp(((x - s / 2, y - s / 2), (x + s / 2, y + s / 2)), seed, s * 0.03), col_, sw, clamp(p * 2), a)
    _stroke(c, _wp(((x + s / 2, y - s / 2), (x - s / 2, y + s / 2)), seed + 1, s * 0.03), col_, sw, clamp(p * 2 - 1), a)


def hatch(c, x, y, w, h, p=1.0, color=None, sw=2.5, gap=11, seed=0, a=1.0):
    """斜排线（暗部、填充）"""
    n = int((w + h) / gap)
    c.save()
    c.clipRect(skia.Rect.MakeXYWH(x, y, w, h))
    for i in range(n):
        q = clamp(p * n - i)
        if q <= 0:
            break
        d = i * gap
        hline(c, x + d, y, x + d - h, y + h, q, color or INK, sw, seed + i, a, amt=1.0)
    c.restore()


def lead(c, x0, y0, x1, y1, p=1.0, color=None, sw=2.5, a=1.0, seed=0):
    """细引线，末端一个实心小圆点"""
    hline(c, x0, y0, x1, y1, p, color or INK, sw, seed, a)
    if p >= 0.98:
        c.drawCircle(x1, y1, sw * 2.4, paint(color or INK, a))


# ======================================================================
# 文字
# ======================================================================

def write(c, s, x, y, size, t, t0, cps=9.0, color=None, kind='hand', align='l', a=1.0, bold=0.0, pen_on=False):
    """一个字一个字写出来（每字约 0.11 秒）。返回写到的位置 (x, y)，写完返回 None。
    bold = 描边加粗（字号的比例，0.03 左右）；pen_on=True 画笔尖跟着写"""
    color = color or INK
    total = text_w(s, size, kind)
    bx = x - total / 2 if align == 'c' else (x if align == 'l' else x - total)
    done = (t - t0) * cps
    if done <= 0:
        return (bx, y + size * 0.2)
    cx, pos = bx, None
    st = (color, size * bold) if bold else None
    for i, ch in enumerate(s):
        cw = text_w(ch, size, kind)
        q = clamp(done - i)
        if q <= 0:
            break
        if q < 1:
            c.save()
            c.clipRect(skia.Rect.MakeLTRB(cx - 3, y - size, cx + cw * q + 1, y + size))
            text(c, ch, cx, y, size, color, kind, 'l', a, st)
            c.restore()
            pos = (cx + cw * q, y + size * 0.22)
        else:
            text(c, ch, cx, y, size, color, kind, 'l', a, st)
        cx += cw
    if pen_on and pos:
        pen(c, pos[0], pos[1], t)
    return pos


def write_d(s, cps=9.0):
    """写完这句要几秒"""
    return len(s) / cps


def tag(c, label, x, y, size, t, t0, color=None, fg=None, a=1.0, seed=0):
    """@标签：墨蓝小方块里的白字，从左往右刷出来（0.25 秒）。返回宽度"""
    tw = text_w(label, size, 'hand')
    pad, h = size * 0.38, size * 1.4
    w = tw + 2 * pad
    if a <= 0:                 # a=0：只量宽度不画
        return w
    p = e_out(prog(t, t0, 0.25))
    if p > 0:
        c.save()
        c.clipRect(skia.Rect.MakeXYWH(x - 6, y - h / 2 - 8, (w + 12) * p, h + 16))
        c.drawPath(_quad(round(x, 1), round(y - h / 2, 1), round(w, 1), round(h, 1), seed, 2.5), paint(color or INK, a))
        text(c, label, x + pad, y, size, fg or SHEET, 'hand', 'l', a)
        c.restore()
    return w


def en(c, s, x, y, size, color=None, a=1.0, align='c'):
    """圆头英文，后面错开一层细描边，像描了两遍"""
    color = color or INK
    off = size * 0.06
    text(c, s, x + off, y + off, size, color, 'en', align, a * 0.9, stroke=(color, max(1.2, size * 0.03)))
    text(c, s, x + off, y + off, size, PAPER, 'en', align, a)
    text(c, s, x, y, size, color, 'en', align, a)


@functools.lru_cache(256)
def _grain_path(x, y, w, h, seed, dens):
    rng = np.random.default_rng(seed)
    n = int(w * h / dens)
    p = skia.Path()
    for _ in range(n):
        p.addCircle(x + rng.uniform(0, w), y + rng.uniform(0, h), rng.uniform(0.5, 1.7))
    return p


@contextmanager
def grain(c, x, y, w, h, seed=0, dens=160):
    """橡皮章颗粒：with 里画的东西被打上随机小孔（dens = 每多少平方像素一个孔，越大越清楚；标题、印章默认 300）"""
    c.saveLayer(skia.Rect.MakeXYWH(x - 4, y - 4, w + 8, h + 8), None)
    try:
        yield
    finally:
        pt = skia.Paint(AntiAlias=True)
        pt.setBlendMode(skia.BlendMode.kDstOut)
        c.drawPath(_grain_path(round(x), round(y), round(w), round(h), seed, dens), pt)
        c.restore()


def title(c, s, x, y, size, t, t0, sub_en=None, color=None, a=1.0, seed=0, dens=300):
    """标题：虚线框（转角出头）+ 框上沿「※ ENGLISH ※」+ 框里颗粒圆粗字。返回框 (x, y, w, h)"""
    color = color or INK
    tw = text_w(s, size, 'round')
    fw, fh = tw + size * 1.2, size * 1.9
    fx, fy = x - fw / 2, y - fh / 2
    p = prog(t, t0, 0.7)
    hbox(c, fx, fy, fw, fh, p, color, sw=3.5, seed=seed, a=a, over=18, dash=(14, 10))
    q = prog(t, t0 + 0.25, 0.4)
    if q > 0:
        sc = lerp(1.18, 1.0, e_out(q))
        with xf(c, x, y, sc, a=a * clamp(q * 2.5)):
            with grain(c, x - tw / 2 - 10, y - size * 0.7, tw + 20, size * 1.4, seed, dens):
                text(c, s, x, y, size, color, 'round', 'c', 1.0, stroke=(color, size * 0.022))
    if sub_en:
        es = size * 0.34
        lab = f'※ {sub_en} ※'
        ew = text_w(lab, es, 'en') + es
        r = prog(t, t0 + 0.4, 0.3)
        if r > 0:
            c.drawRect(skia.Rect.MakeXYWH(x - ew / 2, fy - es * 0.7, ew, es * 1.4), paint(PAPER, a * clamp(r * 3)))
            en(c, lab, x, fy, es, color, a * clamp(r * 3))
    return fx, fy, fw, fh


def stamp(c, s, cx, cy, size, t, t0, color=None, rot=-7, a=1.0, seed=0, dens=300):
    """橡皮章：砸下来（0.22 秒）+ 震一下，双线框，带颗粒"""
    p = prog(t, t0, 0.22)
    if p <= 0:
        return
    color = color or ORANGE
    tw = text_w(s, size, 'round')
    w, h = tw + size * 1.0, size * 1.55
    sc = lerp(1.7, 1.0, e_in(p))
    dx, dy = shake(t, t0 + 0.22, 0.2, 6.0)
    with xf(c, cx, cy, sc, rot, a * clamp(p * 1.8), dx=dx, dy=dy):
        with grain(c, cx - w / 2 - 8, cy - h / 2 - 8, w + 16, h + 16, seed, dens):
            c.drawRRect(rrect(cx - w / 2, cy - h / 2, w, h, size * 0.22), paint(color, 1, stroke=max(4, size * 0.07)))
            c.drawRRect(rrect(cx - w / 2 + size * 0.14, cy - h / 2 + size * 0.14, w - size * 0.28, h - size * 0.28,
                              size * 0.14), paint(color, 1, stroke=max(2, size * 0.03)))
            text(c, s, cx, cy, size, color, 'round', 'c', 1.0, stroke=(color, size * 0.04))


def block_word(c, s, x, y, size, t, t0, color=None, fg=None, align='c', a=1.0, seed=0, kind='hand'):
    """实心色块里的白字（重点词）：弹出来。返回宽度"""
    tw = text_w(s, size, kind)
    pad = size * 0.3
    w, h = tw + 2 * pad, size * 1.35
    bx = x - w / 2 if align == 'c' else (x if align == 'l' else x - w)
    if a <= 0:                 # a=0：只量宽度不画
        return w
    p = prog(t, t0, 0.35)
    if p > 0:
        with xf(c, bx + w / 2, y, lerp(0.6, 1.0, e_back(p)), a=a * clamp(p * 3)):
            c.drawPath(_quad(round(bx, 1), round(y - h / 2, 1), round(w, 1), round(h, 1), seed, 3.0), paint(color or ORANGE))
            text(c, s, bx + pad, y, size, fg or SHEET, kind, 'l', 1.0, stroke=(fg or SHEET, size * 0.025))
    return w


def number(c, s, unit, x, y, size, t, t0, color=None, align='c', a=1.0, seed=0):
    """大数字 + 单位（「10」「亿美元」）：弹出来，数字从 0 数上去。返回总宽；a=0 只量宽度不画"""
    import stylekit as K
    nw = text_w(s, size, 'num')
    us = size * 0.42
    gap = size * 0.1
    uw = text_w(unit, us, 'round') if unit else 0
    w = nw + (gap + uw if unit else 0)
    if a <= 0:
        return w
    q = prog(t, t0, 0.35)
    if q <= 0:
        return w
    bx = x - w / 2 if align == 'c' else (x if align == 'l' else x - w)
    with xf(c, bx + w / 2, y, lerp(0.6, 1.0, e_back(q)), a=a * clamp(q * 3)):
        text(c, K.count(s, prog(t, t0, 0.6)), bx + nw, y, size, color or INK, 'num', 'r')
        if unit:
            text(c, unit, bx + nw + gap, y + size * 0.16, us, color or INK, 'round', 'l')
    return w


def mark(c, s, x, y, size, t, t0, color=None, rot=8, a=1.0):
    """大号标点（？！）：弹出来，略歪"""
    q = prog(t, t0, 0.35)
    if q <= 0:
        return
    with xf(c, x, y, lerp(0.4, 1.0, e_back(q)), rot=rot, a=a * clamp(q * 3)):
        text(c, s, x, y, size, color or ORANGE, 'round', 'c')


def marker(c, x0, x1, y, h, p=1.0, color=None, a=0.95, seed=0):
    """马克笔扫过的淡橙高亮（画在字下面）"""
    if p <= 0:
        return
    xe = lerp(x0, x1, e_io(p))
    rng = np.random.default_rng(seed)
    path = skia.Path()
    path.moveTo(x0 + rng.uniform(-4, 4), y - h / 2 + rng.uniform(-3, 3))
    path.lineTo(xe, y - h / 2 + rng.uniform(-3, 3))
    path.lineTo(xe + rng.uniform(-6, 6), y + h / 2 + rng.uniform(-3, 3))
    path.lineTo(x0 + rng.uniform(-6, 6), y + h / 2 + rng.uniform(-3, 3))
    path.close()
    c.drawPath(path, paint(color or ORANGE_LT, a))


# ======================================================================
# 纸片、照片
# ======================================================================

def tape(c, cx, cy, w=96, h=30, rot=-4, color=None, a=0.88, seed=0):
    """一小段胶带（两头锯齿）"""
    rng = np.random.default_rng(seed)
    path = skia.Path()
    n = 5
    path.moveTo(-w / 2, -h / 2)
    path.lineTo(w / 2, -h / 2)
    for i in range(1, n + 1):
        path.lineTo(w / 2 + (rng.uniform(-4, 1) if i % 2 else rng.uniform(1, 5)), -h / 2 + h * i / n)
    path.lineTo(-w / 2, h / 2)
    for i in range(n - 1, -1, -1):
        path.lineTo(-w / 2 + (rng.uniform(-1, 4) if i % 2 else rng.uniform(-5, -1)), -h / 2 + h * i / n)
    path.close()
    c.save()
    c.translate(cx, cy)
    c.rotate(rot)
    c.drawPath(path, paint(color or ORANGE_LT, a))
    c.drawPath(path, paint(ORANGE, a * 0.25, stroke=1.2))
    c.restore()


def sheet(c, x, y, w, h, t, t0, seed=0, rot=0.0, tape_on=True, layers=1, a=1.0, fill=None, border=None, sw=3.5):
    """一张纸片 / 便签：落下来（0.45 秒），边框一笔笔描出来。layers = 叠几层（像一摞纸）"""
    p = prog(t, t0, 0.45)
    if p <= 0:
        return
    e = e_out(p)
    with xf(c, x + w / 2, y + h / 2, lerp(1.05, 1.0, e), rot + (1 - e) * 3, a * clamp(p * 3), dy=(1 - e) * -30):
        for k in range(layers - 1, 0, -1):
            hbox(c, x + k * 12, y + k * 10, w, h, 1.0, border or INK, sw * 0.8, seed + 10 * k, 1.0, fill or SHEET,
                 over=8, shadow=0.06)
        hbox(c, x, y, w, h, clamp(p * 1.4), border or INK, sw, seed, 1.0, fill or SHEET, over=10, shadow=0.10)
        if tape_on:
            tape(c, x + w / 2, y + 2, rot=-3 + (seed % 5), seed=seed)


def clip_img(S, key, path, src, t, w, h, speed=1.0):
    """视频素材的当前帧（skia.Image），给 photo 用：src = 从原片第几秒开始放"""
    return S.clip(key, path, src, speed, S.t0, size=(int(w), int(h))).get(t)


def photo(c, img, x, y, w, h, t, t0, rot=-2.0, seed=0, caption=None, border=14, focus=(0.5, 0.5), push=0.05,
          a=1.0, tapes=2, cap_size=None):
    """贴在纸上的照片（图片路径、skia.Image 或视频帧）：白边、手绘轮廓、胶带，掉下来落定后在框里慢慢推近。
    caption = 下面白边上的手写说明（来源、人名）"""
    p = prog(t, t0, 0.5)
    if p <= 0 or img is None:
        return
    e = e_out(p)
    bot = border * 3.6 if caption else border
    zoom = 1 + push * e_io(clamp((t - t0) / 7.0))
    with xf(c, x + w / 2, y + h / 2, lerp(1.08, 1.0, e), rot + (1 - e) * 5, a * clamp(p * 2.5), dy=(1 - e) * 50):
        c.drawRect(skia.Rect.MakeXYWH(x + 8, y + 14, w, h), paint(BLACK, 0.16, blur=16))
        c.drawRect(skia.Rect.MakeXYWH(x, y, w, h), paint(SHEET))
        lib.img_cover(c, img, x + border, y + border, w - 2 * border, h - border - bot, zoom=zoom, focus=focus)
        hbox(c, x - 3, y - 3, w + 6, h + 6, 1.0, INK, 3, seed, 0.85, over=7)
        if caption:
            cs = cap_size or min(bot * 0.62, 34)
            text(c, caption, x + w / 2, y + h - bot / 2, cs, INK, 'hand', 'c')
        if tapes >= 1:
            tape(c, x + 26, y + 6, 86, 28, -38, seed=seed + 1)
        if tapes >= 2:
            tape(c, x + w - 26, y + 6, 86, 28, 36, seed=seed + 2)


# ======================================================================
# 笔尖（次要动作）
# ======================================================================

def pen(c, x, y, t, color=None, marker_tip=False):
    """笔尖落在 (x, y)，笔杆朝右上。marker_tip=True 是橙色马克笔"""
    color = color or (ORANGE if marker_tip else INK)
    bob = 2.0 * math.sin(t * 23.0)
    c.save()
    c.translate(x, y + bob)
    c.rotate(-52)
    c.drawRRect(rrect(14, -8, 230, 24, 10), paint(BLACK, 0.16, blur=9))
    c.drawRRect(rrect(26, -11, 210, 22, 9), paint(color))
    c.drawRect(skia.Rect.MakeXYWH(120, -11, 10, 22), paint(SHEET, 0.85))
    tip = skia.Path()
    tip.moveTo(0, 0)
    tip.lineTo(28, -10)
    tip.lineTo(28, 10)
    tip.close()
    c.drawPath(tip, paint(PENCIL3 if not marker_tip else ORANGE_DK))
    c.drawLine(4, 0, 22, 0, paint(INK, 1, stroke=1.5))
    c.restore()


# ======================================================================
# 字幕、人物小窗
# ======================================================================

def sub(c, s, x, y, size, maxw):
    """字幕：一条白纸条（四角略歪）上的墨蓝手写字"""
    size = size * 1.06
    w = text_w(s, size, 'sub')
    if w > maxw:
        size = size * maxw / w
        w = maxw
    pad, h = size * 0.55, size * 1.5
    seed = 3
    path = _quad(round(x - w / 2 - pad, 1), round(y - h / 2, 1), round(w + 2 * pad, 1), round(h, 1), seed, 2.0)
    c.save()
    c.translate(0, 5)
    c.drawPath(path, paint(BLACK, 0.18, blur=10))
    c.restore()
    c.drawPath(path, paint(SHEET, 0.97))
    c.drawPath(path, paint(PENCIL3, 1, stroke=1.4))
    text(c, s, x, y, size, INK, 'sub', 'c', 1.0, stroke=(INK, size * 0.03))


def pip_frame(c, x, y, w, h, r, a):
    """人物小窗：白边 + 手绘墨蓝轮廓 + 顶上一段胶带"""
    if a <= 0.01:
        return
    c.drawRRect(rrect(x + 4, y + 4, w - 8, h - 8, max(0, r - 4)), paint(SHEET, a, stroke=8))
    hbox(c, x - 5, y - 5, w + 10, h + 10, 1.0, INK, 3.5, 77, a, over=9)
    tape(c, x + w / 2, y - 4, 110, 32, -3, a=0.9 * a, seed=78)


# ======================================================================
# 转场
# ======================================================================

def _bp(sx=0.0, sy=0.0, a=1.0):
    p = skia.Paint(AntiAlias=True)
    if sx > 0.3 or sy > 0.3:
        p.setImageFilter(skia.ImageFilters.Blur(sx, sy))
    p.setAlphaf(clamp(a))
    return p


def _di(c, img, x, y, p=None):
    c.drawImageRect(img, skia.Rect.MakeXYWH(x, y, W, H), lib.SAMP, p)


def _tr_scroll(c, A, B, x, fidx):
    """往下读：整张纸往上滑，下一段从下面接上来"""
    e = e_io(x)
    k = math.sin(math.pi * x)
    c.clear(col(PAPER))
    _di(c, A, 0, -e * H, _bp(0, 22 * k))
    _di(c, B, 0, (1 - e) * H, _bp(0, 22 * k))


def _clip_poly(poly, n, s):
    """多边形和半平面 dot(P, n) >= s 求交（Sutherland–Hodgman）"""
    out = []
    for i in range(len(poly)):
        P, Q = poly[i], poly[(i + 1) % len(poly)]
        dp, dq = P[0] * n[0] + P[1] * n[1] - s, Q[0] * n[0] + Q[1] * n[1] - s
        if dp >= 0:
            out.append(P)
        if (dp >= 0) != (dq >= 0):
            k = dp / (dp - dq)
            out.append((P[0] + (Q[0] - P[0]) * k, P[1] + (Q[1] - P[1]) * k))
    return out


def _path(poly):
    p = skia.Path()
    if poly:
        p.moveTo(*poly[0])
        for q in poly[1:]:
            p.lineTo(*q)
        p.close()
    return p


def _tr_page(c, A, B, x, fidx):
    """翻页：右下角掀起来翻向左上，露出下一页；翻起的纸背是白纸，带折痕阴影"""
    e = e_io(x)
    d = np.array([-1.0, -0.42])
    d /= np.linalg.norm(d)
    corner = np.array([W, H], float)
    span = abs(np.dot(np.array([0, 0]) - corner, d)) + 260
    s = e * span                                              # 折线：dot(P - corner, d) = s
    rect = [(0, 0), (W, 0), (W, H), (0, H)]
    rel = [(px - W, py - H) for px, py in rect]
    keep = _clip_poly(rel, d, s)                              # A 留下的部分
    gone = _clip_poly(rel, -d, -s)                            # 翻起来的部分
    flap = [(px + 2 * (s - (px * d[0] + py * d[1])) * d[0], py + 2 * (s - (px * d[0] + py * d[1])) * d[1]) for px, py in gone]
    tr = lambda poly: [(px + W, py + H) for px, py in poly]
    c.clear(col(PAPER))
    _di(c, B, 0, 0)
    c.save()
    c.clipPath(_path(tr(keep)), skia.ClipOp.kIntersect, True)
    _di(c, A, 0, 0)
    c.restore()
    if flap and len(flap) >= 3:
        fp = _path(tr(flap))
        c.save()
        c.clipRect(skia.Rect.MakeWH(W, H))
        c.save()
        c.translate(-d[0] * 14, -d[1] * 14)
        c.drawPath(fp, paint(BLACK, 0.22, blur=18))
        c.restore()
        # 纸背：折痕处暗、往外渐亮
        fold_pt = corner + d * s
        g0 = skia.Point(float(fold_pt[0]), float(fold_pt[1]))
        g1 = skia.Point(float(fold_pt[0] + d[0] * 380), float(fold_pt[1] + d[1] * 380))
        sh = skia.GradientShader.MakeLinear([g0, g1], [col((205, 203, 192)), col(SHEET), col((236, 235, 226))],
                                            [0, 0.45, 1], skia.TileMode.kClamp)
        pt = skia.Paint(AntiAlias=True)
        pt.setShader(sh)
        c.drawPath(fp, pt)
        c.drawPath(fp, paint(PENCIL, 0.8, stroke=1.5))
        c.restore()


@functools.lru_cache(4)
def _zigzag(rows):
    p = skia.Path()
    bw = H / rows
    for r in range(rows):
        y = bw * (r + 0.5)
        x0, x1 = (-160, W + 160) if r % 2 == 0 else (W + 160, -160)
        if r == 0:
            p.moveTo(x0, y)
        else:
            p.lineTo(x0, y)
        p.lineTo(x1, y + bw * 0.25)
    return p


def _tr_erase(c, A, B, x, fidx):
    """橡皮擦：一块白橡皮（橙纸套）来回擦，擦过的地方露出下一页，后面掉橡皮屑"""
    rows = 7 if lib.VERTICAL else 5
    zz = _zigzag(rows)
    q = e_io(clamp(x * 1.05))
    bw = H / rows * 1.45
    c.clear(col(PAPER))
    _di(c, B, 0, 0)
    c.saveLayer(None, None)
    _di(c, A, 0, 0)
    er = paint(BLACK, 1, stroke=bw)
    er.setBlendMode(skia.BlendMode.kDstOut)
    er.setMaskFilter(skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 6))
    c.drawPath(partial_path(zz, q), er)
    c.restore()
    pm = skia.PathMeasure(zz, False)
    L = pm.getLength()
    if q >= 0.999:
        return
    pos, tan = pm.getPosTan(L * q)                            # skia-python 返回 (位置, 切线)
    rng = np.random.default_rng(int(q * 400))
    for _ in range(14):                                       # 橡皮屑
        p2, _t = pm.getPosTan(max(0.0, L * q - rng.uniform(20, 380)))
        c.drawCircle(p2.x() + rng.uniform(-bw / 2, bw / 2), p2.y() + rng.uniform(-bw / 2, bw / 2),
                     rng.uniform(2, 5), paint(PENCIL, rng.uniform(0.5, 0.9)))
    ang = math.degrees(math.atan2(tan.y(), tan.x()))
    c.save()
    c.translate(pos.x(), pos.y())
    c.rotate(ang * 0.15 - 12)
    c.drawRRect(rrect(-92, -48 + 10, 184, 96, 18), paint(BLACK, 0.2, blur=14))
    c.drawRRect(rrect(-92, -48, 184, 96, 18), paint(SHEET))
    c.drawRRect(rrect(-92, -48, 184, 96, 18), paint(PENCIL, 1, stroke=2))
    c.drawRect(skia.Rect.MakeXYWH(-10, -50, 104, 100), paint(ORANGE))
    c.drawLine(-10, -50, -10, 50, paint(ORANGE_DK, 1, stroke=2))
    c.restore()


TRANSITIONS = {'scroll': _tr_scroll, 'page': _tr_page, 'erase': _tr_erase}
