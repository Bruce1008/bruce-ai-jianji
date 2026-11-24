"""示例页面（所有风格通用）：style_preview.py 用它出风格静帧；写 scenes.py 时照着抄部件的用法。
所有风格的部件名字、参数都一样（见 styles/部件.md），所以这一份示例换哪个风格都能出图。
三页：标题页（页眉 + 标题 + 标签 + 逐字出字 + 重点词 + 问号 + 占位线）、照片页（照片 + 卡片 + 勾叉 + 箭头）、
数字页（大数字 + 高亮 + 圈 + 一句话 + 印章）。坐标按 W、H 和 layout 算，横屏、竖屏都能用。
"""
import functools
import theme as T
from lib import *  # noqa: F401,F403
import lib
import layout as L
import skia

SUB = '这一页是字幕的样子'


@functools.lru_cache(2)
def demo_photo(w=900, h=640):
    """示例用的假照片（天空、太阳、山）；真做片子时换成素材文件路径"""
    surf = skia.Surface(w, h)
    c = surf.getCanvas()
    sh = skia.GradientShader.MakeLinear([skia.Point(0, 0), skia.Point(0, h)],
                                        [col((122, 170, 214)), col((236, 222, 196))], None, skia.TileMode.kClamp)
    p = skia.Paint(AntiAlias=True)
    p.setShader(sh)
    c.drawRect(skia.Rect.MakeWH(w, h), p)
    c.drawCircle(w * 0.72, h * 0.32, h * 0.1, paint((255, 214, 150)))
    for k, (clr, base, peaks) in enumerate((((96, 118, 140), 0.62, [(0.1, 0.38), (0.35, 0.5), (0.58, 0.3), (0.9, 0.46)]),
                                            ((58, 74, 86), 0.78, [(0.0, 0.6), (0.25, 0.48), (0.5, 0.66), (0.8, 0.5)]))):
        path = skia.Path()
        path.moveTo(0, h)
        path.lineTo(0, h * base)
        for x, y in peaks:
            path.lineTo(w * x, h * y)
        path.lineTo(w, h * base)
        path.lineTo(w, h)
        path.close()
        c.drawPath(path, paint(clr))
    return surf.makeImageSnapshot()


def _left():
    """横屏内容区左边界（让开人物小窗）"""
    return 60 if lib.VERTICAL else L.PIP_SAFE[2] + 40


def p_title(c, t, S):
    T.paper(c, t, head='AI 剪辑 · 第 1 课')
    t0 = S.t0
    with T.cam(c, t, t0):
        if lib.VERTICAL:
            T.title(c, 'AI 剪辑', W / 2, H * 0.2, 120, t, t0 + 0.1, sub_en='AI EDITING')
            x, y = 90, H * 0.37
            T.tag(c, '@三步', x, y, 46, t, t0 + 0.8)
            T.write(c, '剪气口、加音效、', x, y + 110, 64, t, t0 + 1.0)
            T.write(c, '先出开头', x, y + 210, 64, t, t0 + 1.9)
            bw = T.block_word(c, '15 秒', x + text_w('先出开头', 64, 'hand') + 20, y + 210, 64, t, t0 + 2.4, align='l')
            T.mark(c, '？', x + text_w('先出开头', 64, 'hand') + 20 + bw + 60, y + 204, 120, t, t0 + 2.8)
            for k in range(3):
                T.squiggle(c, x, y + 320 + k * 56, W - 2 * x - k * 120, T.prog(t, t0 + 3.0 + k * 0.2, 0.5), seed=k)
        else:
            lx = _left()
            cx = (lx + W - 60) / 2
            T.title(c, 'AI 剪辑', cx, H * 0.3, 128, t, t0 + 0.1, sub_en='AI EDITING')
            y = H * 0.58
            s1 = '剪气口、加音效、先出'
            tw = text_w('@三步', 44, 'hand') + 44 * 0.76
            row = tw + 26 + text_w(s1, 60, 'hand') + 18 + text_w('15 秒', 60, 'hand') + 60 * 0.6 + 120
            x0 = cx - row / 2
            w = T.tag(c, '@三步', x0, y, 44, t, t0 + 0.8)
            x1 = x0 + w + 26
            T.write(c, s1, x1, y, 60, t, t0 + 1.0, pen_on=True)
            x2 = x1 + text_w(s1, 60, 'hand') + 18
            bw = T.block_word(c, '15 秒', x2, y, 60, t, t0 + 2.3, align='l')
            T.mark(c, '？', x2 + bw + 62, y - 4, 130, t, t0 + 2.8)
            T.hunder(c, x1, x1 + text_w('剪气口', 60, 'hand'), y + 46, T.prog(t, t0 + 1.4, 0.4), seed=4)
            for k in range(2):
                T.squiggle(c, x0, y + 110 + k * 54, row * (0.9 - k * 0.3), T.prog(t, t0 + 3.2 + k * 0.2, 0.5), seed=k)


def p_photo(c, t, S):
    T.paper(c, t, head='第 4 步 · 找素材')
    t0 = S.t0
    with T.cam(c, t, t0, amt=0.03):
        if lib.VERTICAL:
            px, py, pw, ph = 110, 170, W - 220, 680
            T.photo(c, demo_photo(), px, py, pw, ph, t, t0, rot=-2.5, caption='素材：可商用图库')
            sx, sy, sw, sh = 120, 930, W - 240, 400
        else:
            lx = _left()
            px, py, pw, ph = lx + 20, 160, 620, 560
            T.photo(c, demo_photo(), px, py, pw, ph, t, t0, rot=-3, caption='素材：可商用图库')
            sx, sy, sw, sh = px + pw + 90, 200, W - (px + pw + 90) - 90, 440
        T.sheet(c, sx, sy, sw, sh, t, t0 + 0.5, seed=4, rot=1.5, layers=2)
        T.tag(c, '@找素材', sx + 40, sy + 74, 40, t, t0 + 0.9)
        for k, line in enumerate(('只要能商用的', 'CC0、CC BY 都行', 'NC、SA 一律不要')):
            yy = sy + 166 + k * 84
            T.write(c, line, sx + 100, yy, 48, t, t0 + 1.2 + k * 0.8)
            if k < 2:
                T.hcheck(c, sx + 58, yy - 4, 38, T.prog(t, t0 + 1.2 + k * 0.8 + 0.7, 0.3), seed=k)
            else:
                T.hcross(c, sx + 58, yy - 4, 32, T.prog(t, t0 + 1.2 + k * 0.8 + 0.7, 0.3), seed=k)
        if not lib.VERTICAL:
            T.harrow(c, sx - 10, sy + sh - 40, px + pw - 30, py + ph - 120, T.prog(t, t0 + 3.6, 0.5), seed=9,
                     curve=-0.25)


def p_number(c, t, S):
    T.paper(c, t, head='开头先行')
    t0 = S.t0
    with T.cam(c, t, t0):
        cx = W / 2 if lib.VERTICAL else (_left() + W - 60) / 2
        cy = H * 0.36 if lib.VERTICAL else H * 0.42
        nw = T.number(c, '15', '秒', cx, cy, 300, t, t0, a=0)          # a=0：只量宽度不画
        T.marker(c, cx - nw / 2 - 40, cx + nw / 2 + 40, cy + 60, 130, T.prog(t, t0 + 0.7, 0.45))
        T.number(c, '15', '秒', cx, cy, 300, t, t0)
        T.hcircle(c, cx, cy + 10, nw * 0.62, 190, T.prog(t, t0 + 1.2, 0.6), seed=2)
        T.write(c, '先剪开头，看对了再做全片', cx, cy + 270, 56, t, t0 + 1.6, align='c')
        T.stamp(c, '先看开头', cx + (230 if lib.VERTICAL else 520), cy + (480 if lib.VERTICAL else 330), 64, t,
                t0 + 2.6)


# (名字, 画面函数, 出静帧的时刻)
PAGES = [('标题页', p_title, 4.6), ('照片页', p_photo, 4.4), ('数字页', p_number, 3.3)]
