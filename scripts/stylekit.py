"""风格共用的小工具：给 styles/<风格>/theme.py 用（scenes.py 不直接用它）。

每个风格都要提供同一套部件（名字、参数一样，长相各不同），见 styles/部件.md。这里放大家都要的底层：
镜头慢推、震动、视频帧、图片铺满慢推、渐变画笔、渐变字、逐字出现、颗粒、暗角、转场用的画图函数。
"""
import math, functools
from contextlib import contextmanager
import numpy as np
import skia
import lib
from lib import clamp, prog, e_out, e_in, e_io, e_back, lerp, paint, col, text, text_w, xf, W, H, CX, CY


# ---------- 镜头 ----------
@contextmanager
def cam(c, t, t0, amt=0.04, dur=7.0, cx=None, cy=None):
    """整页慢推：1.0 → 1+amt（dur 秒推完）。背景画在 with 外面"""
    s = 1 + amt * e_io(clamp((t - t0) / dur))
    with xf(c, CX if cx is None else cx, CY if cy is None else cy, s):
        yield


def shake(t, t0, d=0.2, amp=7.0):
    """砸下那一下的震动 -> (dx, dy)"""
    x = (t - t0) / d
    if x < 0 or x > 1:
        return 0.0, 0.0
    k = (1 - x) * amp
    return k * math.sin(x * 37.0), k * math.cos(x * 29.0) * 0.6


# ---------- 图 ----------
def clip_img(S, key, path, src, t, w, h, speed=1.0):
    """视频素材的当前帧（skia.Image），交给 photo 显示。src = 从原片第几秒开始放"""
    return S.clip(key, path, src, speed, S.t0, size=(int(w), int(h))).get(t)


def as_img(img):
    return lib.load_img(img) if isinstance(img, str) else img


def cover(c, img, x, y, w, h, t, t0, focus=(0.5, 0.5), push=0.05, r=0, a=1.0):
    """图片铺满框，落定后 7 秒里慢慢推近 push"""
    zoom = 1 + push * e_io(clamp((t - t0) / 7.0))
    lib.img_cover(c, as_img(img), x, y, w, h, a=a, r=r, focus=focus, zoom=zoom)


# ---------- 渐变 ----------
def _cols(colors):
    return [col(c_[:3], c_[3] if len(c_) > 3 else 1.0) for c_ in colors]


def lin(x0, y0, x1, y1, colors, pos=None, a=1.0):
    """线性渐变画笔。colors = [(r,g,b) 或 (r,g,b,alpha), …]"""
    p = skia.Paint(AntiAlias=True)
    p.setShader(skia.GradientShader.MakeLinear([skia.Point(x0, y0), skia.Point(x1, y1)], _cols(colors), pos,
                                               skia.TileMode.kClamp))
    p.setAlphaf(clamp(a))
    return p


def radial(cx, cy, r, colors, pos=None, a=1.0):
    p = skia.Paint(AntiAlias=True)
    p.setShader(skia.GradientShader.MakeRadial(skia.Point(cx, cy), max(r, 1), _cols(colors), pos, skia.TileMode.kClamp))
    p.setAlphaf(clamp(a))
    return p


def ptext(c, s, x, y, size, p, kind='cn', align='c', track=0.0, scale_x=1.0):
    """用任意画笔（渐变、描边、模糊）写一行字，y 是垂直中心。scale_x < 1 把字压窄（报纸标题）。返回宽度"""
    w = (text_w(s, size, kind) + (len(s) - 1) * track * size) * scale_x if s else 0
    if not s:
        return 0
    bx = x - w / 2 if align == 'c' else (x if align == 'l' else x - w)
    by = y + size * lib.KINDS[kind][2]
    c.save()
    c.translate(bx, by)
    if scale_x != 1.0:
        c.scale(scale_x, 1.0)
    cx = 0.0
    for r, fb in lib._runs(s, kind):
        f = lib.font(kind, size, fb)
        if track:
            for ch in r:
                c.drawString(ch, cx, 0, f, p)
                cx += f.measureText(ch) + track * size
        else:
            c.drawString(r, cx, 0, f, p)
            cx += f.measureText(r)
    c.restore()
    return w


def grad_text(c, s, x, y, size, colors, kind='cn', align='c', a=1.0, track=0.0, scale_x=1.0, pos=None):
    """上下渐变的字（金字、银字）"""
    p = lin(0, y - size * 0.55, 0, y + size * 0.45, colors, pos, a)
    return ptext(c, s, x, y, size, p, kind, align, track, scale_x)


# ---------- 逐字出现 ----------
def chars(c, s, x, y, size, t, t0, cps=9.0, color=None, kind='cn', align='l', a=1.0, mode='fade', slots=2.5,
          draw=None):
    """一个字一个字出来。mode：fade（淡入 + 上浮）、blur（由虚到实）、type（直接出现）、pop（弹出）。
    slots = 每个字用几个字的时间出完（越大越柔）。draw(c, ch, x, y, a) 自定义怎么画一个字（默认 text）。
    返回 (总宽, 出到哪里的 x)"""
    total = text_w(s, size, kind)
    bx = x - total / 2 if align == 'c' else (x if align == 'l' else x - total)
    done = (t - t0) * cps
    cx, end = bx, bx
    if done <= 0:
        return total, bx
    for i, ch in enumerate(s):
        cw = text_w(ch, size, kind)
        q = clamp((done - i) / (1.0 if mode == 'type' else slots))
        if q <= 0:
            break
        e = e_out(q)
        pen_ = draw or (lambda c_, ch_, x_, y_, a_: text(c_, ch_, x_, y_, size, color, kind, 'l', a_))
        if mode == 'type' or q >= 1:
            pen_(c, ch, cx, y, a)
        elif mode == 'fade':
            with xf(c, cx + cw / 2, y, dy=(1 - e) * size * 0.28):
                pen_(c, ch, cx, y, a * e)
        elif mode == 'blur':
            with lib.blurred(c, (1 - e) * size * 0.16, a * e, bounds=(cx - 4, y - size, cw + 8, size * 2)):
                pen_(c, ch, cx, y, 1.0)
        elif mode == 'pop':
            with xf(c, cx + cw / 2, y, lerp(0.4, 1.0, e_back(q)), a=a * clamp(q * 3)):
                pen_(c, ch, cx, y, 1.0)
        cx += cw
        end = cx
    return total, end


def count(s, p):
    """数字从 0 数到 s（s 是 '10'、'3.5'、'1,200' 这类）；不是数字就原样返回"""
    raw = s.replace(',', '')
    try:
        v = float(raw)
    except ValueError:
        return s
    dec = len(raw.split('.')[1]) if '.' in raw else 0
    cur = v * e_out(clamp(p))
    out = f'{cur:,.{dec}f}' if ',' in s else f'{cur:.{dec}f}'
    return out


# ---------- 质感 ----------
@functools.lru_cache(16)
def _noise_tile(n, seed, amt, light):
    rng = np.random.default_rng(seed)
    v = rng.normal(0, 1, (n, n)).astype(np.float32)
    a = np.clip(np.abs(v) * amt * 255, 0, 255).astype(np.uint8)
    arr = np.zeros((n, n, 4), np.uint8)
    arr[..., :3] = 255 if light else 0
    arr[..., 3] = a
    arr[..., :3] = (arr[..., :3].astype(np.float32) * (a[..., None] / 255.0)).astype(np.uint8)   # 预乘
    return skia.Image.fromarray(arr, colorType=skia.ColorType.kRGBA_8888_ColorType)


def grain(c, t, amt=0.05, n=256, seed=5, fps=12, light=True, rect=None):
    """胶片颗粒：每秒换 fps 次位置"""
    k = int(t * fps)
    rng = np.random.default_rng(k)
    m = skia.Matrix.Translate(float(rng.uniform(0, n)), float(rng.uniform(0, n)))
    p = skia.Paint()
    p.setShader(_noise_tile(n, seed, amt, light).makeShader(skia.TileMode.kRepeat, skia.TileMode.kRepeat, lib.SAMP, m))
    c.drawRect(rect or skia.Rect.MakeWH(W, H), p)


def vignette(c, a=0.55, color=(0, 0, 0), inner=0.45):
    r = math.hypot(W, H) / 2
    c.drawRect(skia.Rect.MakeWH(W, H), radial(CX, CY, r, [color + (0.0,), color + (0.0,), color + (a,)], [0, inner, 1]))


def glow(c, cx, cy, r, color, a=0.5):
    c.drawCircle(cx, cy, r, radial(cx, cy, r, [tuple(color) + (a,), tuple(color) + (0.0,)]))


def stroke_path(c, path, p, color, w, a=1.0, cap=True, blur=None):
    """把 path 画出 p（0..1）"""
    if p <= 0:
        return
    pp = lib.partial_path(path, p) if p < 1 else path
    pt = paint(color, a, stroke=w, blur=blur)
    if cap:
        pt.setStrokeCap(skia.Paint.kRound_Cap)
        pt.setStrokeJoin(skia.Paint.kRound_Join)
    c.drawPath(pp, pt)


def ellipse_path(cx, cy, rx, ry, start=-100, sweep=360):
    path = skia.Path()
    sweep = max(-359.9, min(359.9, sweep))          # 正好 360 度 skia 会给空路径
    path.addArc(skia.Rect.MakeLTRB(cx - rx, cy - ry, cx + rx, cy + ry), start, sweep)
    return path


def curve_path(x0, y0, x1, y1, curve=0.15):
    """两点间的弧线（curve = 弯的程度，正负决定往哪边弯）"""
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = x1 - x0, y1 - y0
    path = skia.Path()
    path.moveTo(x0, y0)
    path.quadTo(mx - dy * curve, my + dx * curve, x1, y1)
    return path


def head_angle(x0, y0, x1, y1, curve=0.15):
    """弧线末端的方向（度）"""
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = x1 - x0, y1 - y0
    qx, qy = mx - dy * curve, my + dx * curve
    return math.degrees(math.atan2(y1 - qy, x1 - qx))


def arrow_head(c, x, y, ang, size, color, a=1.0, fill=True, w=4):
    path = skia.Path()
    path.moveTo(0, 0)
    path.lineTo(-size, -size * 0.55)
    if fill:
        path.lineTo(-size * 0.7, 0)
    path.lineTo(-size, size * 0.55)
    if fill:
        path.close()
    c.save()
    c.translate(x, y)
    c.rotate(ang)
    pt = paint(color, a) if fill else paint(color, a, stroke=w)
    if not fill:
        pt.setStrokeCap(skia.Paint.kRound_Cap)
    c.drawPath(path, pt)
    c.restore()


# ---------- 转场 ----------
def bp(sx=0.0, sy=0.0, a=1.0):
    p = skia.Paint(AntiAlias=True)
    if sx > 0.3 or sy > 0.3:
        p.setImageFilter(skia.ImageFilters.Blur(max(sx, 0.01), max(sy, 0.01), skia.TileMode.kClamp))
    p.setAlphaf(clamp(a))
    return p


def di(c, img, x=0.0, y=0.0, p=None, s=1.0, cx=None, cy=None):
    """把一整帧画上去（可平移、缩放）"""
    if s != 1.0:
        cx = CX if cx is None else cx
        cy = CY if cy is None else cy
        c.save(); c.translate(cx, cy); c.scale(s, s); c.translate(-cx, -cy)
    c.drawImageRect(img, skia.Rect.MakeXYWH(x, y, W, H), lib.SAMP, p)
    if s != 1.0:
        c.restore()


# ---------- 时间 ----------
def today_cn():
    import datetime
    d = datetime.date.today()
    return f'{d.year} 年 {d.month} 月 {d.day} 日　星期' + '一二三四五六日'[d.weekday()]
