"""扁平流程图：奶油底、琥珀黄、特粗近黑字的扁平科普信息图。东西都是平的，体积只靠一层不模糊的错位投影；
彩色块带一点厚度；背景是慢慢转的浅灰钟面和飘着的扁平小几何。
风格卡.md 是给人看的说明；这个文件是给 scenes.py 用的部件，名字和参数跟其他风格一样（见 styles/部件.md）。
"""
import math, functools
import numpy as np
import skia
import lib
from lib import *  # noqa: F401,F403
from lib import clamp, prog, e_out, e_in, e_io, e_back, lerp, paint, col, text, text_w, xf, rrect, mix
import stylekit as K
from stylekit import cam, shake, clip_img  # noqa: F401

# ---------- 配色 ----------
CREAM = (252, 249, 236)       # 奶油底
PAPERW = (255, 253, 246)      # 卡片白
AMBER = (251, 191, 47)        # 琥珀黄：页眉带、标题块、说明框、高亮
AMBER_DK = (247, 163, 14)     # 深琥珀：箭头头、描边
AMBER_DD = (224, 138, 6)
AMBER_LT = (253, 231, 160)
INK = (26, 20, 16)            # 近黑：字
LINEK = (43, 36, 27)          # 细折线
WARM = (125, 115, 99)         # 暖灰：说明
WARM2 = (95, 87, 74)
HINT = (185, 176, 156)
RING = (239, 232, 214)        # 钟面灰
SHADOW = (239, 227, 194)      # 错位投影
CAPS = (245, 238, 219)
RED, BLUE, ORANGE, GREEN, GOLD = (212, 25, 40), (35, 115, 206), (238, 128, 19), (79, 157, 52), (217, 142, 4)
ACCENT, ACCENT2, MUTE = RED, BLUE, WARM
lib.use_palette(INK=INK, SUBINK=WARM2, MUTE=WARM, LINE=RING, BG=CREAM, ACC=RED, ACC2=BLUE)

# ---------- 字体：思源黑体（正文 600、特粗 900）+ Montserrat（数字、英文） ----------
lib.use_kinds(hand=('noto_sans_sc', 700, 0.36), round=('noto_sans_sc', 900, 0.36), sub=('noto_sans_sc', 800, 0.36),
              num=('montserrat', 900, 0.35), en=('montserrat', 800, 0.35),
              cn=('noto_sans_sc', 700, 0.36), cn_med=('noto_sans_sc', 500, 0.36), cn_reg=('noto_sans_sc', 400, 0.36),
              cn_black=('noto_sans_sc', 900, 0.36))

# ---------- 转场、音效 ----------
lib.DEFAULT_TR = 'slide'
ALT_TR = 'circle'               # 换话题时用的第二种转场：scenes.py 里写 tr=T.ALT_TR
lib.TR_D.update(slide=0.55, circle=0.6)
SFX = {'write': ('blip', -2), 'drop': ('desk_tap', 0), 'pop': ('bubble', 0), 'mark': ('swish', -4),
       'stamp': ('bell', -6), 'stick': None, 'tick': ('bubble', -2, {'v': 2}), 'number': ('wood_knock', 0),
       'whoosh': ('whip', -6)}
TR_SFX = {'slide': [(-0.28, 'whoosh', -4, {'d': 0.5, 'f0': 300.0, 'f1': 3000.0})],
          'circle': [(-0.25, 'swish', -6), (-0.02, 'bubble', -2)]}


def _flat_shadow(c, rr, dx=10, dy=12, color=None, a=1.0):
    c.save(); c.translate(dx, dy)
    c.drawRRect(rr, paint(color or SHADOW, a))
    c.restore()


# ======================================================================
# 背景：奶油底 + 慢慢转的钟面 + 飘着的扁平小几何 + 页眉琥珀带
# ======================================================================

def _clock(c, cx, cy, r, t, a=1.0):
    c.drawCircle(cx, cy, r, paint(RING, a, stroke=5))
    for k in range(12):
        ang = math.radians(k * 30)
        x0, y0 = cx + math.cos(ang) * r * 0.86, cy + math.sin(ang) * r * 0.86
        x1, y1 = cx + math.cos(ang) * r * 0.94, cy + math.sin(ang) * r * 0.94
        p = paint(RING, a, stroke=7 if k % 3 == 0 else 4)
        p.setStrokeCap(skia.Paint.kRound_Cap)
        c.drawLine(x0, y0, x1, y1, p)
    for ln, sp, wd in ((0.55, 6.0, 7), (0.75, 36.0, 4)):          # 分针、秒针一直在转
        ang = math.radians(t * sp - 90)
        p = paint(RING, a, stroke=wd)
        p.setStrokeCap(skia.Paint.kRound_Cap)
        c.drawLine(cx, cy, cx + math.cos(ang) * r * ln, cy + math.sin(ang) * r * ln, p)
    c.drawCircle(cx, cy, 9, paint(RING, a))


_SHAPES = [(0.62, 0.16, 'circle', (253, 222, 150), 18), (0.93, 0.30, 'tri', (205, 225, 246), 26),
           (0.55, 0.86, 'square', (214, 236, 204), 20), (0.86, 0.78, 'plus', (250, 210, 205), 22),
           (0.40, 0.10, 'ring', (253, 222, 150), 20), (0.97, 0.56, 'circle', (205, 225, 246), 14),
           (0.30, 0.90, 'tri', (253, 222, 150), 20), (0.72, 0.52, 'plus', (214, 236, 204), 16)]


def _shape(c, kind, x, y, s, color, rot, a):
    with xf(c, x, y, rot=rot, a=a):
        if kind == 'circle':
            c.drawCircle(x, y, s / 2, paint(color))
        elif kind == 'ring':
            c.drawCircle(x, y, s / 2, paint(color, stroke=5))
        elif kind == 'square':
            c.drawRRect(rrect(x - s / 2, y - s / 2, s, s, 4), paint(color))
        elif kind == 'tri':
            path = skia.Path()
            path.moveTo(x, y - s * 0.55); path.lineTo(x + s * 0.55, y + s * 0.4); path.lineTo(x - s * 0.55, y + s * 0.4)
            path.close()
            c.drawPath(path, paint(color))
        else:
            for dx, dy in ((1, 0), (0, 1)):
                p = paint(color, stroke=6)
                p.setStrokeCap(skia.Paint.kRound_Cap)
                c.drawLine(x - dx * s / 2, y - dy * s / 2, x + dx * s / 2, y + dy * s / 2, p)


def _left():
    import layout as L
    return 60 if lib.VERTICAL else L.PIP_SAFE[2] + 40


def paper(c, t, head=None, deco=True):
    """铺底。head = 页眉琥珀带里的字（这一段讲什么，可以不给）；deco=False 不要钟面和小几何"""
    c.clear(col(CREAM))
    if deco:
        if lib.VERTICAL:
            _clock(c, W * 0.86, H * 0.74, 300, t)
            _clock(c, W * 0.1, H * 0.12, 180, t * 0.7)
        else:
            _clock(c, W * 0.84, H * 0.7, 340, t)
            _clock(c, W * 0.16, H * 0.98, 200, t * 0.7)
        for k, (fx, fy, kind, clr, s) in enumerate(_SHAPES):
            x = fx * W + 18 * math.sin(t * 0.5 + k)
            y = fy * H + 14 * math.cos(t * 0.4 + k * 1.7)
            _shape(c, kind, x, y, s, clr, t * 12 * (1 if k % 2 else -1) + k * 30, 0.95)
    if head:
        x0 = 0 if lib.VERTICAL else _left() - 34
        hh = 104 if lib.VERTICAL else 92
        c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeLTRB(x0, -30, W + 30, hh), 26, 26), paint(AMBER))
        c.drawRect(skia.Rect.MakeLTRB(x0, hh, W, hh + 5), paint(SHADOW))
        text(c, head, (60 if lib.VERTICAL else _left()) + 4, hh / 2 + 2, 44, INK, 'round', 'l')


# ======================================================================
# 字
# ======================================================================

def title(c, s, x, y, size, t, t0, sub_en=None, color=None, a=1.0, seed=0):
    """大标题：琥珀色块里的特粗黑字，带错位投影；块弹出来，字一个个蹦出来"""
    tw = text_w(s, size, 'round')
    pw, ph = tw + size * 0.9, size * 1.55
    q = prog(t, t0, 0.4)
    if q <= 0:
        return
    with xf(c, x, y, lerp(0.6, 1.0, e_back(q)), a=a * clamp(q * 3)):
        rr = rrect(x - pw / 2, y - ph / 2, pw, ph, size * 0.24)
        _flat_shadow(c, rr, size * 0.08, size * 0.1)
        c.drawRRect(rr, paint(color or AMBER))
        c.drawRRect(rrect(x - pw / 2, y - ph / 2, pw, ph * 0.18, size * 0.24), paint(WHITE, 0.18))
    K.chars(c, s, x, y, size, t, t0 + 0.15, 14, INK, 'round', 'c', a, mode='pop')
    if sub_en:
        qe = prog(t, t0 + 0.25, 0.3)
        text(c, sub_en, x, y - ph / 2 - size * 0.32, size * 0.2, WARM, 'en', 'c', a * qe, track=0.18)


def tag(c, label, x, y, size, t, t0, color=None, fg=None, a=1.0, seed=0):
    """标签：琥珀小胶囊里的近黑字，从左边滑进来。返回宽度"""
    tw = text_w(label, size, 'round')
    h = size * 1.5
    w = tw + h * 0.8
    if a <= 0:                 # a=0：只量宽度不画
        return w
    q = prog(t, t0, 0.3)
    if q > 0:
        e = e_out(q)
        with xf(c, x, y, a=a * clamp(q * 2.5), dx=(1 - e) * -30):
            rr = rrect(x, y - h / 2, w, h, h / 2)
            _flat_shadow(c, rr, 5, 6)
            c.drawRRect(rr, paint(color or AMBER))
            text(c, label, x + w / 2, y, size, fg or INK, 'round', 'c')
    return w


def write(c, s, x, y, size, t, t0, cps=9.0, color=None, kind='hand', align='l', a=1.0, pen_on=False, **_):
    """一个字一个字浮上来（淡入 + 上浮）。返回出到的位置 (x, y)"""
    _, end = K.chars(c, s, x, y, size, t, t0, cps * 1.2, color or INK, kind, align, a, mode='fade', slots=2.0)
    return (end, y)


def write_d(s, cps=9.0):
    return len(s) / (cps * 1.2) + 2.0 / (cps * 1.2)


def _chip(c, x, y, w, h, color, r=None, depth=None):
    """带厚度的彩色圆角块：下面一条深色边 + 上沿一道高光 + 错位投影"""
    r = r if r is not None else h * 0.24
    d = depth if depth is not None else h * 0.12
    _flat_shadow(c, rrect(x, y, w, h + d, r), 7, 9)
    c.drawRRect(rrect(x, y + d, w, h, r), paint(mix(color, (0, 0, 0), 0.28)))
    c.drawRRect(rrect(x, y, w, h, r), paint(color))
    c.drawRRect(rrect(x + 4, y + 4, w - 8, h * 0.32, r * 0.7), paint(WHITE, 0.16))


def block_word(c, s, x, y, size, t, t0, color=None, fg=None, align='c', a=1.0, seed=0, **_):
    """重点词：带厚度的彩色块里的白字（默认强调色 A 红；第二个重点用 color=T.ACCENT2 蓝），弹出来。返回宽度"""
    tw = text_w(s, size, 'round')
    w, h = tw + size * 0.7, size * 1.4
    bx = x - w / 2 if align == 'c' else (x if align == 'l' else x - w)
    if a <= 0:                 # a=0：只量宽度不画
        return w
    q = prog(t, t0, 0.35)
    if q > 0:
        with xf(c, bx + w / 2, y, lerp(0.5, 1.0, e_back(q)), a=a * clamp(q * 3)):
            _chip(c, bx, y - h / 2, w, h, color or ACCENT)
            text(c, s, bx + w / 2, y, size, fg or WHITE, 'round', 'c')
    return w


def number(c, s, unit, x, y, size, t, t0, color=None, align='c', a=1.0, seed=0):
    """大数字 + 单位：特粗数字带琥珀错位投影，从 0 数上去。返回总宽；a=0 只量宽度"""
    nw = text_w(s, size, 'num')
    us = size * 0.4
    gap = size * 0.1
    uw = text_w(unit, us, 'round') if unit else 0
    w = nw + (gap + uw if unit else 0)
    if a <= 0:
        return w
    q = prog(t, t0, 0.35)
    if q <= 0:
        return w
    bx = x - w / 2 if align == 'c' else (x if align == 'l' else x - w)
    s_ = K.count(s, prog(t, t0, 0.7))
    with xf(c, bx + w / 2, y, lerp(0.6, 1.0, e_back(q)), a=a * clamp(q * 3)):
        text(c, s_, bx + nw + size * 0.045, y + size * 0.05, size, AMBER, 'num', 'r')
        text(c, s_, bx + nw, y, size, color or INK, 'num', 'r')
        if unit:
            text(c, unit, bx + nw + gap + us * 0.05, y + size * 0.2 + us * 0.05, us, AMBER, 'round', 'l')
            text(c, unit, bx + nw + gap, y + size * 0.2, us, color or INK, 'round', 'l')
    return w


def mark(c, s, x, y, size, t, t0, color=None, rot=8, a=1.0):
    """大号标点：琥珀色特粗，带深色错位投影，弹出来后轻轻晃"""
    q = prog(t, t0, 0.35)
    if q <= 0:
        return
    wob = 4 * math.sin((t - t0) * 3.0) * clamp((t - t0 - 0.35) * 2)
    with xf(c, x, y, lerp(0.4, 1.0, e_back(q)), rot=rot + wob, a=a * clamp(q * 3)):
        text(c, s, x + size * 0.05, y + size * 0.06, size, AMBER_DD, 'round', 'c')
        text(c, s, x, y, size, color or AMBER, 'round', 'c')


def stamp(c, s, cx, cy, size, t, t0, color=None, rot=-7, a=1.0, seed=0):
    """结论：琥珀结果块 + 角上一个对勾圆标，弹出来时撒一把彩色小纸屑"""
    tw = text_w(s, size, 'round')
    w, h = tw + size * 0.9, size * 1.6
    q = prog(t, t0, 0.4)
    if q <= 0:
        return
    rot = rot * 0.3
    with xf(c, cx, cy, lerp(0.5, 1.0, e_back(q)), rot=rot, a=a * clamp(q * 3)):
        rr = rrect(cx - w / 2, cy - h / 2, w, h, size * 0.26)
        _flat_shadow(c, rr, 9, 11)
        c.drawRRect(rr, paint(color or AMBER))
        text(c, s, cx, cy, size, INK, 'round', 'c')
        bx, by, br = cx + w / 2 - size * 0.1, cy - h / 2 + size * 0.1, size * 0.36
        c.drawCircle(bx, by, br + 5, paint(CREAM))
        lib.check(c, bx, by, br, clamp((t - t0 - 0.2) / 0.35), INK)
    _confetti(c, cx, cy, w, t, t0, seed)


def _confetti(c, cx, cy, w, t, t0, seed):
    d = t - t0
    if d <= 0.05 or d > 1.0:
        return
    rng = np.random.default_rng(seed + 40)
    colors = [RED, BLUE, GREEN, ORANGE, AMBER]
    for k in range(16):
        ang = rng.uniform(0, 2 * math.pi)
        sp = rng.uniform(260, 520)
        x = cx + math.cos(ang) * (w * 0.35 + sp * e_out(clamp(d / 0.8)) * 0.6)
        y = cy + math.sin(ang) * sp * e_out(clamp(d / 0.8)) * 0.5 + 120 * d * d
        s = rng.uniform(8, 16)
        _shape(c, ['circle', 'square', 'tri'][k % 3], x, y, s, colors[k % 5], d * 300 + k * 40, clamp((1.0 - d) * 3))


# ======================================================================
# 线和标记
# ======================================================================

def hunder(c, x0, x1, y, p=1.0, color=None, seed=0, a=1.0, **_):
    """下划线：一条圆头的琥珀粗条，从左往右画"""
    if p <= 0:
        return
    xe = lerp(x0, x1, e_out(p))
    c.drawRRect(rrect(x0, y - 5, max(10, xe - x0), 10, 5), paint(color or AMBER, a))


def hcircle(c, cx, cy, rx, ry=None, p=1.0, color=None, seed=0, a=1.0, **_):
    """圈出来：琥珀粗线圆圈，一笔转一圈"""
    K.stroke_path(c, K.ellipse_path(cx, cy, rx, ry or rx, -100, 360), e_io(p), color or AMBER_DK, 8, a)


def harrow(c, x0, y0, x1, y1, p=1.0, color=None, seed=0, a=1.0, curve=0.15, **_):
    """弧形箭头：尾巴透明、头部深琥珀，从尾画到头"""
    if p <= 0:
        return
    path = K.curve_path(x0, y0, x1, y1, curve)
    pp = lib.partial_path(path, e_io(p)) if p < 1 else path
    pt = K.lin(x0, y0, x1, y1, [AMBER + (0.0,), AMBER + (0.9,), color or AMBER_DK], [0, 0.4, 1], a)
    pt.setStyle(skia.Paint.kStroke_Style)
    pt.setStrokeWidth(10)
    pt.setStrokeCap(skia.Paint.kRound_Cap)
    c.drawPath(pp, pt)
    if p > 0.8:
        K.arrow_head(c, x1, y1, K.head_angle(x0, y0, x1, y1, curve), 30, color or AMBER_DK, a * clamp((p - 0.8) * 5))


def hcheck(c, x, y, s, p=1.0, color=None, seed=0, a=1.0, **_):
    """勾：绿色圆标里的白勾，弹出来"""
    if p <= 0:
        return
    lib.check(c, x, y, s * 0.58, p, color or GREEN, a)


def hcross(c, x, y, s, p=1.0, color=None, seed=0, a=1.0, **_):
    if p <= 0:
        return
    lib.cross(c, x, y, s * 0.58, p, color or RED, a)


def marker(c, x0, x1, y, h, p=1.0, color=None, a=0.85, seed=0):
    """高亮：琥珀色圆角底，从左往右铺（画在字下面）"""
    if p <= 0:
        return
    xe = lerp(x0, x1, e_out(p))
    c.drawRRect(rrect(x0, y - h / 2, max(h * 0.3, xe - x0), h, 10), paint(color or AMBER_LT, a))


def squiggle(c, x, y, w, p=1.0, color=None, seed=0, a=1.0, **_):
    """占位的字：几段圆头灰条（像还没写字的说明）"""
    rng = np.random.default_rng(seed + 3)
    xs, cx = [], x
    while cx < x + w - 30:
        L_ = min(rng.uniform(60, 190), x + w - cx)
        xs.append((cx, L_))
        cx += L_ + rng.uniform(14, 24)
    xe = x + w * e_out(clamp(p))
    for sx, L_ in xs:
        if sx >= xe:
            break
        c.drawRRect(rrect(sx, y - 7, min(L_, xe - sx), 14, 7), paint(color or RING, a))


def hline(c, x0, y0, x1, y1, p=1.0, color=None, seed=0, a=1.0, **_):
    """细黑折线，两头小圆点（说明框连到东西上）"""
    if p <= 0:
        return
    xe, ye = lerp(x0, x1, e_out(p)), lerp(y0, y1, e_out(p))
    pt = paint(color or LINEK, a, stroke=2.5)
    pt.setStrokeCap(skia.Paint.kRound_Cap)
    c.drawLine(x0, y0, xe, ye, pt)
    c.drawCircle(x0, y0, 5, paint(color or LINEK, a))
    if p >= 1:
        c.drawCircle(x1, y1, 5, paint(color or LINEK, a))


# ======================================================================
# 卡片、照片
# ======================================================================

def sheet(c, x, y, w, h, t, t0, seed=0, rot=0.0, layers=1, a=1.0, fill=None, **_):
    """卡片：白色圆角卡 + 琥珀色窗口标题条（三个小点）+ 错位投影，浮上来。layers = 后面再叠几张"""
    q = prog(t, t0, 0.4)
    if q <= 0:
        return
    e = e_out(q)
    with xf(c, x + w / 2, y + h / 2, lerp(0.94, 1.0, e), a=a * clamp(q * 2.5), dy=(1 - e) * 30):
        for k in range(layers - 1, 0, -1):
            c.drawRRect(rrect(x + 16 * k, y + 14 * k, w, h, 26), paint(CAPS))
        rr = rrect(x, y, w, h, 26)
        _flat_shadow(c, rr, 12, 14)
        c.drawRRect(rr, paint(fill or PAPERW))
        c.drawRRect(rr, paint((234, 224, 196), 1, stroke=2))
        c.save(); c.clipRRect(rr, True)
        c.drawRect(skia.Rect.MakeXYWH(x, y, w, 22), paint(AMBER))
        c.restore()
        for k in range(3):
            c.drawCircle(x + w - 30 - k * 20, y + 11, 4, paint(INK, 0.55))


def photo(c, img, x, y, w, h, t, t0, rot=0.0, seed=0, caption=None, focus=(0.5, 0.5), push=0.05, a=1.0, **_):
    """照片：白色圆角卡里的图，下面一条说明（来源、人名），浮上来，落定后图在框里慢推"""
    q = prog(t, t0, 0.45)
    if q <= 0 or img is None:
        return
    e = e_out(q)
    pad = 14
    bot = 58 if caption else pad
    with xf(c, x + w / 2, y + h / 2, lerp(0.92, 1.0, e), a=a * clamp(q * 2.5), dy=(1 - e) * 40):
        rr = rrect(x, y, w, h, 24)
        _flat_shadow(c, rr, 12, 14)
        c.drawRRect(rr, paint(PAPERW))
        K.cover(c, img, x + pad, y + pad, w - 2 * pad, h - pad - bot, t, t0, focus, push, r=16)
        if caption:
            c.drawCircle(x + pad + 14, y + h - bot / 2, 7, paint(AMBER))
            text(c, caption, x + pad + 32, y + h - bot / 2, 26, WARM2, 'hand', 'l')


# ======================================================================
# 字幕、人物小窗
# ======================================================================

def sub(c, s, x, y, size, maxw):
    """字幕：卡片白圆角条上的特粗近黑字，下面一层琥珀错位投影"""
    w = text_w(s, size, 'sub')
    if w > maxw:
        size = size * maxw / w
        w = maxw
    pad, h = size * 0.6, size * 1.55
    rr = rrect(x - w / 2 - pad, y - h / 2, w + 2 * pad, h, h * 0.3)
    _flat_shadow(c, rr, 6, 7, AMBER)
    c.drawRRect(rr, paint(PAPERW, 0.97))
    text(c, s, x, y, size, INK, 'sub', 'c')


def pip_frame(c, x, y, w, h, r, a):
    """人物小窗：白边 + 近黑细框"""
    if a <= 0.01:
        return
    c.drawRRect(rrect(x + 4, y + 4, w - 8, h - 8, max(0, r - 4)), paint(PAPERW, a, stroke=9))
    c.drawRRect(rrect(x - 1, y - 1, w + 2, h + 2, r + 1), paint(INK, a * 0.85, stroke=3))


# ======================================================================
# 转场
# ======================================================================

def _tr_slide(c, A, B, x, fidx):
    """镜头往右移到下一站：整页往左滑走，下一页从右边接上来"""
    e = e_io(x)
    k = math.sin(math.pi * x)
    c.clear(col(CREAM))
    K.di(c, A, -e * W, 0, K.bp(16 * k, 0))
    K.di(c, B, (1 - e) * W, 0, K.bp(16 * k, 0))


def _tr_circle(c, A, B, x, fidx):
    """圆形展开：下一页从画面中间一个圆里撑开，圆边一圈琥珀"""
    e = e_io(x)
    K.di(c, A, p=None, s=1 - 0.06 * e)
    cx = CX if lib.VERTICAL else (_left() + W) / 2
    r = math.hypot(W, H) * e
    path = skia.Path()
    path.addCircle(cx, CY, max(r, 1))
    c.save(); c.clipPath(path, skia.ClipOp.kIntersect, True)
    K.di(c, B)
    c.restore()
    if 0 < e < 1:
        c.drawCircle(cx, CY, r, paint(AMBER, 1, stroke=26 * (1 - e) + 6))


TRANSITIONS = {'slide': _tr_slide, 'circle': _tr_circle}
