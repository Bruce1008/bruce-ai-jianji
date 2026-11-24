"""两套版式的几何：人物小窗、人物全屏的裁切、字幕位置、安全区。

横屏 1920x1080：画面全屏，左上角一个圆角人物小窗；TIMELINE 里 host=True 的地方小窗平滑放大成人物全屏，
               下一个条目开始时缩回去。
竖屏 1080x1920：画面全屏 ⇄ 人物全屏（host=True 是一个普通场景，和别的场景之间走普通转场）。

口播原片和成片方向不一致时（竖拍做横屏、横拍做竖屏），人物全屏要按人脸位置裁一块再放大，会有点糊。
人脸位置用 framing.py 看图定下来（存进 project.json）；scenes.py 里写 HOST_FOCUS = (x, y)、PIP_ZOOM 会盖过它。
"""
from lib import W, H, VERTICAL, clamp

# 横屏人物小窗：x, y, 宽, 高, 圆角
PIP = (44, 44, 312, 416, 26)
PIP_SAFE = (0, 0, PIP[0] + PIP[2] + 28, PIP[1] + PIP[3] + 28)   # 画面全屏时这块别放重点内容

# 字幕：中心 y、字号、一行最大宽度
if VERTICAL:
    SUB_Y, SUB_SIZE, SUB_MAXW = 1415, 64, W - 140
    SAFE = (70, 120, W - 70, 1330)        # 重点内容放这个框里（抖音两边可能各裁约 55 px，下面是字幕区）
else:
    SUB_Y, SUB_SIZE, SUB_MAXW = 985, 54, W - 260
    SAFE = (60, 50, W - 60, 920)

DEFAULT_FOCUS = (0.5, 0.42)             # 人脸位置 = 两眼中间那一点在原片里的相对位置；自拍一般在正中、偏上一点


def host_setting():
    """人脸位置和小窗松紧：scenes.py 没写 HOST_FOCUS / PIP_ZOOM 时用 project.json 里 framing.py 存的值"""
    import json, os
    for p in ('project.json', os.path.join('_工程', 'project.json')):
        if os.path.exists(p):
            cfg = json.load(open(p, encoding='utf-8'))
            f = cfg.get('host_focus')
            return (tuple(f) if f else DEFAULT_FOCUS), float(cfg.get('pip_zoom') or 1.0)
    return DEFAULT_FOCUS, 1.0


def host_rects(vw, vh, focus=DEFAULT_FOCUS, pip_zoom=1.0):
    """原片里要用的两块，单位是原片像素 (x, y, w, h)：
    full  人物全屏用的那块：和成片同比例。原片方向不一致时裁一块，人脸中心放在中间
    pip   横屏小窗用的那块：3:4，头和肩都在。竖拍的原片取 82% 宽，横拍的取整个高度；pip_zoom > 1 更紧"""
    a = W / H
    fx, fy = focus[0] * vw, focus[1] * vh
    if abs(vw / vh - a) < 0.01:
        full = (0, 0, vw, vh)
    elif vw / vh > a:                   # 原片更宽（横拍做竖屏）：裁左右
        cw = int(vh * a) // 2 * 2
        full = (int(clamp(fx - cw / 2, 0, vw - cw)), 0, cw, vh)
    else:                               # 原片更高（竖拍做横屏）：裁上下
        ch = int(vw / a) // 2 * 2
        full = (0, int(clamp(fy - ch * 0.48, 0, vh - ch)), vw, ch)
    if vh / vw > 4 / 3:
        pw = vw * 0.82
        ph = pw * 4 / 3
    else:
        ph = vh
        pw = ph * 3 / 4
    pw, ph = pw / pip_zoom, ph / pip_zoom
    k = min(1.0, vw / pw, vh / ph)
    pw, ph = pw * k, ph * k
    pip = (clamp(fx - pw / 2, 0, vw - pw), clamp(fy - ph * 0.42, 0, vh - ph), pw, ph)
    return full, pip


def host_crop(vw, vh, focus=DEFAULT_FOCUS):
    """人物全屏用的 ffmpeg crop。返回 (crop 字符串 或 None, 放大倍数)"""
    if not vw or not vh:
        return None, 1.0
    (x, y, w, h), _ = host_rects(vw, vh, focus)
    if (w, h) == (vw, vh):
        return None, W / vw
    return f'{w}:{h}:{x}:{y}', W / w
