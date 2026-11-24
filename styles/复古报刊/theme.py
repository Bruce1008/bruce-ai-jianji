"""复古报刊：白报纸、藏青和报纸红两种油墨；标题是压窄的特粗宋体 + 粗细两道横线（报头），正文像打字机一个字一个字打出来；
重点词是带白边的红 / 藏青色块；照片是黑白新闻照 + 图注；改稿用红笔圈、勾、叉；结论盖一个红色审稿章。
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
PAPER = (253, 253, 251)       # 报纸白
NAVY = (29, 61, 138)          # 藏青：标题、报头、粗线
SEA0, SEA1 = (33, 80, 143), (23, 47, 92)
PURPLE = (94, 116, 165)       # 紫蓝：副线、小字
LIGHT = (207, 214, 238)       # 浅蓝：高亮、网点
RED = (187, 54, 51)           # 报纸红：栏目标签、改稿红笔、印章
GRAY = (115, 117, 116)        # 灰：图注、引线
BODY = (26, 26, 26)           # 正文黑
RULE = (206, 206, 208)        # 细分隔线
INK = BODY
ACCENT, ACCENT2, MUTE = RED, NAVY, GRAY
lib.use_palette(INK=BODY, SUBINK=GRAY, MUTE=GRAY, LINE=RULE, BG=PAPER, ACC=RED, ACC2=NAVY)

# ---------- 字体：标题思源宋体特粗（压窄）、正文思源黑体、数字英文 Playfair Display ----------
COND = 0.82                   # 标题压窄
lib.use_kinds(hand=('noto_sans_sc', 500, 0.36), round=('noto_serif_sc', 900, 0.36), sub=('noto_sans_sc', 700, 0.36),
              num=('noto_serif_sc', 900, 0.36), en=('playfair', 700, 0.35),
              cn=('noto_sans_sc', 500, 0.36), cn_med=('noto_sans_sc', 500, 0.36), cn_reg=('noto_sans_sc', 400, 0.36),
              cn_black=('noto_serif_sc', 900, 0.36))

# ---------- 转场、音效 ----------
lib.DEFAULT_TR = 'paper'
ALT_TR = 'dive'               # 换话题时用的第二种转场：scenes.py 里写 tr=T.ALT_TR
lib.TR_D.update(paper=0.55, dive=0.55)
SFX = {'write': ('typing', -2, {'d': 0.9}), 'drop': ('paper_drop', -6), 'pop': ('click', -4), 'mark': ('pencil', -4),
       'stamp': ('stamp', 0), 'stick': ('snip', -6), 'tick': ('pencil', -6), 'number': ('click', -2),
       'whoosh': ('paper_slide', -6)}
TR_SFX = {'paper': [(-0.3, 'page_flip', -4)], 'dive': [(-0.3, 'deep_whoosh', -6)]}


def _left():
    import layout as L
    return 60 if lib.VERTICAL else L.PIP_SAFE[2] + 40


def _reveal(c, x, y, w, h, p):
    """从左往右露出来（印刷那种一下一下推出来的感觉）"""
    c.save()
    c.clipRect(skia.Rect.MakeXYWH(x, y, w * e_out(clamp(p)), h))


# ======================================================================
# 背景：报纸白 + 纸纹 + 角上一块网点 + 报头
# ======================================================================

@functools.lru_cache(2)
def _halftone(vertical):
    """右下角一块淡蓝网点（离角越远点越小）"""
    pts = []
    step = 22
    ox, oy = (W, H)
    for gx in range(0, 520, step):
        for gy in range(0, 420, step):
            d = math.hypot(gx, gy) / 520
            r = (1 - d) * step * 0.42
            if r > 1:
                pts.append((ox - gx - (gy // step % 2) * step / 2, oy - gy, r))
    return pts


def paper(c, t, head=None, dots=True):
    """铺底。head = 报头里的栏目名（这一段讲什么，可以不给）；没给时只画顶上的粗细两道线"""
    c.clear(col(PAPER))
    K.grain(c, t, 0.028, light=False, fps=6)
    if dots:
        for x, y, r in _halftone(lib.VERTICAL):
            c.drawCircle(x, y, r, paint(LIGHT, 0.7))
    x0 = 60 if lib.VERTICAL else _left()
    x1 = W - 60
    if head:
        y0 = 84 if lib.VERTICAL else 76
        K.ptext(c, head, x0, y0, 46, paint(NAVY), 'round', 'l', scale_x=COND)
        text(c, K.today_cn(), x1, y0 + 4, 22, GRAY, 'hand', 'r')
        ry = y0 + 42
    else:
        ry = 60
    c.drawRect(skia.Rect.MakeLTRB(x0, ry, x1, ry + 5), paint(NAVY))
    c.drawRect(skia.Rect.MakeLTRB(x0, ry + 10, x1, ry + 11.5), paint(NAVY))


# ======================================================================
# 字
# ======================================================================

def title(c, s, x, y, size, t, t0, sub_en=None, color=None, a=1.0, seed=0):
    """大标题：压窄的特粗宋体藏青字，从左往右印出来；上面一行红色小英文，下面粗细两道线往两边拉开"""
    q = prog(t, t0, 0.5)
    if q <= 0:
        return
    tw = text_w(s, size, 'round') * COND
    with xf(c, x, y, a=a):
        _reveal(c, x - tw / 2 - 10, y - size, tw + 20, size * 2, q)
        K.ptext(c, s, x, y, size, paint(color or NAVY), 'round', 'c', scale_x=COND)
        c.restore()
        ql = e_out(prog(t, t0 + 0.25, 0.5))
        hw = (tw / 2 + size * 0.4) * ql
        ly = y + size * 0.72
        if ql > 0:
            c.drawRect(skia.Rect.MakeLTRB(x - hw, ly, x + hw, ly + max(4, size * 0.045)), paint(color or NAVY))
            c.drawRect(skia.Rect.MakeLTRB(x - hw, ly + size * 0.085, x + hw, ly + size * 0.085 + 1.6), paint(color or NAVY))
        if sub_en:
            qe = prog(t, t0 + 0.15, 0.4)
            K.ptext(c, sub_en.upper(), x, y - size * 0.86, size * 0.19, paint(RED, qe), 'en', 'c', track=0.3)


def tag(c, label, x, y, size, t, t0, color=None, fg=None, a=1.0, seed=0):
    """栏目标签：方角红底白字，从左往右露出来。返回宽度"""
    tw = text_w(label, size, 'sub')
    h = size * 1.5
    w = tw + size * 0.9
    if a <= 0:                 # a=0：只量宽度不画
        return w
    q = prog(t, t0, 0.3)
    if q > 0:
        with xf(c, x, y, a=a):
            _reveal(c, x, y - h / 2, w, h, q)
            c.drawRect(skia.Rect.MakeXYWH(x, y - h / 2, w, h), paint(color or RED))
            text(c, label, x + w / 2, y, size, fg or WHITE, 'sub', 'c')
            c.restore()
    return w


def write(c, s, x, y, size, t, t0, cps=9.0, color=None, kind='hand', align='l', a=1.0, pen_on=False, **_):
    """打字机：一个字一个字打出来，打字时后面跟一条藏青光标。返回出到的位置 (x, y)"""
    total, end = K.chars(c, s, x, y, size, t, t0, cps * 1.3, color or BODY, kind, align, a, mode='type')
    dur, d = len(s) / (cps * 1.3), t - t0
    if 0 <= d < dur + 0.6 and (d < dur or int(d * 4) % 2 == 0):           # 打字时一直在，打完闪两下
        c.drawRect(skia.Rect.MakeXYWH(end + 3, y - size * 0.5, max(3, size * 0.06), size), paint(NAVY, a))
    return (end, y)


def write_d(s, cps=9.0):
    return len(s) / (cps * 1.3)


def block_word(c, s, x, y, size, t, t0, color=None, fg=None, align='c', a=1.0, seed=0, **_):
    """重点词：带白边的色块（默认报纸红；第二个重点 color=T.ACCENT2 藏青）里的白色宋体字，从左往右印出来。返回宽度"""
    tw = text_w(s, size, 'round')
    w, h = tw + size * 0.6, size * 1.36
    bx = x - w / 2 if align == 'c' else (x if align == 'l' else x - w)
    if a <= 0:                 # a=0：只量宽度不画
        return w
    q = prog(t, t0, 0.3)
    if q > 0:
        with xf(c, bx + w / 2, y, a=a):
            _reveal(c, bx - 4, y - h, w + 8, h * 2, q)
            c.drawRect(skia.Rect.MakeXYWH(bx, y - h / 2, w, h), paint(color or ACCENT))
            c.drawRect(skia.Rect.MakeXYWH(bx + 5, y - h / 2 + 5, w - 10, h - 10), paint(WHITE, 0.9, stroke=2))
            text(c, s, bx + w / 2, y, size, fg or WHITE, 'round', 'c')
            c.restore()
    return w


def number(c, s, unit, x, y, size, t, t0, color=None, align='c', a=1.0, seed=0):
    """大数字 + 单位：藏青色的压窄衬线数字，从 0 数上去，从下往上印出来。返回总宽；a=0 只量宽度"""
    nw = text_w(s, size, 'num') * 0.88
    us = size * 0.38
    gap = size * 0.1
    uw = text_w(unit, us, 'round') * COND if unit else 0
    w = nw + (gap + uw if unit else 0)
    if a <= 0:
        return w
    q = prog(t, t0, 0.4)
    if q <= 0:
        return w
    bx = x - w / 2 if align == 'c' else (x if align == 'l' else x - w)
    s_ = K.count(s, prog(t, t0, 0.8))
    e = e_out(q)
    c.save()
    c.clipRect(skia.Rect.MakeLTRB(bx - 20, y + size * 0.6 - size * 1.4 * e, bx + w + 20, y + size * 0.6))
    K.ptext(c, s_, bx + nw, y, size, paint(color or NAVY, a), 'num', 'r', scale_x=0.88)
    if unit:
        K.ptext(c, unit, bx + nw + gap, y + size * 0.2, us, paint(color or NAVY, a), 'round', 'l', scale_x=COND)
    c.restore()
    return w


def mark(c, s, x, y, size, t, t0, color=None, rot=8, a=1.0):
    """大号标点：红色宋体，像盖上去一样一下落定"""
    q = prog(t, t0, 0.18)
    if q <= 0:
        return
    with xf(c, x, y, lerp(1.35, 1.0, e_in(q)), rot=rot, a=a * clamp(q * 3)):
        text(c, s, x, y, size, color or RED, 'round', 'c')


def stamp(c, s, cx, cy, size, t, t0, color=None, rot=-7, a=1.0, seed=0):
    """结论：红色审稿章（双线框、空心），砸下来震一下，油墨有点不匀"""
    tw = text_w(s, size, 'round') * COND
    w, h = tw + size * 0.9, size * 1.55
    d = t - t0
    if d <= 0:
        return
    q = clamp(d / 0.2)
    dx, dy = shake(t, t0 + 0.2, 0.22, 5)
    clr = color or RED
    with xf(c, cx, cy, lerp(1.5, 1.0, e_in(q)), rot=rot, a=a * clamp(q * 3) * 0.92, dx=dx, dy=dy):
        c.saveLayer(skia.Rect.MakeXYWH(cx - w, cy - h, w * 2, h * 2), None)
        c.drawRect(skia.Rect.MakeXYWH(cx - w / 2, cy - h / 2, w, h), paint(clr, 1, stroke=6))
        c.drawRect(skia.Rect.MakeXYWH(cx - w / 2 + 10, cy - h / 2 + 10, w - 20, h - 20), paint(clr, 1, stroke=2))
        K.ptext(c, s, cx, cy, size, paint(clr), 'round', 'c', scale_x=COND)
        p = skia.Paint()                                     # 油墨不匀：用颗粒擦掉一点
        p.setBlendMode(skia.BlendMode.kDstOut)
        c.saveLayer(skia.Rect.MakeXYWH(cx - w, cy - h, w * 2, h * 2), p)
        K.grain(c, seed + 3, 0.3, n=128, seed=seed + 9, fps=1, light=False,
                rect=skia.Rect.MakeXYWH(cx - w, cy - h, w * 2, h * 2))
        c.restore()
        c.restore()


# ======================================================================
# 线和标记（改稿红笔、引线）
# ======================================================================

def _pen(c, path, p, color=None, w=5, a=1.0):
    K.stroke_path(c, path, p, color or RED, w, a)


def hunder(c, x0, x1, y, p=1.0, color=None, seed=0, a=1.0, **_):
    """下划线：红笔划一道，略往上翘"""
    path = skia.Path()
    path.moveTo(x0, y + 2); path.quadTo((x0 + x1) / 2, y + 5, x1, y - 4)
    _pen(c, path, e_out(clamp(p)), color, 5, a)


def hcircle(c, cx, cy, rx, ry=None, p=1.0, color=None, seed=0, a=1.0, **_):
    """圈出来：红笔歪着圈一圈"""
    with xf(c, cx, cy, rot=-4):
        _pen(c, K.ellipse_path(cx, cy, rx, ry or rx, -110, 360), e_io(clamp(p)), color, 5, a)


def harrow(c, x0, y0, x1, y1, p=1.0, color=None, seed=0, a=1.0, curve=0.15, **_):
    """引线箭头：尾巴一个小圆点，细线，实心小箭头（藏青）"""
    if p <= 0:
        return
    clr = color or NAVY
    c.drawCircle(x0, y0, 6, paint(clr, a))
    K.stroke_path(c, K.curve_path(x0, y0, x1, y1, curve * 0.6), e_io(clamp(p)), clr, 2.5, a)
    if p > 0.85:
        K.arrow_head(c, x1, y1, K.head_angle(x0, y0, x1, y1, curve * 0.6), 20, clr, a * clamp((p - 0.85) * 6))


def hcheck(c, x, y, s, p=1.0, color=None, seed=0, a=1.0, **_):
    """勾：红笔打个勾"""
    path = skia.Path()
    path.moveTo(x - s * 0.36, y); path.lineTo(x - s * 0.08, y + s * 0.3); path.lineTo(x + s * 0.42, y - s * 0.38)
    _pen(c, path, e_out(clamp(p)), color, max(4, s * 0.13), a)


def hcross(c, x, y, s, p=1.0, color=None, seed=0, a=1.0, **_):
    k = s * 0.3
    for i, (ax, ay, bx, by) in enumerate(((-k, -k, k, k), (k, -k, -k, k))):
        path = skia.Path()
        path.moveTo(x + ax, y + ay); path.lineTo(x + bx, y + by)
        _pen(c, path, clamp(p * 2 - i), color, max(4, s * 0.13), a)


def marker(c, x0, x1, y, h, p=1.0, color=None, a=0.9, seed=0):
    """高亮：浅蓝色平涂，从左往右铺（画在字下面）"""
    if p <= 0:
        return
    xe = lerp(x0, x1, e_out(p))
    c.drawRect(skia.Rect.MakeLTRB(x0, y - h / 2, xe, y + h / 2), paint(color or LIGHT, a))


def squiggle(c, x, y, w, p=1.0, color=None, seed=0, a=1.0, **_):
    """占位的字：一行灰色的「正文」短条（像报纸上一行小字）"""
    rng = np.random.default_rng(seed + 3)
    xs, cx = [], x
    while cx < x + w - 20:
        L_ = min(rng.uniform(26, 90), x + w - cx)
        xs.append((cx, L_))
        cx += L_ + rng.uniform(8, 12)
    xe = x + w * e_out(clamp(p))
    for sx, L_ in xs:
        if sx >= xe:
            break
        c.drawRect(skia.Rect.MakeXYWH(sx, y - 4, min(L_, xe - sx), 8), paint(color or (185, 186, 188), a))


def hline(c, x0, y0, x1, y1, p=1.0, color=None, seed=0, a=1.0, **_):
    """引线：灰色细线，两头小圆点"""
    if p <= 0:
        return
    xe, ye = lerp(x0, x1, e_out(p)), lerp(y0, y1, e_out(p))
    c.drawLine(x0, y0, xe, ye, paint(color or GRAY, a, stroke=2))
    c.drawCircle(x0, y0, 5, paint(color or GRAY, a))
    if p >= 1:
        c.drawCircle(x1, y1, 5, paint(color or GRAY, a))


# ======================================================================
# 卡片、照片
# ======================================================================

def _soft_shadow(c, x, y, w, h, a=1.0):
    c.drawRect(skia.Rect.MakeXYWH(x + 6, y + 10, w, h), paint((0, 0, 0), 0.16 * a, blur=14))


def sheet(c, x, y, w, h, t, t0, seed=0, rot=0.0, layers=1, a=1.0, fill=None, **_):
    """卡片：剪下来的一块报纸（白、细灰边、顶上粗细两道藏青线、一点投影），落下来。layers = 底下再压几张"""
    q = prog(t, t0, 0.35)
    if q <= 0:
        return
    e = e_out(q)
    with xf(c, x + w / 2, y + h / 2, lerp(1.05, 1.0, e), rot=rot * 0.6, a=a * clamp(q * 3)):
        for k in range(layers - 1, 0, -1):
            r = (-2.5 if k % 2 else 2) * k
            with xf(c, x + w / 2, y + h / 2, rot=r):
                _soft_shadow(c, x, y, w, h)
                c.drawRect(skia.Rect.MakeXYWH(x, y, w, h), paint((246, 245, 240)))
                c.drawRect(skia.Rect.MakeXYWH(x, y, w, h), paint(RULE, 1, stroke=1.5))
        _soft_shadow(c, x, y, w, h)
        c.drawRect(skia.Rect.MakeXYWH(x, y, w, h), paint(fill or WHITE))
        c.drawRect(skia.Rect.MakeXYWH(x, y, w, h), paint(RULE, 1, stroke=1.5))
        c.drawRect(skia.Rect.MakeXYWH(x + 24, y + 20, w - 48, 4), paint(NAVY))
        c.drawRect(skia.Rect.MakeXYWH(x + 24, y + 28, w - 48, 1.4), paint(NAVY))


_GRAY_CF = skia.ColorFilters.Matrix([0.33, 0.55, 0.12, 0, -0.02,
                                     0.33, 0.55, 0.12, 0, -0.01,
                                     0.31, 0.52, 0.12, 0, 0.02,
                                     0, 0, 0, 1, 0])


def photo(c, img, x, y, w, h, t, t0, rot=0.0, seed=0, caption=None, focus=(0.5, 0.5), push=0.05, a=1.0, **_):
    """照片：白卡上的黑白新闻照（细黑框），下面一行图注；落下来，落定后照片在框里慢推"""
    q = prog(t, t0, 0.4)
    if q <= 0 or img is None:
        return
    e = e_out(q)
    pad = 16
    bot = 56 if caption else pad
    with xf(c, x + w / 2, y + h / 2, lerp(1.05, 1.0, e), rot=rot * 0.5, a=a * clamp(q * 3)):
        _soft_shadow(c, x, y, w, h)
        c.drawRect(skia.Rect.MakeXYWH(x, y, w, h), paint(WHITE))
        c.drawRect(skia.Rect.MakeXYWH(x, y, w, h), paint(RULE, 1, stroke=1.5))
        ix, iy, iw, ih = x + pad, y + pad, w - 2 * pad, h - pad - bot
        gp = skia.Paint()
        gp.setColorFilter(_GRAY_CF)
        c.saveLayer(skia.Rect.MakeXYWH(ix, iy, iw, ih), gp)
        K.cover(c, img, ix, iy, iw, ih, t, t0, focus, push)
        c.restore()
        c.drawRect(skia.Rect.MakeXYWH(ix, iy, iw, ih), paint(BODY, 1, stroke=1.5))
        if caption:
            cy_ = y + h - bot / 2
            c.drawRect(skia.Rect.MakeXYWH(ix, cy_ - 8, 16, 16), paint(RED))
            text(c, caption, ix + 28, cy_, 24, GRAY, 'hand', 'l')


# ======================================================================
# 字幕、人物小窗
# ======================================================================

def sub(c, s, x, y, size, maxw):
    """字幕：白条 + 上面一道藏青粗线，黑字"""
    w = text_w(s, size, 'sub')
    if w > maxw:
        size = size * maxw / w
        w = maxw
    pad, h = size * 0.7, size * 1.6
    rx = x - w / 2 - pad
    c.drawRect(skia.Rect.MakeXYWH(rx + 4, y - h / 2 + 6, w + 2 * pad, h), paint((0, 0, 0), 0.12, blur=8))
    c.drawRect(skia.Rect.MakeXYWH(rx, y - h / 2, w + 2 * pad, h), paint(WHITE, 0.97))
    c.drawRect(skia.Rect.MakeXYWH(rx, y - h / 2, w + 2 * pad, 5), paint(NAVY))
    text(c, s, x, y + 3, size, BODY, 'sub', 'c')


def pip_frame(c, x, y, w, h, r, a):
    """人物小窗：白边 + 细黑框，像报纸上的人物小照"""
    if a <= 0.01:
        return
    c.drawRRect(rrect(x + 4, y + 4, w - 8, h - 8, max(0, r - 4)), paint(WHITE, a, stroke=9))
    c.drawRRect(rrect(x - 1, y - 1, w + 2, h + 2, r + 1), paint(BODY, a * 0.85, stroke=2))


# ======================================================================
# 转场
# ======================================================================

def _tr_paper(c, A, B, x, fidx):
    """换一张报纸：下一页从右边盖上来（带一点倾斜和投影），上一页稍稍变暗"""
    e = e_io(x)
    K.di(c, A)
    c.drawRect(skia.Rect.MakeWH(W, H), paint((0, 0, 0), 0.12 * e))
    ox = (1 - e) * W * 1.02
    c.save()
    c.translate(ox, 0)
    c.rotate(3 * (1 - e), W / 2, H)
    c.drawRect(skia.Rect.MakeXYWH(-18, 10, 30, H), paint((0, 0, 0), 0.22 * (1 - e) + 0.05, blur=18))
    K.di(c, B)
    c.restore()


def _tr_dive(c, A, B, x, fidx):
    """钻进去：上一页往里冲、变淡，下一页从远处迎上来"""
    e = e_io(x)
    c.clear(col(PAPER))
    K.di(c, A, p=K.bp(0, 0, 1 - e_in(clamp(x * 1.5))), s=1 + 0.5 * e)
    K.di(c, B, p=K.bp(0, 0, e_out(clamp(x * 1.6 - 0.4))), s=0.82 + 0.18 * e)


TRANSITIONS = {'paper': _tr_paper, 'dive': _tr_dive}
