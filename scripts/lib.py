"""通用绘图底层（skia）：时间和缓动、画笔、文字（缺字自动用思源黑体补）、形状、图标、图片、模糊、字幕读取、
人物窗口的时间窗。

风格相关的东西（配色、字体分工、背景、字幕样式、部件）都在 styles/<风格>/theme.py 里。theme.py 会调用
use_palette() / use_kinds() 改这里的默认值，所以 scenes.py 里要先 `import theme as T`，再 `from lib import *`。

画面尺寸由工程配置决定：_工程/project.json 里 orient = 横屏（1920x1080）或 竖屏（1080x1920）。舞台就是整个画面。
"""
import math, functools, os, re, json
from contextlib import contextmanager
import numpy as np
import skia
import tools  # noqa: F401  （BAJ_STYLE 换风格要在 import theme 之前生效）
import fonts


# ---------- 工程配置 ----------
def _project():
    for p in ('project.json', os.path.join('_工程', 'project.json')):
        if os.path.exists(p):
            with open(p, encoding='utf-8') as f:
                return json.load(f)
    return {}


PROJECT = _project()
ORIENT = os.environ.get('BAJ_ORIENT') or PROJECT.get('orient', '横屏')
VERTICAL = ORIENT == '竖屏'
W, H = (1080, 1920) if VERTICAL else (1920, 1080)
SW, SH = W, H                 # 舞台 = 整个画面
CX, CY = W / 2, H / 2
FPS = 30
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = PROJECT.get('skill_dir') or os.path.dirname(HERE)

# ---------- 配色（theme.py 用 use_palette 覆盖） ----------
INK = (21, 25, 45)
SUBINK = (90, 96, 112)
MUTE = (152, 153, 154)
LINE = (212, 213, 211)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
BG = (246, 246, 239)
ACC = (248, 113, 28)          # 强调色 A
ACC2 = (21, 25, 45)           # 强调色 B
RED = (214, 64, 52)
GRN = (40, 160, 90)
YEL = (255, 206, 64)


def use_palette(**kw):
    """theme.py 调用：use_palette(INK=(..), BG=(..), ACC=(..), ...)"""
    g = globals()
    for k, v in kw.items():
        g[k] = tuple(v)


# ---------- 时间 / 缓动 ----------
def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


PROG_LOG = None             # holds.py 在这里记录每个页面的动画什么时候结束（t0 + d）


def prog(t, t0, d):
    if PROG_LOG is not None and d <= 1.6:              # 更长的 prog 是镜头慢推，不算进场
        PROG_LOG.append((t0, t0 + d))
    return clamp((t - t0) / d) if d > 0 else (1.0 if t >= t0 else 0.0)


def e_out(x):
    return 1 - (1 - x) ** 3


def e_in(x):
    return x ** 3


def e_io(x):
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def e_back(x, s=1.9):
    c3 = s + 1
    return 1 + c3 * (x - 1) ** 3 + s * (x - 1) ** 2


def e_spring(x):
    if x <= 0: return 0.0
    if x >= 1: return 1.0
    return 1 - math.exp(-6.5 * x) * math.cos(11 * x)


def lerp(a, b, x):
    return a + (b - a) * x


def mix(c1, c2, x):
    return tuple(int(lerp(c1[i], c2[i], x)) for i in range(3))


def pop(t, t0, d=0.38):
    """弹出：返回 (缩放, 透明度)"""
    x = prog(t, t0, d)
    return (0.55 + 0.45 * e_back(x)) if x > 0 else 0.0, clamp(x * 2.2)


def rise(t, t0, d=0.45, dist=40):
    """上浮淡入：返回 (dy, 透明度)"""
    x = e_out(prog(t, t0, d))
    return (1 - x) * dist, x


def kf(t, keys):
    """分段缓动关键帧：keys = [(t, x, y), ...] -> (x, y)"""
    if t <= keys[0][0]: return keys[0][1], keys[0][2]
    for (t0, x0, y0), (t1, x1, y1) in zip(keys, keys[1:]):
        if t <= t1:
            e = e_io(prog(t, t0, t1 - t0))
            return lerp(x0, x1, e), lerp(y0, y1, e)
    return keys[-1][1], keys[-1][2]


def steps(t, fps=12):
    """定格动画感：把时间量化到每秒 fps 张（手绘、剪纸类风格的抖动用）"""
    return math.floor(t * fps) / fps


def jitter(t, seed, amt=1.0, fps=12):
    """每秒 fps 次的小抖动 (dx, dy)，同一 seed 同一时刻结果固定"""
    k = int(math.floor(t * fps)) * 7919 + seed * 104729
    rng = np.random.default_rng(k & 0xFFFFFFFF)
    return float(rng.uniform(-amt, amt)), float(rng.uniform(-amt, amt))


# ---------- 颜色 / 画笔 ----------
def col(c, a=1.0):
    return skia.Color(int(c[0]), int(c[1]), int(c[2]), int(255 * clamp(a)))


def paint(c, a=1.0, stroke=None, cap=None, blur=None):
    p = skia.Paint(AntiAlias=True, Color=col(c, a))
    if stroke is not None:
        p.setStyle(skia.Paint.kStroke_Style)
        p.setStrokeWidth(stroke)
        p.setStrokeCap(cap or skia.Paint.kRound_Cap)
        p.setStrokeJoin(skia.Paint.kRound_Join)
    if blur:
        p.setMaskFilter(skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, blur))
    return p


# ---------- 字体 ----------
# kind -> (字体 key, 字重, 垂直居中系数)。theme.py 用 use_kinds 增改；字体 key 见 fonts.FONTS
KINDS = {
    'cn': ('noto_sans_sc', 600, 0.36), 'cn_med': ('noto_sans_sc', 500, 0.36), 'cn_reg': ('noto_sans_sc', 400, 0.36),
    'cn_black': ('noto_sans_sc', 900, 0.36), 'en': ('noto_sans_sc', 700, 0.35), 'num': ('noto_sans_sc', 800, 0.35),
    'sub': ('noto_sans_sc', 600, 0.36),
}
FALLBACK = 'noto_sans_sc'


def use_kinds(**kw):
    KINDS.update(kw)
    typeface.cache_clear(); font.cache_clear(); _runs.cache_clear()


@functools.lru_cache(None)
def typeface(kind):
    key, wt, _ = KINDS[kind]
    return fonts.typeface(key, wt)


@functools.lru_cache(None)
def font(kind, size, fallback=False):
    if fallback:
        key, wt, _ = KINDS[kind]
        f = skia.Font(fonts.typeface(FALLBACK, wt), size)
    else:
        f = skia.Font(typeface(kind), size)
    f.setSubpixel(True)
    f.setEdging(skia.Font.Edging.kAntiAlias)
    return f


@functools.lru_cache(4096)
def _runs(s, kind):
    """把字符串切成 [(片段, 是否用兜底字体)]：这款字体里没有的字用思源黑体补"""
    if not s: return ()
    f = font(kind, 64)
    gl = f.textToGlyphs(s)
    if len(gl) != len(s) or all(g != 0 for g in gl):
        return ((s, False),)
    out, cur, fb = [], '', None
    for ch, g in zip(s, gl):
        m = g == 0 and not ch.isspace()
        if fb is None or m == fb:
            cur += ch; fb = m
        else:
            out.append((cur, fb)); cur, fb = ch, m
    out.append((cur, fb))
    return tuple(out)


def text_w(s, size, kind='cn'):
    return sum(font(kind, size, fb).measureText(r) for r, fb in _runs(s, kind))


def text(c, s, x, y, size, color=None, kind='cn', align='c', a=1.0, stroke=None, track=0.0):
    """以 y 为垂直中心写一行字。align: c/l/r。stroke=(颜色, 粗细) 先描边再填色。track = 字间距（字号的比例）。返回宽度"""
    color = INK if color is None else color
    w = text_w(s, size, kind) + (len(s) - 1) * track * size if s else 0
    if a <= 0 or not s: return w
    bx = x - w / 2 if align == 'c' else (x if align == 'l' else x - w)
    by = y + size * KINDS[kind][2]
    paints = []
    if stroke:
        paints.append(paint(stroke[0], a, stroke=stroke[1]))
    paints.append(paint(color, a))
    for p in paints:
        cx = bx
        for r, fb in _runs(s, kind):
            f = font(kind, size, fb)
            if track:
                for ch in r:
                    c.drawString(ch, cx, by, f, p)
                    cx += f.measureText(ch) + track * size
            else:
                c.drawString(r, cx, by, f, p)
                cx += f.measureText(r)
    return w


def rich(c, parts, x, y, size, align='c', a=1.0):
    """parts: [(文字, 颜色, kind)]"""
    ws = [text_w(s, size, k) for s, _, k in parts]
    tw = sum(ws)
    cx = x - tw / 2 if align == 'c' else (x if align == 'l' else x - tw)
    for (s, cl, k), w in zip(parts, ws):
        text(c, s, cx, y, size, cl, k, 'l', a)
        cx += w
    return tw


def wrap(s, size, maxw, kind='cn'):
    """按宽度折行（中文逐字，英文单词不拆）"""
    lines, cur = [], ''
    for tok in re.findall(r'[A-Za-z0-9.%$+\-]+|\s|.', s):
        if text_w(cur + tok, size, kind) > maxw and cur.strip():
            lines.append(cur.rstrip()); cur = tok.lstrip()
        else:
            cur += tok
    if cur.strip(): lines.append(cur.rstrip())
    return lines


def text_block(c, s, x, y, size, maxw, color=None, kind='cn', align='l', a=1.0, lh=1.45):
    """多行文字，y 是第一行的垂直中心；返回总高度"""
    ls = wrap(s, size, maxw, kind)
    for i, l in enumerate(ls):
        text(c, l, x, y + i * size * lh, size, color, kind, align, a)
    return len(ls) * size * lh


# ---------- 变换 ----------
@contextmanager
def xf(c, cx=0, cy=0, s=1.0, rot=0.0, a=1.0, dx=0.0, dy=0.0, bounds=None):
    c.save()
    c.translate(cx + dx, cy + dy)
    if rot: c.rotate(rot)
    if s != 1.0: c.scale(s, s)
    c.translate(-cx, -cy)
    layered = a < 0.999
    if layered:
        c.saveLayerAlpha(bounds, int(255 * clamp(a)))
    try:
        yield
    finally:
        if layered: c.restore()
        c.restore()


@contextmanager
def blurred(c, s=0.0, a=1.0, bounds=None):
    """把这一块当一层画，高斯模糊 s、透明度 a。bounds = (x, y, w, h)，尽量给，整屏一层很慢"""
    if s < 0.35 and a >= 0.999:
        yield
        return
    p = skia.Paint()
    if s >= 0.35:
        p.setImageFilter(skia.ImageFilters.Blur(s, s))
    if a < 0.999:
        p.setAlphaf(clamp(a))
    if bounds is not None:
        m = 3 * s + 2
        c.saveLayer(skia.Rect.MakeXYWH(bounds[0] - m, bounds[1] - m, bounds[2] + 2 * m, bounds[3] + 2 * m), p)
    else:
        c.saveLayer(None, p)
    try:
        yield
    finally:
        c.restore()


# ---------- 形状 ----------
def rrect(x, y, w, h, r):
    return skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y, w, h), r, r)


def card(c, x, y, w, h, r=22, fill=None, a=1.0, shadow=0.10, border=None, bw=2.0, sblur=18, sdy=10):
    if a <= 0: return
    fill = WHITE if fill is None else fill
    rr = rrect(x, y, w, h, r)
    if shadow:
        c.save(); c.translate(0, sdy)
        c.drawRRect(rr, paint((12, 22, 44), shadow * a, blur=sblur))
        c.restore()
    c.drawRRect(rr, paint(fill, a))
    if border:
        c.drawRRect(rr, paint(border, a, stroke=bw))


def pill(c, cx, cy, s, size, fg=None, bg=None, kind='cn', a=1.0, padx=None, h=None, border=None, shadow=0.0):
    fg = WHITE if fg is None else fg
    bg = ACC if bg is None else bg
    w = text_w(s, size, kind)
    px = padx if padx is not None else size * 0.75
    hh = h or size * 1.9
    card(c, cx - w / 2 - px, cy - hh / 2, w + 2 * px, hh, hh / 2, bg, a, shadow=shadow, border=border)
    text(c, s, cx, cy, size, fg, kind, 'c', a)
    return w + 2 * px


def circle(c, cx, cy, r, color, a=1.0):
    c.drawCircle(cx, cy, r, paint(color, a))


def line(c, x1, y1, x2, y2, color, w=4, a=1.0, p=1.0, dash=None):
    if p <= 0 or a <= 0: return
    pt = paint(color, a, stroke=w)
    if dash:
        pt.setPathEffect(skia.DashPathEffect.Make(dash, 0))
    c.drawLine(x1, y1, x1 + (x2 - x1) * p, y1 + (y2 - y1) * p, pt)


def arrow(c, x1, y1, x2, y2, color=None, w=6, a=1.0, p=1.0, head=20, dash=None):
    color = ACC if color is None else color
    if p <= 0 or a <= 0: return
    ex, ey = x1 + (x2 - x1) * p, y1 + (y2 - y1) * p
    ang = math.atan2(ey - y1, ex - x1)
    bx, by = ex - math.cos(ang) * head * 0.6, ey - math.sin(ang) * head * 0.6
    line(c, x1, y1, bx, by, color, w, a, 1.0, dash)
    path = skia.Path()
    path.moveTo(ex, ey)
    path.lineTo(ex - head * math.cos(ang - 0.5), ey - head * math.sin(ang - 0.5))
    path.lineTo(ex - head * math.cos(ang + 0.5), ey - head * math.sin(ang + 0.5))
    path.close()
    c.drawPath(path, paint(color, a))


def partial_path(path, p):
    """路径画到 p（0..1）：描线动画"""
    if p >= 1: return path
    if p <= 0: return skia.Path()
    pm = skia.PathMeasure(path, False)
    out = skia.Path()
    total = 0.0
    lens = []
    while True:
        lens.append(pm.getLength()); total += lens[-1]
        if not pm.nextContour(): break
    pm = skia.PathMeasure(path, False)
    remain = total * p
    for L in lens:
        if remain <= 0: break
        pm.getSegment(0, min(L, remain), out, True)
        remain -= L
        pm.nextContour()
    return out


def wobble_path(pts, seed=0, amt=2.0, closed=False, overshoot=0.0):
    """手绘感折线：pts = [(x, y), ...]，每段中间加一点随机弯曲；overshoot = 线头出头的长度（像手画的框）"""
    rng = np.random.default_rng(seed)
    path = skia.Path()
    P = list(pts) + ([pts[0]] if closed else [])
    for i in range(len(P) - 1):
        (x0, y0), (x1, y1) = P[i], P[i + 1]
        if overshoot:
            L = math.hypot(x1 - x0, y1 - y0) or 1
            ux, uy = (x1 - x0) / L, (y1 - y0) / L
            x0, y0 = x0 - ux * overshoot * rng.uniform(0.3, 1), y0 - uy * overshoot * rng.uniform(0.3, 1)
            x1, y1 = x1 + ux * overshoot * rng.uniform(0.3, 1), y1 + uy * overshoot * rng.uniform(0.3, 1)
        mx, my = (x0 + x1) / 2 + rng.uniform(-amt, amt), (y0 + y1) / 2 + rng.uniform(-amt, amt)
        if i == 0 or overshoot:
            path.moveTo(x0 + rng.uniform(-amt, amt) * .5, y0 + rng.uniform(-amt, amt) * .5)
        path.quadTo(mx, my, x1 + rng.uniform(-amt, amt) * .5, y1 + rng.uniform(-amt, amt) * .5)
    return path


def strike(c, x1, x2, y, p, color=None, w=6, a=1.0):
    color = RED if color is None else color
    if p <= 0: return
    line(c, x1, y, x1 + (x2 - x1) * e_out(p), y, color, w, a)


def check(c, cx, cy, r, p=1.0, color=None, a=1.0, fg=None):
    color = GRN if color is None else color
    fg = WHITE if fg is None else fg
    if p <= 0 or a <= 0: return
    s = 0.6 + 0.4 * e_back(clamp(p * 1.6))
    with xf(c, cx, cy, s):
        circle(c, cx, cy, r, color, a)
        path = skia.Path()
        path.moveTo(cx - r * 0.45, cy + r * 0.02)
        path.lineTo(cx - r * 0.1, cy + r * 0.36)
        path.lineTo(cx + r * 0.48, cy - r * 0.32)
        c.drawPath(partial_path(path, clamp((p - 0.25) / 0.6)), paint(fg, a, stroke=r * 0.22))


def cross(c, cx, cy, r, p=1.0, color=None, a=1.0):
    color = RED if color is None else color
    if p <= 0 or a <= 0: return
    s = 0.6 + 0.4 * e_back(clamp(p * 1.6))
    with xf(c, cx, cy, s):
        circle(c, cx, cy, r, color, a)
        k = r * 0.38
        line(c, cx - k, cy - k, cx + k, cy + k, WHITE, r * 0.22, a, clamp((p - .2) / .4))
        line(c, cx + k, cy - k, cx - k, cy + k, WHITE, r * 0.22, a, clamp((p - .45) / .4))


def glow(c, cx, cy, r, color=None, a=0.35):
    color = ACC if color is None else color
    if a <= 0: return
    sh = skia.GradientShader.MakeRadial(skia.Point(cx, cy), r, [col(color, a), col(color, 0)])
    p = skia.Paint(AntiAlias=True); p.setShader(sh)
    c.drawCircle(cx, cy, r, p)


def progress_bar(c, x, y, w, h, p, fg=None, bg=None, a=1.0):
    fg = ACC if fg is None else fg
    bg = LINE if bg is None else bg
    c.drawRRect(rrect(x, y, w, h, h / 2), paint(bg, a))
    if p > 0:
        c.drawRRect(rrect(x, y, max(h, w * clamp(p)), h, h / 2), paint(fg, a))


# ---------- SVG 图标（Lucide 线性图标；画面上不用 emoji） ----------
ICON_DIRS = [os.path.join(os.getcwd(), 'icons'), os.path.join(SKILL_DIR, 'assets', 'icons')]
LUCIDE_CDN = ['https://cdn.jsdelivr.net/npm/lucide-static@0.460.0/icons/{}.svg',
              'https://unpkg.com/lucide-static@0.460.0/icons/{}.svg']


def _icon_src(name):
    """Lucide 图标名或 .svg 路径 -> SVG 文本；本地没有的 Lucide 图标第一次用时下载，存到工程的 icons/"""
    if name.endswith('.svg') and os.path.exists(name):
        return open(name, encoding='utf-8').read()
    for d in ICON_DIRS:
        p = os.path.join(d, name + '.svg')
        if os.path.exists(p):
            return open(p, encoding='utf-8').read()
    import subprocess, shutil
    curl = shutil.which('curl') or shutil.which('curl.exe')
    for url in LUCIDE_CDN:
        r = subprocess.run([curl, '-sfL', '--max-time', '20', url.format(name)], capture_output=True) if curl else None
        if r is not None and r.returncode == 0 and b'<svg' in r.stdout:
            data = r.stdout.decode('utf-8')
            os.makedirs(ICON_DIRS[0], exist_ok=True)
            open(os.path.join(ICON_DIRS[0], name + '.svg'), 'w', encoding='utf-8').write(data)
            return data
    raise ValueError(f'图标 {name!r} 本地没有、Lucide 上也没找到；可用的名字见 assets/icons/INDEX.txt 或 lucide.dev/icons')


@functools.lru_cache(None)
def _icon_dom(name, color, sw, fill):
    s = _icon_src(name)
    hexc = '#%02x%02x%02x' % tuple(int(v) for v in color)
    s = s.replace('currentColor', hexc)
    s = re.sub(r'stroke-width="[^"]*"', f'stroke-width="{sw}"', s, count=1)
    if fill is not None:
        s = re.sub(r'fill="none"', 'fill="#%02x%02x%02x"' % tuple(int(v) for v in fill), s, count=1)
    dom = skia.SVGDOM.MakeFromStream(skia.MemoryStream(s.encode('utf-8'), True))
    m = re.search(r'viewBox="([\d.\s-]+)"', s)
    vb = [float(v) for v in m.group(1).split()] if m else [0, 0, 24, 24]
    dom.setContainerSize(skia.Size(vb[2], vb[3]))
    return dom, vb[2], vb[3]


def icon(c, name, cx, cy, size, color=None, a=1.0, sw=2.0, fill=None, rot=0.0, reveal=1.0):
    """以 (cx, cy) 为中心画一个线性图标，宽 size。sw = 线宽（24 格里的单位）。reveal 0..1 从左往右擦出来"""
    color = INK if color is None else color
    if a <= 0 or reveal <= 0 or size <= 0: return
    dom, vw, vh = _icon_dom(name, tuple(color), sw, tuple(fill) if fill else None)
    k = size / vw
    c.save()
    c.translate(cx, cy)
    if rot: c.rotate(rot)
    c.translate(-size / 2, -vh * k / 2)
    if reveal < 1:
        c.clipRect(skia.Rect.MakeXYWH(-4, -4, size * reveal + 4, vh * k + 8))
    layered = a < 0.999
    if layered: c.saveLayerAlpha(None, int(255 * clamp(a)))
    c.scale(k, k)
    dom.render(c)
    if layered: c.restore()
    c.restore()


def icon_badge(c, name, cx, cy, size, fg=None, bg=None, a=1.0, shape='circle', sw=2.0, shadow=0.0):
    fg = WHITE if fg is None else fg
    bg = ACC if bg is None else bg
    if a <= 0: return
    r = size * (.5 if shape == 'circle' else .28)
    if shadow:
        c.drawRRect(rrect(cx - size / 2, cy - size / 2 + 6, size, size, r), paint(BLACK, a * shadow, blur=12))
    c.drawRRect(rrect(cx - size / 2, cy - size / 2, size, size, r), paint(bg, a))
    icon(c, name, cx, cy, size * 0.52, fg, a, sw)


# ---------- 图片 ----------
SAMP = skia.SamplingOptions(skia.FilterMode.kLinear, skia.MipmapMode.kNone)


@functools.lru_cache(64)
def load_img(path):
    img = skia.Image.MakeFromEncoded(skia.Data.MakeFromFileName(path))
    if img is None:
        raise ValueError(f'读不了图片：{path}')
    return img


def draw_img(c, img, x, y, w=None, h=None, a=1.0):
    if isinstance(img, str): img = load_img(img)
    p = skia.Paint(AntiAlias=True); p.setAlphaf(clamp(a))
    w = w or img.width(); h = h or img.height()
    c.drawImageRect(img, skia.Rect.MakeXYWH(x, y, w, h), SAMP, p)


def draw_np(c, arr_rgba, x, y, w=None, h=None, a=1.0):
    img = skia.Image.fromarray(np.ascontiguousarray(arr_rgba), colorType=skia.ColorType.kRGBA_8888_ColorType)
    draw_img(c, img, x, y, w, h, a)


def img_cover(c, img, x, y, w, h, a=1.0, r=0, focus=(0.5, 0.5), zoom=1.0):
    """图片铺满 (x, y, w, h)，多出来的按 focus 裁掉；r = 圆角；zoom > 1 放大（慢推用）"""
    if isinstance(img, str): img = load_img(img)
    if a <= 0: return
    iw, ih = img.width(), img.height()
    k = max(w / iw, h / ih) * zoom
    sw_, sh_ = w / k, h / k
    sx = clamp((iw - sw_) * focus[0], 0, max(0, iw - sw_))
    sy = clamp((ih - sh_) * focus[1], 0, max(0, ih - sh_))
    p = skia.Paint(AntiAlias=True); p.setAlphaf(clamp(a))
    c.save()
    if r: c.clipRRect(rrect(x, y, w, h, r), True)
    c.drawImageRect(img, skia.Rect.MakeXYWH(sx, sy, sw_, sh_), skia.Rect.MakeXYWH(x, y, w, h), SAMP, p,
                    skia.Canvas.kFast_SrcRectConstraint)
    c.restore()


def img_fit(img, maxw, maxh):
    """等比缩到框里，返回 (w, h)"""
    if isinstance(img, str): img = load_img(img)
    k = min(maxw / img.width(), maxh / img.height())
    return img.width() * k, img.height() * k


# ---------- 字幕 ----------
def load_srt(path):
    """[(t0, t1, 文字)]"""
    out = []
    for blk in re.split(r'\n\s*\n', open(path, encoding='utf-8').read().strip()):
        ls = [l.strip() for l in blk.strip().splitlines() if l.strip()]
        m = next((re.match(r'(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)', l) for l in ls if '-->' in l), None)
        if not m: continue
        g = [int(x) for x in m.groups()]
        t0 = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        t1 = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        txt = ' '.join(ls[ls.index(next(l for l in ls if '-->' in l)) + 1:])
        if txt: out.append((t0, t1, txt))
    return sorted(out)


# ---------- 转场时长 / 人物窗口 ----------
HOST_D = 0.6                # 横屏：人物小窗放大成全屏（和缩回去）用的秒数


DEFAULT_TR = 'push'         # TIMELINE 条目不写 tr 时用的转场；风格（theme.py）可以改
TR_D = {'flash': 0.36}      # 各种转场的默认时长（秒），没列的 0.42；风格可以加


def _td(e):
    """一个 TIMELINE 条目进场转场的时长"""
    tr = e.get('tr', DEFAULT_TR)
    return 0.0 if tr == 'cut' else e.get('td', TR_D.get(tr, 0.42))


def full_windows(SC):
    """横屏：人物全屏的时间窗 [(a, b, d)]。TIMELINE 里 host=True 的条目从 a 开始放大、a+d 时占满全屏，
    b-d 开始缩回小窗、b 时缩完。放大以条目时间为中心，缩回以下一个条目时间为中心。竖屏返回 []（人物是普通场景）。"""
    if VERTICAL:
        return []
    d0 = getattr(SC, 'HOST_D', HOST_D)
    tl = SC.TIMELINE
    ws = []
    for i, e in enumerate(tl):
        if not e.get('host'):
            continue
        nxt = tl[i + 1]['t'] if i + 1 < len(tl) else 1e9
        ws.append([e['t'] - d0 / 2, nxt + d0 / 2 if nxt < 1e8 else 1e9, d0])
    out = []
    for w in ws:
        if out and w[0] <= out[-1][1] + 0.3:
            out[-1][1] = max(out[-1][1], w[1])
        else:
            out.append(w)
    return [tuple(w) for w in out]


def full_amount(t, windows):
    """0 = 画面全屏（人物在小窗），1 = 人物全屏；缓入缓出，不跳变"""
    f = 0.0
    for a, b, d in windows:
        if a < t < b:
            d = min(d, (b - a) / 2)
            f = max(f, min(e_io(prog(t, a, d)), 1 - e_io(prog(t, b - d, d))))
    return f


def host_stats(SC, dur):
    """打印人物全屏 / 画面全屏的时长比例"""
    tl = SC.TIMELINE
    host = 0.0
    for i, e in enumerate(tl):
        if e.get('host'):
            nxt = tl[i + 1]['t'] if i + 1 < len(tl) else dur
            host += min(nxt, dur) - e['t']
    print(f'人物全屏 {host:.1f} s，画面全屏 {dur - host:.1f} s（画面占 {100 * (dur - host) / max(dur, 1e-6):.0f}%）')
    return host, dur - host
