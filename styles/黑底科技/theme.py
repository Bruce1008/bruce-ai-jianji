"""黑底科技：近黑的底、一团暖色的光、飘着的金色星尘；字是宋体，标题和数字是由虚到实浮出来的金色渐变字；
线都是细细的金线，画的时候笔尖带一颗亮点；卡片是深色玻璃 + 四角金色括号；结论是一枚红色印章砸下来。
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
BG0, BG1 = (11, 15, 21), (5, 7, 11)          # 底：上浅下深的近黑
WARMG = (62, 50, 32)                         # 暖光
GOLD = (229, 207, 149)                       # 金：线、括号、小字
GOLD_HI = (250, 239, 204)
GOLD_G = [(250, 239, 204), (221, 201, 148), (174, 145, 92), (140, 99, 48)]    # 金字渐变（上亮下暗）
COIN_G = [(247, 233, 188), (229, 202, 137), (205, 172, 106), (178, 142, 79)]  # 金币块渐变
LINE1, LINE2, LINE3 = (193, 190, 168), (161, 156, 133), (116, 111, 97)
TXT = (226, 223, 211)                        # 正文、字幕
GLASS, GLASS_B = (26, 23, 19), (55, 51, 52)  # 玻璃卡片、卡片边
SEAL, SEAL_IN, SEAL_TXT = (177, 49, 42), (252, 208, 192), (254, 229, 213)     # 印章红
NO_RED = (214, 96, 82)
INK = TXT
ACCENT, ACCENT2, MUTE = SEAL, GOLD, LINE2
lib.use_palette(INK=TXT, SUBINK=LINE1, MUTE=LINE2, LINE=GLASS_B, BG=BG0, ACC=GOLD, ACC2=SEAL)

# ---------- 字体：思源宋体（正文 600、标题 900）+ Playfair Display（数字、英文） ----------
lib.use_kinds(hand=('noto_serif_sc', 600, 0.36), round=('noto_serif_sc', 900, 0.36), sub=('noto_serif_sc', 700, 0.36),
              num=('noto_serif_sc', 900, 0.36), en=('playfair', 600, 0.35),
              cn=('noto_serif_sc', 600, 0.36), cn_med=('noto_serif_sc', 500, 0.36), cn_reg=('noto_serif_sc', 400, 0.36),
              cn_black=('noto_serif_sc', 900, 0.36))

# ---------- 转场、音效 ----------
lib.DEFAULT_TR = 'dissolve'
ALT_TR = 'glow'               # 换话题时用的第二种转场：scenes.py 里写 tr=T.ALT_TR
lib.TR_D.update(dissolve=0.6, glow=0.6)
SFX = {'write': ('low_swish', -10), 'drop': ('deep_whoosh', -6), 'pop': ('sparkle', 0), 'mark': ('swish', -4),
       'stamp': ('boom', -4), 'stick': None, 'tick': ('ding', 0), 'number': ('swell', -4), 'whoosh': ('deep_whoosh', -4)}
TR_SFX = {'dissolve': [(-0.3, 'low_swish', -4)],
          'glow': [(-0.35, 'swell', -6), (0.0, 'sparkle', 0)]}


def _left():
    import layout as L
    return 60 if lib.VERTICAL else L.PIP_SAFE[2] + 40


def _dark(color):
    return sum(color[:3]) / 3 < 150


# ======================================================================
# 背景：近黑渐变 + 暖光 + 星尘 + 颗粒 + 暗角
# ======================================================================

@functools.lru_cache(1)
def _dust():
    rng = np.random.default_rng(23)
    n = 90
    return [(rng.uniform(0, 1), rng.uniform(0, 1), rng.uniform(0.8, 2.6), rng.uniform(0, 6.3), rng.uniform(0.4, 1.4),
             rng.uniform(4, 14)) for _ in range(n)]


def paper(c, t, head=None, dust=True):
    """铺底。head = 顶上一行小字（这一段讲什么，可以不给）；dust=False 不要星尘"""
    c.drawRect(skia.Rect.MakeWH(W, H), K.lin(0, 0, 0, H, [BG0, BG1]))
    gx = W * (0.72 if not lib.VERTICAL else 0.62) + 60 * math.sin(t * 0.13)
    gy = H * (0.28 if not lib.VERTICAL else 0.22) + 40 * math.cos(t * 0.11)
    K.glow(c, gx, gy, max(W, H) * 0.62, WARMG, 0.95)
    K.glow(c, W * 0.12, H * 0.92, max(W, H) * 0.4, (30, 34, 44), 0.8)
    if dust:
        for fx, fy, r, ph, sp, drift in _dust():
            y = (fy * H - t * drift) % H
            x = fx * W + 10 * math.sin(t * 0.3 + ph)
            tw = 0.5 + 0.5 * math.sin(t * sp * 2 + ph)
            c.drawCircle(x, y, r, paint(GOLD, 0.12 + 0.45 * tw * (r / 2.6)))
    K.grain(c, t, 0.035, light=True)
    K.vignette(c, 0.6)
    if head:
        x0 = 60 if lib.VERTICAL else _left()
        y0 = 70
        w = K.ptext(c, head, x0, y0, 30, paint(GOLD, 0.9), 'hand', 'l', track=0.3)
        x1 = x0 + w + 26
        c.drawLine(x1, y0, W - 60, y0, K.lin(x1, 0, W - 60, 0, [GOLD + (0.7,), GOLD + (0.0,)]))
        _diamond(c, x1, y0, 6, GOLD, 0.9)


def _diamond(c, x, y, s, color, a=1.0):
    path = skia.Path()
    path.moveTo(x, y - s); path.lineTo(x + s, y); path.lineTo(x, y + s); path.lineTo(x - s, y); path.close()
    c.drawPath(path, paint(color, a))


def _spark(c, x, y, a=1.0, r=5):
    """线笔尖上那颗亮点"""
    if a <= 0.01:
        return
    K.glow(c, x, y, r * 5, GOLD_HI, 0.55 * a)
    c.drawCircle(x, y, r * 0.6, paint((255, 250, 235), a))


def _gold_line(c, path, p, w=3, color=None, a=1.0, spark=True):
    """细金线 + 一层发光，笔尖带亮点"""
    if p <= 0:
        return
    pp = lib.partial_path(path, p) if p < 1 else path
    clr = color or GOLD
    for wd, al, bl in ((w * 3.5, 0.25, w * 2.0), (w, 1.0, None)):
        pt = paint(clr, a * al, stroke=wd, blur=bl)
        pt.setStrokeCap(skia.Paint.kRound_Cap)
        pt.setStrokeJoin(skia.Paint.kRound_Join)
        c.drawPath(pp, pt)
    if spark and p < 1:
        m = skia.PathMeasure(path, False)
        pos, _ = m.getPosTan(m.getLength() * p)
        _spark(c, pos.x(), pos.y(), a)


# ======================================================================
# 字
# ======================================================================

def _gold_char(size, kind='round', colors=None):
    return lambda c_, ch, x_, y_, a_: K.grad_text(c_, ch, x_, y_, size, colors or GOLD_G, kind, 'l', a_)


def title(c, s, x, y, size, t, t0, sub_en=None, color=None, a=1.0, seed=0):
    """大标题：金色渐变宋体，一个字一个字由虚到实浮出来，背后一团光，下面一条从中间往两边拉开的细金线"""
    if t < t0:
        return
    tw = text_w(s, size, 'round')
    K.glow(c, x, y, tw * 0.8 + size, (120, 95, 50), 0.45 * a * e_out(prog(t, t0, 0.8)))
    draw = _gold_char(size) if color is None else None
    K.chars(c, s, x, y, size, t, t0, 7, color, 'round', 'c', a, mode='blur', slots=3.0, draw=draw)
    q = e_out(prog(t, t0 + 0.4, 0.7))
    if q > 0:
        hw = (tw / 2 + size * 0.7) * q
        ly = y + size * 0.78
        c.drawLine(x - hw, ly, x + hw, ly, K.lin(x - hw, 0, x + hw, 0, [GOLD + (0.0,), GOLD + (0.9,), GOLD + (0.0,)],
                                               None, a))
        _diamond(c, x, ly, 7 * q, GOLD, a)
    if sub_en:
        qe = prog(t, t0 + 0.3, 0.6)
        with lib.blurred(c, (1 - e_out(qe)) * 6, a * qe, bounds=(x - tw, y - size * 1.4, tw * 2, size * 0.6)):
            K.ptext(c, sub_en.upper(), x, y - size * 0.92, size * 0.17, paint(LINE2), 'en', 'c', track=0.42)


def tag(c, label, x, y, size, t, t0, color=None, fg=None, a=1.0, seed=0):
    """标签：深色玻璃小胶囊 + 细金边 + 金字，由虚到实从左边滑进来。返回宽度"""
    tw = text_w(label, size, 'hand')
    h = size * 1.6
    w = tw + h * 0.9
    if a <= 0:                 # a=0：只量宽度不画
        return w
    q = prog(t, t0, 0.45)
    if q > 0:
        e = e_out(q)
        with xf(c, x, y, dx=(1 - e) * -24):
            with lib.blurred(c, (1 - e) * 8, a * e, bounds=(x - 30, y - h, w + 60, h * 2)):
                rr = rrect(x, y - h / 2, w, h, h / 2)
                c.drawRRect(rr, paint(color or GLASS, 0.9))
                c.drawRRect(rr, paint(GOLD, 0.75, stroke=1.6))
                text(c, label, x + w / 2, y, size, fg or GOLD, 'hand', 'c')
    return w


def write(c, s, x, y, size, t, t0, cps=9.0, color=None, kind='hand', align='l', a=1.0, pen_on=False, **_):
    """一个字一个字由虚到实浮出来。返回出到的位置 (x, y)"""
    _, end = K.chars(c, s, x, y, size, t, t0, cps * 1.1, color or TXT, kind, align, a, mode='blur', slots=2.5)
    return (end, y)


def write_d(s, cps=9.0):
    return (len(s) + 2.5) / (cps * 1.1)


def _coin(c, x, y, w, h, r, a=1.0):
    c.drawRRect(rrect(x, y, w, h, r), K.lin(0, y, 0, y + h, COIN_G, None, a))
    c.drawRRect(rrect(x + 3, y + 3, w - 6, h - 6, max(1, r - 3)), paint(GOLD_HI, a * 0.7, stroke=1.4))


def _seal(c, x, y, w, h, r, color=None, a=1.0):
    c.drawRRect(rrect(x, y, w, h, r), paint(color or SEAL, a))
    c.drawRRect(rrect(x + 5, y + 5, w - 10, h - 10, max(1, r - 3)), paint(SEAL_IN, a * 0.55, stroke=1.6))


def block_word(c, s, x, y, size, t, t0, color=None, fg=None, align='c', a=1.0, seed=0, **_):
    """重点词：默认是印章红块里的浅字；color=T.ACCENT2 是金币块里的深字。由虚到实落下来，背后一点光。返回宽度"""
    tw = text_w(s, size, 'round')
    w, h = tw + size * 0.7, size * 1.42
    bx = x - w / 2 if align == 'c' else (x if align == 'l' else x - w)
    if a <= 0:                 # a=0：只量宽度不画
        return w
    q = prog(t, t0, 0.35)
    if q > 0:
        e = e_out(q)
        clr = color or ACCENT
        gold = tuple(clr[:3]) == tuple(GOLD)
        K.glow(c, bx + w / 2, y, w * 0.8, (150, 110, 60) if gold else (140, 40, 30), 0.35 * a * e)
        with xf(c, bx + w / 2, y, lerp(1.12, 1.0, e)):
            with lib.blurred(c, (1 - e) * 10, a * clamp(q * 2.5), bounds=(bx - 40, y - h, w + 80, h * 2)):
                if gold:
                    _coin(c, bx, y - h / 2, w, h, 8)
                else:
                    _seal(c, bx, y - h / 2, w, h, 8, clr)
                tc = fg or ((40, 28, 12) if gold or not _dark(clr) else SEAL_TXT)
                text(c, s, bx + w / 2, y, size, tc, 'round', 'c')
    return w


def number(c, s, unit, x, y, size, t, t0, color=None, align='c', a=1.0, seed=0):
    """大数字 + 单位：金色渐变的衬线数字，由虚到实、从 0 数上去，背后一团光。返回总宽；a=0 只量宽度"""
    nw = text_w(s, size, 'num')
    us = size * 0.36
    gap = size * 0.12
    uw = text_w(unit, us, 'round') if unit else 0
    w = nw + (gap + uw if unit else 0)
    if a <= 0:
        return w
    q = prog(t, t0, 0.5)
    if q <= 0:
        return w
    e = e_out(q)
    bx = x - w / 2 if align == 'c' else (x if align == 'l' else x - w)
    K.glow(c, bx + w / 2, y, w * 0.75 + size * 0.3, (130, 100, 52), 0.5 * a * e)
    s_ = K.count(s, prog(t, t0, 0.9))
    with lib.blurred(c, (1 - e) * size * 0.06, a * e, bounds=(bx - size, y - size, w + size * 2, size * 2)):
        with xf(c, bx + w / 2, y, lerp(1.06, 1.0, e)):
            if color is None:
                K.grad_text(c, s_, bx + nw, y, size, GOLD_G, 'num', 'r')
            else:
                text(c, s_, bx + nw, y, size, color, 'num', 'r')
            if unit:
                K.grad_text(c, unit, bx + nw + gap, y + size * 0.22, us, GOLD_G, 'round', 'l')
    return w


def mark(c, s, x, y, size, t, t0, color=None, rot=8, a=1.0):
    """大号标点：金色渐变，由虚到实浮出来，之后轻轻上下浮"""
    q = prog(t, t0, 0.5)
    if q <= 0:
        return
    e = e_out(q)
    fl = 6 * math.sin((t - t0) * 1.6)
    K.glow(c, x, y, size * 0.9, (130, 100, 52), 0.45 * a * e)
    with lib.blurred(c, (1 - e) * 12, a * e, bounds=(x - size, y - size * 1.2, size * 2, size * 2.4)):
        with xf(c, x, y, lerp(1.2, 1.0, e), rot=rot * 0.4, dy=fl):
            if color is None:
                K.grad_text(c, s, x, y, size, GOLD_G, 'round', 'c')
            else:
                text(c, s, x, y, size, color, 'round', 'c')


def stamp(c, s, cx, cy, size, t, t0, color=None, rot=-7, a=1.0, seed=0):
    """结论：一枚红色印章砸下来（放大 → 落定 → 震一下），落定时一圈金色光环散开"""
    tw = text_w(s, size, 'round')
    w, h = tw + size * 0.8, size * 1.6
    d = t - t0
    if d <= 0:
        return
    q = clamp(d / 0.22)
    sc = lerp(1.7, 1.0, e_in(q))
    dx, dy = shake(t, t0 + 0.22, 0.25, 6)
    with xf(c, cx, cy, sc, rot=rot * 0.6, a=a * clamp(q * 3), dx=dx, dy=dy):
        _seal(c, cx - w / 2, cy - h / 2, w, h, 10, color)
        text(c, s, cx, cy, size, SEAL_TXT, 'round', 'c')
    r = clamp((d - 0.22) / 0.7)
    if 0 < r < 1:
        rr = w * (0.55 + 0.3 * e_out(r))
        c.drawCircle(cx, cy, rr, paint(GOLD, a * (1 - r) * 0.8, stroke=3 * (1 - r) + 1))


# ======================================================================
# 线和标记
# ======================================================================

def hunder(c, x0, x1, y, p=1.0, color=None, seed=0, a=1.0, **_):
    """下划线：细金线从左往右拉，笔尖带亮点"""
    path = skia.Path()
    path.moveTo(x0, y); path.lineTo(x1, y)
    _gold_line(c, path, e_out(clamp(p)), 3, color, a)


def hcircle(c, cx, cy, rx, ry=None, p=1.0, color=None, seed=0, a=1.0, **_):
    """圈出来：细金线椭圆，一笔转一圈，笔尖带亮点"""
    _gold_line(c, K.ellipse_path(cx, cy, rx, ry or rx, -100, 360), e_io(clamp(p)), 3, color, a)


def harrow(c, x0, y0, x1, y1, p=1.0, color=None, seed=0, a=1.0, curve=0.15, **_):
    """弧形箭头：细金线 + 空心箭头，从尾画到头"""
    if p <= 0:
        return
    _gold_line(c, K.curve_path(x0, y0, x1, y1, curve), e_io(clamp(p)), 3, color, a)
    if p > 0.85:
        K.arrow_head(c, x1, y1, K.head_angle(x0, y0, x1, y1, curve), 22, color or GOLD, a * clamp((p - 0.85) * 6),
                     fill=False, w=3)


def hcheck(c, x, y, s, p=1.0, color=None, seed=0, a=1.0, **_):
    """勾：细金圈 + 金勾"""
    if p <= 0:
        return
    clr = color or GOLD
    r = s * 0.56
    K.stroke_path(c, K.ellipse_path(x, y, r, r, -90, 360), e_out(clamp(p * 2)), clr, 2, a * 0.8)
    path = skia.Path()
    path.moveTo(x - r * 0.45, y + r * 0.02); path.lineTo(x - r * 0.1, y + r * 0.36); path.lineTo(x + r * 0.5, y - r * 0.34)
    _gold_line(c, path, clamp(p * 2 - 0.6), max(2.5, s * 0.08), clr, a, spark=False)


def hcross(c, x, y, s, p=1.0, color=None, seed=0, a=1.0, **_):
    if p <= 0:
        return
    clr = color or NO_RED
    r = s * 0.56
    K.stroke_path(c, K.ellipse_path(x, y, r, r, -90, 360), e_out(clamp(p * 2)), clr, 2, a * 0.8)
    k = r * 0.38
    for i, (ax, ay, bx, by) in enumerate(((-k, -k, k, k), (k, -k, -k, k))):
        path = skia.Path()
        path.moveTo(x + ax, y + ay); path.lineTo(x + bx, y + by)
        _gold_line(c, path, clamp(p * 2 - 0.6 - i * 0.3), max(2.5, s * 0.08), clr, a, spark=False)


def marker(c, x0, x1, y, h, p=1.0, color=None, a=0.85, seed=0):
    """高亮：一条暖金色的光带从左往右铺，底边一条细金线（画在字下面）"""
    if p <= 0:
        return
    xe = lerp(x0, x1, e_out(p))
    clr = color or GOLD
    c.drawRect(skia.Rect.MakeLTRB(x0, y - h / 2, xe, y + h / 2),
               K.lin(0, y - h / 2, 0, y + h / 2, [clr + (0.0,), clr + (0.22,)], None, a))
    c.drawLine(x0, y + h / 2, xe, y + h / 2, paint(clr, a * 0.9, stroke=2))


def squiggle(c, x, y, w, p=1.0, color=None, seed=0, a=1.0, **_):
    """占位的字：几段暗灰细条（像还没亮起来的说明文字）"""
    rng = np.random.default_rng(seed + 3)
    xs, cx = [], x
    while cx < x + w - 30:
        L_ = min(rng.uniform(50, 170), x + w - cx)
        xs.append((cx, L_))
        cx += L_ + rng.uniform(12, 20)
    xe = x + w * e_out(clamp(p))
    for sx, L_ in xs:
        if sx >= xe:
            break
        c.drawRRect(rrect(sx, y - 3, min(L_, xe - sx), 6, 3), paint(color or LINE3, a * 0.6))


def hline(c, x0, y0, x1, y1, p=1.0, color=None, seed=0, a=1.0, **_):
    """细金引线，两头小菱形（说明连到东西上）"""
    if p <= 0:
        return
    path = skia.Path()
    path.moveTo(x0, y0); path.lineTo(x1, y1)
    _gold_line(c, path, e_out(clamp(p)), 1.6, color, a * 0.85)
    _diamond(c, x0, y0, 5, color or GOLD, a)
    if p >= 1:
        _diamond(c, x1, y1, 5, color or GOLD, a)


# ======================================================================
# 卡片、照片
# ======================================================================

def _brackets(c, x, y, w, h, L_=30, color=None, a=1.0, wd=3):
    clr = color or GOLD
    pt = paint(clr, a, stroke=wd)
    pt.setStrokeCap(skia.Paint.kSquare_Cap)
    for px, py, sx, sy in ((x, y, 1, 1), (x + w, y, -1, 1), (x, y + h, 1, -1), (x + w, y + h, -1, -1)):
        path = skia.Path()
        path.moveTo(px, py + sy * L_); path.lineTo(px, py); path.lineTo(px + sx * L_, py)
        c.drawPath(path, pt)


def sheet(c, x, y, w, h, t, t0, seed=0, rot=0.0, layers=1, a=1.0, fill=None, **_):
    """卡片：深色玻璃 + 细边 + 四角金色括号，由虚到实浮上来。layers = 后面再叠几张（往右上错开、更暗）"""
    q = prog(t, t0, 0.5)
    if q <= 0:
        return
    e = e_out(q)
    with xf(c, x + w / 2, y + h / 2, dy=(1 - e) * 24):
        with lib.blurred(c, (1 - e) * 10, a * e, bounds=(x - 60, y - 60, w + 120, h + 120)):
            for k in range(layers - 1, 0, -1):
                rr = rrect(x + 18 * k, y - 16 * k, w, h, 14)
                c.drawRRect(rr, paint(GLASS, 0.6))
                c.drawRRect(rr, paint(GLASS_B, 0.8, stroke=1.4))
            rr = rrect(x, y, w, h, 14)
            c.drawRRect(rr, K.lin(0, y, 0, y + h, [mix(fill or GLASS, (255, 255, 255), 0.04), fill or GLASS], None, 0.92))
            c.drawRRect(rr, paint(GLASS_B, 1, stroke=1.6))
            c.drawLine(x + 30, y + 1, x + w - 30, y + 1,
                       K.lin(x, 0, x + w, 0, [GOLD + (0.0,), GOLD + (0.5,), GOLD + (0.0,)]))
            _brackets(c, x - 8, y - 8, w + 16, h + 16, 30, GOLD, 0.9)


def photo(c, img, x, y, w, h, t, t0, rot=0.0, seed=0, caption=None, focus=(0.5, 0.5), push=0.05, a=1.0, **_):
    """照片：细金框里的图（四角金括号），下面一行小字说明；由虚到实浮出来，落定后图在框里慢推"""
    q = prog(t, t0, 0.55)
    if q <= 0 or img is None:
        return
    e = e_out(q)
    bot = 56 if caption else 0
    ih = h - bot
    with xf(c, x + w / 2, y + h / 2, lerp(1.04, 1.0, e)):
        with lib.blurred(c, (1 - e) * 12, a * e, bounds=(x - 60, y - 60, w + 120, h + 120)):
            c.drawRect(skia.Rect.MakeXYWH(x, y, w, ih), paint((8, 9, 12)))
            c.drawRect(skia.Rect.MakeXYWH(x + 8, y + 8, w - 16, ih - 16), paint((236, 232, 220)))   # 透明底的图（官网标志）垫浅色
            K.cover(c, img, x + 8, y + 8, w - 16, ih - 16, t, t0, focus, push)
            c.drawRect(skia.Rect.MakeXYWH(x + 8, y + 8, w - 16, ih - 16), paint(GOLD, 0.35, stroke=1))
            c.drawRect(skia.Rect.MakeXYWH(x, y, w, ih), paint(GOLD, 0.7, stroke=1.6))
            _brackets(c, x - 8, y - 8, w + 16, ih + 16, 34, GOLD, 0.95)
            if caption:
                cy_ = y + ih + bot / 2 + 6
                c.drawLine(x, cy_, x + 36, cy_, paint(GOLD, 0.9, stroke=2))
                K.ptext(c, caption, x + 50, cy_, 26, paint(LINE1), 'hand', 'l', track=0.12)


# ======================================================================
# 字幕、人物小窗
# ======================================================================

def sub(c, s, x, y, size, maxw):
    """字幕：半透明深色条上的浅色宋体字，条两头淡出"""
    w = text_w(s, size, 'sub')
    if w > maxw:
        size = size * maxw / w
        w = maxw
    pad, h = size * 1.6, size * 1.6
    c.drawRect(skia.Rect.MakeLTRB(x - w / 2 - pad, y - h / 2, x + w / 2 + pad, y + h / 2),
               K.lin(x - w / 2 - pad, 0, x + w / 2 + pad, 0,
                     [(5, 6, 9, 0.0), (5, 6, 9, 0.72), (5, 6, 9, 0.72), (5, 6, 9, 0.0)], [0, 0.18, 0.82, 1]))
    text(c, s, x, y + 2, size, (0, 0, 0), 'sub', 'c', 0.6)
    text(c, s, x, y, size, TXT, 'sub', 'c')


def pip_frame(c, x, y, w, h, r, a):
    """人物小窗：细金边 + 四角金括号"""
    if a <= 0.01:
        return
    c.drawRRect(rrect(x, y, w, h, r), paint(GOLD, a * 0.6, stroke=1.6))
    _brackets(c, x - 9, y - 9, w + 18, h + 18, 28, GOLD, a * 0.95)


# ======================================================================
# 转场
# ======================================================================

def _tr_dissolve(c, A, B, x, fidx):
    """溶解：上一页虚掉、轻轻放大着淡出，下一页由虚到实淡入"""
    e = e_io(x)
    k = math.sin(math.pi * x)
    c.clear(col(BG1))
    K.di(c, A, p=K.bp(14 * k, 14 * k, 1 - e), s=1 + 0.04 * e)
    K.di(c, B, p=K.bp(14 * k, 14 * k, e), s=1.04 - 0.04 * e)


def _tr_glow(c, A, B, x, fidx):
    """金光：画面中间亮起一团暖金色的光把上一页吞掉，光退下去露出下一页"""
    K.di(c, A if x < 0.5 else B, p=K.bp(10 * math.sin(math.pi * x), 10 * math.sin(math.pi * x)))
    k = math.sin(math.pi * x)
    cx = CX if lib.VERTICAL else (_left() + W) / 2
    r = max(W, H) * (0.4 + 0.8 * k)
    c.drawRect(skia.Rect.MakeWH(W, H), K.radial(cx, CY, r, [(255, 244, 214, 0.95 * k), (229, 190, 120, 0.7 * k),
                                                        (60, 45, 25, 0.0)], [0, 0.45, 1]))


TRANSITIONS = {'dissolve': _tr_dissolve, 'glow': _tr_glow}
