"""华尔街财经：深藏青的布纹底 + 顶上一束光 + 重暗角；标题是金属银的特粗黑体，上面一行金色英文小字；
数字是 Bebas 窄体的金色大数字（数上去、落定后一道反光扫过）；标签是金边深色小牌；重点词是金 / 绿 / 红胶囊；
照片是白色新闻卡 + 红色来源标签；结论是一块深色金边牌子，砸下来后反光扫过。
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
NAVY0, NAVY1 = (16, 26, 48), (5, 9, 18)        # 底：深藏青
SPOT = (52, 78, 128)                           # 顶光
SILVER_G = [(255, 255, 255), (222, 228, 238), (150, 162, 180), (232, 236, 244)]   # 金属银字
GOLD_G = [(255, 238, 186), (242, 204, 116), (204, 154, 62)]                      # 金色数字
GOLD = (201, 169, 90)                          # 金边、金线
GOLD_TXT = (243, 230, 184)                     # 小牌上的金字
PLATE_G = [(29, 31, 36), (11, 12, 15)]         # 深色小牌
PILL_GOLD = [(232, 196, 104), (141, 106, 34)]
PILL_GREEN = [(54, 163, 100), (31, 110, 64)]
PILL_RED = [(212, 83, 79), (143, 35, 38)]
OK, NO = (47, 158, 91), (210, 60, 60)
HILITE = (242, 226, 126)                       # 黄色高亮
CARD = (253, 253, 251)
SRC_RED = (184, 40, 47)
TXT = (246, 247, 250)
DIM = (150, 160, 180)
GOLDC, GREEN, REDC = (216, 180, 90), (54, 163, 100), (212, 83, 79)               # 传给 block_word 的 color
INK = TXT
ACCENT, ACCENT2, MUTE = GOLDC, GREEN, DIM
lib.use_palette(INK=TXT, SUBINK=DIM, MUTE=DIM, LINE=(40, 52, 76), BG=NAVY0, ACC=GOLD, ACC2=GREEN)

# ---------- 字体：思源黑体（正文 700、标题 900）+ Bebas Neue（大数字）+ Montserrat（英文） ----------
lib.use_kinds(hand=('noto_sans_sc', 700, 0.36), round=('noto_sans_sc', 900, 0.36), sub=('noto_sans_sc', 800, 0.36),
              num=('bebas_neue', 400, 0.36), en=('montserrat', 700, 0.35),
              cn=('noto_sans_sc', 700, 0.36), cn_med=('noto_sans_sc', 500, 0.36), cn_reg=('noto_sans_sc', 400, 0.36),
              cn_black=('noto_sans_sc', 900, 0.36))

# ---------- 转场、音效 ----------
lib.DEFAULT_TR = 'whip'
ALT_TR = 'zoom'               # 换话题时用的第二种转场：scenes.py 里写 tr=T.ALT_TR
lib.TR_D.update(whip=0.4)
SFX = {'write': ('tick', -6), 'drop': ('low_swish', -4), 'pop': ('click', -4), 'mark': ('whoosh', -8),
       'stamp': ('impact', -4), 'stick': None, 'tick': ('ding', 0), 'number': ('landing', -4), 'whoosh': ('whip', -4)}
TR_SFX = {'whip': [(-0.2, 'whip', -2)]}


def _left():
    import layout as L
    return 60 if lib.VERTICAL else L.PIP_SAFE[2] + 40


def _pill_colors(color):
    c3 = tuple(color[:3])
    if c3 == GREEN:
        return PILL_GREEN, TXT
    if c3 == REDC:
        return PILL_RED, TXT
    if c3 == GOLDC:
        return PILL_GOLD, (30, 22, 8)
    return [mix(c3, (255, 255, 255), 0.15), mix(c3, (0, 0, 0), 0.35)], (TXT if sum(c3) < 450 else (30, 22, 8))


def _shadow_text(c, s, x, y, size, kind='hand', align='c', a=1.0, d=4):
    K.ptext(c, s, x, y + d, size, paint((0, 0, 0), 0.75 * a, blur=d * 1.5), kind, align)


def _sweep(c, rect, p, a=0.6):
    """反光：一道斜的白光从左扫到右（只亮在已经画了东西的地方；调用前要 saveLayer）"""
    if not 0 < p < 1:
        return
    x0, w = rect.left(), rect.width()
    bx = lerp(x0 - w * 0.3, x0 + w * 1.1, e_io(p))
    pt = K.lin(bx, rect.top(), bx + w * 0.25, rect.bottom(),
               [(255, 255, 255, 0.0), (255, 255, 255, a), (255, 255, 255, 0.0)])
    pt.setBlendMode(skia.BlendMode.kSrcATop)
    c.drawRect(rect, pt)


# ======================================================================
# 背景：深藏青布纹 + 顶光 + 重暗角
# ======================================================================

@functools.lru_cache(1)
def _fabric_img():
    n = 192
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    v = 0.5 * np.sin((xx + yy) * 2 * np.pi / 6) + 0.5 * np.sin((xx - yy) * 2 * np.pi / 6)
    rng = np.random.default_rng(4)
    a = np.clip((v * 0.5 + 0.5) * 0.045 + rng.normal(0, 1, (n, n)) * 0.012, 0, 1)
    arr = np.zeros((n, n, 4), np.uint8)
    arr[..., 3] = (a * 255).astype(np.uint8)
    arr[..., :3] = arr[..., 3:4]
    return skia.Image.fromarray(arr, colorType=skia.ColorType.kRGBA_8888_ColorType)


def paper(c, t, head=None, spot=True):
    """铺底。head = 左上角金色小标签（这一段讲什么，可以不给）"""
    c.drawRect(skia.Rect.MakeWH(W, H), K.lin(0, 0, 0, H, [NAVY0, NAVY1]))
    p = skia.Paint()
    p.setShader(_fabric_img().makeShader(skia.TileMode.kRepeat, skia.TileMode.kRepeat, lib.SAMP))
    c.drawRect(skia.Rect.MakeWH(W, H), p)
    if spot:
        sx = (W / 2 if lib.VERTICAL else (_left() + W) / 2) + 40 * math.sin(t * 0.2)
        c.save()
        c.scale(1.5, 1.0)                                  # 横着拉宽的一束光（边缘自然淡掉，没有硬边）
        c.drawRect(skia.Rect.MakeXYWH(0, 0, W, H),
                   K.radial(sx / 1.5, -H * 0.05, H * 0.95, [SPOT + (0.75,), SPOT + (0.25,), SPOT + (0.0,)], [0, 0.5, 1]))
        c.restore()
    K.vignette(c, 0.75, inner=0.4)
    if head:
        x0 = 60 if lib.VERTICAL else _left()
        y0 = 72
        c.drawRect(skia.Rect.MakeXYWH(x0, y0 - 18, 6, 36), paint(GOLD))
        w = K.ptext(c, head, x0 + 20, y0, 30, paint(GOLD_TXT), 'hand', 'l', track=0.12)
        x1 = x0 + 20 + w + 24
        c.drawLine(x1, y0, W - 60, y0, K.lin(x1, 0, W - 60, 0, [GOLD + (0.6,), GOLD + (0.0,)]))


# ======================================================================
# 字
# ======================================================================

def title(c, s, x, y, size, t, t0, sub_en=None, color=None, a=1.0, seed=0):
    """大标题：金属银的特粗黑体（带深色投影），从下面升上来、由虚到实；上面一行金色英文小字往两边拉开"""
    q = prog(t, t0, 0.5)
    if q <= 0:
        return
    e = e_out(q)
    tw = text_w(s, size, 'round')
    with lib.blurred(c, (1 - e) * 10, a * clamp(q * 2), bounds=(x - tw, y - size * 1.6, tw * 2, size * 3)):
        with xf(c, x, y, dy=(1 - e) * size * 0.35):
            _shadow_text(c, s, x, y, size, 'round', 'c', 1, size * 0.05)
            if color is None:
                K.grad_text(c, s, x, y, size, SILVER_G, 'round', 'c', pos=[0, 0.45, 0.8, 1])
            else:
                text(c, s, x, y, size, color, 'round', 'c')
    if sub_en:
        qe = e_out(prog(t, t0 + 0.2, 0.6))
        K.ptext(c, sub_en.upper(), x, y - size * 0.9, size * 0.17, paint(GOLD, a * qe), 'en', 'c', track=0.2 + 0.25 * qe)


def tag(c, label, x, y, size, t, t0, color=None, fg=None, a=1.0, seed=0):
    """标签：深色小牌 + 细金边 + 金字，从左边滑进来。返回宽度"""
    tw = text_w(label, size, 'hand')
    h = size * 1.5
    w = tw + size * 0.9
    if a <= 0:                 # a=0：只量宽度不画
        return w
    q = prog(t, t0, 0.3)
    if q > 0:
        e = e_out(q)
        with xf(c, x, y, a=a * clamp(q * 2.5), dx=(1 - e) * -26):
            rr = rrect(x, y - h / 2, w, h, 6)
            c.drawRRect(rr, K.lin(0, y - h / 2, 0, y + h / 2, PLATE_G))
            c.drawRRect(rr, paint(color or GOLD, 0.9, stroke=1.6))
            text(c, label, x + w / 2, y, size, fg or GOLD_TXT, 'hand', 'c')
    return w


def write(c, s, x, y, size, t, t0, cps=9.0, color=None, kind='hand', align='l', a=1.0, pen_on=False, **_):
    """白字带投影，一个字一个字淡入上浮。返回出到的位置 (x, y)"""
    clr = color or TXT

    def draw(c_, ch, x_, y_, a_):
        K.ptext(c_, ch, x_, y_ + 3, size, paint((0, 0, 0), 0.7 * a_, blur=4), kind, 'l')
        text(c_, ch, x_, y_, size, clr, kind, 'l', a_)

    _, end = K.chars(c, s, x, y, size, t, t0, cps * 1.2, clr, kind, align, a, mode='fade', slots=2.0, draw=draw)
    return (end, y)


def write_d(s, cps=9.0):
    return (len(s) + 2.0) / (cps * 1.2)


def block_word(c, s, x, y, size, t, t0, color=None, fg=None, align='c', a=1.0, seed=0, **_):
    """重点词：胶囊。默认金色（深字）；color=T.ACCENT2 绿（白字，涨、对）；color=T.REDC 红（白字，跌、错）。弹出来。返回宽度"""
    tw = text_w(s, size, 'round')
    h = size * 1.42
    w = tw + h * 0.8
    bx = x - w / 2 if align == 'c' else (x if align == 'l' else x - w)
    if a <= 0:                 # a=0：只量宽度不画
        return w
    q = prog(t, t0, 0.3)
    if q > 0:
        grad, tc = _pill_colors(color or ACCENT)
        with xf(c, bx + w / 2, y, lerp(0.6, 1.0, e_back(q)), a=a * clamp(q * 3)):
            rr = rrect(bx, y - h / 2, w, h, h / 2)
            c.drawRRect(rrect(bx, y - h / 2 + 6, w, h, h / 2), paint((0, 0, 0), 0.5, blur=8))
            c.drawRRect(rr, K.lin(0, y - h / 2, 0, y + h / 2, grad))
            c.drawRRect(rrect(bx + 3, y - h / 2 + 2, w - 6, h * 0.45, h / 2), paint(WHITE, 0.18))
            text(c, s, bx + w / 2, y, size, fg or tc, 'round', 'c')
    return w


def number(c, s, unit, x, y, size, t, t0, color=None, align='c', a=1.0, seed=0):
    """大数字 + 单位：Bebas 窄体金色大数字，从 0 数上去，落定后一道反光扫过。返回总宽；a=0 只量宽度"""
    nw = text_w(s, size, 'num')
    us = size * 0.34
    gap = size * 0.08
    uw = text_w(unit, us, 'round') if unit else 0
    w = nw + (gap + uw if unit else 0)
    if a <= 0:
        return w
    q = prog(t, t0, 0.35)
    if q <= 0:
        return w
    bx = x - w / 2 if align == 'c' else (x if align == 'l' else x - w)
    s_ = K.count(s, prog(t, t0, 0.8))
    rect = skia.Rect.MakeXYWH(bx - 20, y - size * 0.7, w + 40, size * 1.4)
    with xf(c, bx + w / 2, y, lerp(0.75, 1.0, e_back(q)), a=a * clamp(q * 3)):
        K.ptext(c, s_, bx + nw, y + size * 0.04, size, paint((0, 0, 0), 0.7, blur=size * 0.03), 'num', 'r')
        c.saveLayer(rect, None)
        if color is None:
            K.grad_text(c, s_, bx + nw, y, size, GOLD_G, 'num', 'r')
        else:
            text(c, s_, bx + nw, y, size, color, 'num', 'r')
        if unit:
            K.grad_text(c, unit, bx + nw + gap, y + size * 0.22, us, GOLD_G, 'round', 'l')
        _sweep(c, rect, prog(t, t0 + 0.85, 0.6))
        c.restore()
    return w


def mark(c, s, x, y, size, t, t0, color=None, rot=8, a=1.0):
    """大号标点：金色，弹出来"""
    q = prog(t, t0, 0.3)
    if q <= 0:
        return
    with xf(c, x, y, lerp(0.5, 1.0, e_back(q)), rot=rot * 0.5, a=a * clamp(q * 3)):
        _shadow_text(c, s, x, y, size, 'round', 'c', 1, size * 0.04)
        if color is None:
            K.grad_text(c, s, x, y, size, GOLD_G, 'round', 'c')
        else:
            text(c, s, x, y, size, color, 'round', 'c')


def stamp(c, s, cx, cy, size, t, t0, color=None, rot=-7, a=1.0, seed=0):
    """结论：深色金边牌子砸下来，金字，落定后一道反光扫过"""
    tw = text_w(s, size, 'round')
    w, h = tw + size * 1.0, size * 1.6
    d = t - t0
    if d <= 0:
        return
    q = clamp(d / 0.2)
    dx, dy = shake(t, t0 + 0.2, 0.22, 5)
    rect = skia.Rect.MakeXYWH(cx - w / 2 - 6, cy - h / 2 - 6, w + 12, h + 12)
    with xf(c, cx, cy, lerp(1.5, 1.0, e_in(q)), rot=rot * 0.3, a=a * clamp(q * 3), dx=dx, dy=dy):
        c.drawRRect(rrect(cx - w / 2, cy - h / 2 + 10, w, h, 12), paint((0, 0, 0), 0.6, blur=14))
        c.saveLayer(rect, None)
        rr = rrect(cx - w / 2, cy - h / 2, w, h, 12)
        c.drawRRect(rr, K.lin(0, cy - h / 2, 0, cy + h / 2, PLATE_G))
        c.drawRRect(rr, paint(color or GOLD, 1, stroke=3))
        c.drawRRect(rrect(cx - w / 2 + 7, cy - h / 2 + 7, w - 14, h - 14, 8), paint(color or GOLD, 0.5, stroke=1.2))
        K.grad_text(c, s, cx, cy, size, GOLD_G, 'round', 'c')
        _sweep(c, rect, prog(t, t0 + 0.35, 0.6), 0.45)
        c.restore()


# ======================================================================
# 线和标记
# ======================================================================

def _glow_line(c, path, p, color=None, w=5, a=1.0):
    if p <= 0:
        return
    clr = color or GOLD
    pp = lib.partial_path(path, p) if p < 1 else path
    for wd, al, bl in ((w * 3, 0.35, w * 1.6), (w, 1.0, None)):
        pt = paint(clr, a * al, stroke=wd, blur=bl)
        pt.setStrokeCap(skia.Paint.kRound_Cap)
        pt.setStrokeJoin(skia.Paint.kRound_Join)
        c.drawPath(pp, pt)


def hunder(c, x0, x1, y, p=1.0, color=None, seed=0, a=1.0, **_):
    """下划线：一道发光的金线从左往右"""
    path = skia.Path()
    path.moveTo(x0, y); path.lineTo(x1, y)
    _glow_line(c, path, e_out(clamp(p)), color, 5, a)


def hcircle(c, cx, cy, rx, ry=None, p=1.0, color=None, seed=0, a=1.0, **_):
    """圈出来：发光的金色圆圈，一笔转一圈"""
    _glow_line(c, K.ellipse_path(cx, cy, rx, ry or rx, -100, 360), e_io(clamp(p)), color, 5, a)


def harrow(c, x0, y0, x1, y1, p=1.0, color=None, seed=0, a=1.0, curve=0.15, **_):
    """弧形箭头：发光金线 + 实心箭头"""
    if p <= 0:
        return
    _glow_line(c, K.curve_path(x0, y0, x1, y1, curve), e_io(clamp(p)), color, 5, a)
    if p > 0.85:
        K.arrow_head(c, x1, y1, K.head_angle(x0, y0, x1, y1, curve), 28, color or GOLD, a * clamp((p - 0.85) * 6))


def hcheck(c, x, y, s, p=1.0, color=None, seed=0, a=1.0, **_):
    """勾：绿色圆标白勾"""
    lib.check(c, x, y, s * 0.56, p, color or OK, a)


def hcross(c, x, y, s, p=1.0, color=None, seed=0, a=1.0, **_):
    """叉：红色圆标白叉"""
    lib.cross(c, x, y, s * 0.56, p, color or NO, a)


def marker(c, x0, x1, y, h, p=1.0, color=None, a=0.85, seed=0):
    """高亮：一条半透明的黄色荧光带从左往右铺（画在字下面）"""
    if p <= 0:
        return
    xe = lerp(x0, x1, e_out(p))
    clr = color or HILITE
    c.drawRRect(rrect(x0, y - h / 2, max(h * 0.2, xe - x0), h, 6), paint(clr, a * 0.32))
    c.drawRect(skia.Rect.MakeLTRB(x0, y + h / 2 - 5, xe, y + h / 2), paint(clr, a * 0.9))


def squiggle(c, x, y, w, p=1.0, color=None, seed=0, a=1.0, **_):
    """占位的字：几段暗蓝灰的圆头条"""
    rng = np.random.default_rng(seed + 3)
    xs, cx = [], x
    while cx < x + w - 30:
        L_ = min(rng.uniform(60, 180), x + w - cx)
        xs.append((cx, L_))
        cx += L_ + rng.uniform(12, 22)
    xe = x + w * e_out(clamp(p))
    for sx, L_ in xs:
        if sx >= xe:
            break
        c.drawRRect(rrect(sx, y - 5, min(L_, xe - sx), 10, 5), paint(color or (52, 64, 90), a))


def hline(c, x0, y0, x1, y1, p=1.0, color=None, seed=0, a=1.0, **_):
    """细金线，两头小圆点"""
    if p <= 0:
        return
    path = skia.Path()
    path.moveTo(x0, y0); path.lineTo(x1, y1)
    _glow_line(c, path, e_out(clamp(p)), color, 2, a * 0.85)
    c.drawCircle(x0, y0, 5, paint(color or GOLD, a))
    if p >= 1:
        c.drawCircle(x1, y1, 5, paint(color or GOLD, a))


# ======================================================================
# 卡片、照片
# ======================================================================

def sheet(c, x, y, w, h, t, t0, seed=0, rot=0.0, layers=1, a=1.0, fill=None, **_):
    """卡片：深色玻璃卡 + 细金边 + 顶上一道高光，浮上来。layers = 后面再叠几张"""
    q = prog(t, t0, 0.4)
    if q <= 0:
        return
    e = e_out(q)
    with xf(c, x + w / 2, y + h / 2, lerp(0.95, 1.0, e), a=a * clamp(q * 2.5), dy=(1 - e) * 30):
        for k in range(layers - 1, 0, -1):
            rr = rrect(x + 16 * k, y - 14 * k, w, h, 16)
            c.drawRRect(rr, paint((14, 20, 34), 0.9))
            c.drawRRect(rr, paint(GOLD, 0.25, stroke=1.2))
        c.drawRRect(rrect(x, y + 14, w, h, 16), paint((0, 0, 0), 0.55, blur=20))
        rr = rrect(x, y, w, h, 16)
        c.drawRRect(rr, K.lin(0, y, 0, y + h, [fill or (28, 38, 62), mix(fill or (28, 38, 62), (0, 0, 0), 0.45)], None, 0.94))
        c.drawRRect(rr, paint(GOLD, 0.6, stroke=1.6))
        c.drawLine(x + 24, y + 1.5, x + w - 24, y + 1.5,
                   K.lin(x, 0, x + w, 0, [(255, 255, 255, 0.0), (255, 255, 255, 0.35), (255, 255, 255, 0.0)]))


def photo(c, img, x, y, w, h, t, t0, rot=0.0, seed=0, caption=None, focus=(0.5, 0.5), push=0.05, a=1.0, **_):
    """照片：白色新闻卡里的图，左下角一个红色来源标签（caption）；从下面浮上来，落定后图在框里慢推"""
    q = prog(t, t0, 0.45)
    if q <= 0 or img is None:
        return
    e = e_out(q)
    pad = 12
    with xf(c, x + w / 2, y + h / 2, lerp(0.94, 1.0, e), rot=rot * 0.3, a=a * clamp(q * 2.5), dy=(1 - e) * 40):
        c.drawRRect(rrect(x, y + 16, w, h, 10), paint((0, 0, 0), 0.6, blur=22))
        c.drawRRect(rrect(x, y, w, h, 10), paint(CARD))
        K.cover(c, img, x + pad, y + pad, w - 2 * pad, h - 2 * pad, t, t0, focus, push, r=6)
        if caption:
            cs = 24
            cw = text_w(caption, cs, 'hand') + 30
            ch = cs * 1.7
            cx_, cy_ = x + pad + 14, y + h - pad - 14 - ch
            c.drawRect(skia.Rect.MakeXYWH(cx_, cy_, cw, ch), paint(SRC_RED))
            text(c, caption, cx_ + cw / 2, cy_ + ch / 2, cs, WHITE, 'hand', 'c')


# ======================================================================
# 字幕、人物小窗
# ======================================================================

def sub(c, s, x, y, size, maxw):
    """字幕：白色特粗字 + 深色投影，不垫底"""
    w = text_w(s, size, 'sub')
    if w > maxw:
        size = size * maxw / w
    K.ptext(c, s, x, y + 4, size, paint((0, 0, 0), 0.9, blur=7), 'sub', 'c')
    K.ptext(c, s, x, y + 2, size, paint((0, 0, 0), 0.8, stroke=size * 0.08), 'sub', 'c')
    text(c, s, x, y, size, TXT, 'sub', 'c')


def pip_frame(c, x, y, w, h, r, a):
    """人物小窗：细金边 + 外面一圈深色"""
    if a <= 0.01:
        return
    c.drawRRect(rrect(x - 3, y - 3, w + 6, h + 6, r + 3), paint((0, 0, 0), a * 0.6, stroke=4))
    c.drawRRect(rrect(x, y, w, h, r), paint(GOLD, a * 0.85, stroke=2.5))


# ======================================================================
# 转场
# ======================================================================

def _tr_whip(c, A, B, x, fidx):
    """甩镜头：整页往左一甩，强烈的横向拖影，下一页甩进来"""
    e = e_io(x)
    k = math.sin(math.pi * x)
    c.clear(col(NAVY1))
    p = K.bp(90 * k, 0)
    K.di(c, A, -e * W, 0, p)
    K.di(c, B, (1 - e) * W, 0, p)


TRANSITIONS = {'whip': _tr_whip}
