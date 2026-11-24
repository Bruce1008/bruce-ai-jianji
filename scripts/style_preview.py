"""第 7 步：看风格。不用口播视频，直接把示例页面（styles/示例.py，所有风格共用）用某个风格出成静帧，
带上人物小窗（横屏）和字幕，看起来和成片一样。

usage: python style_preview.py <风格> [--orient 横屏|竖屏] [--out 文件夹] [--host 人物截图.png]
       python style_preview.py <风格> --use      （在 _工程 里运行）用户选定后：把风格装进这个工程
writes: <out>/<风格>_<横屏|竖屏>.png（几页拼一张）和每页单独的 png
--host：小窗里放哪张人物图。不给时：当前文件夹有 口播_粗剪.mp4 就从里面取一帧（套上调色），没有就画一个示意的人影
--use：复制 styles/<风格>/theme.py 到当前文件夹，project.json 里记下 style；示例.py 也复制一份（示例_<风格>.py）给写画面时参考
"""
import os, sys, argparse, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))


def _skill_dir():
    """技能文件夹：在 _工程 里运行时看 project.json 的 skill_dir，否则是这个脚本的上一级"""
    import json
    for p in ('project.json', os.path.join('_工程', 'project.json')):
        if os.path.exists(p):
            d = json.load(open(p, encoding='utf-8')).get('skill_dir')
            if d and os.path.isdir(os.path.join(d, 'styles')):
                return d
    return os.path.dirname(HERE)


SKILL = _skill_dir()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('style')
    ap.add_argument('--orient', default=None, choices=['横屏', '竖屏'])
    ap.add_argument('--out', default='风格预览')
    ap.add_argument('--host', default=None)
    ap.add_argument('--use', action='store_true')
    a = ap.parse_args()
    sdir = os.path.join(SKILL, 'styles', a.style)
    if not os.path.exists(os.path.join(sdir, 'theme.py')):
        have = [d for d in os.listdir(os.path.join(SKILL, 'styles')) if os.path.exists(os.path.join(SKILL, 'styles', d, 'theme.py'))]
        sys.exit(f'没有风格「{a.style}」。现有：{"、".join(have)}')
    if a.use:
        return use(a.style, sdir)
    if a.orient:
        os.environ['BAJ_ORIENT'] = a.orient
    sys.path.insert(0, HERE)
    sys.path.insert(0, sdir)                       # theme.py、示例.py 从风格文件夹里取
    import theme as T                              # noqa: E402
    import lib, layout as L                        # noqa: E402
    import skia, numpy as np                       # noqa: E402
    spec = importlib.util.spec_from_file_location('demo', _demo_file(sdir))
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)

    class S:                                       # 示例页面只用到 t0
        t0 = 0.0

    os.makedirs(a.out, exist_ok=True)
    if not a.host:
        a.host = _host_from_take(a.out)
    host = lib.load_img(a.host) if a.host else _fake_host(skia, lib)
    W, H = lib.W, lib.H
    shots = []
    for name, fn, ts in demo.PAGES:
        surf = skia.Surface(W, H)
        c = surf.getCanvas()
        fn(c, ts, S)
        if not lib.VERTICAL:                       # 横屏：左上角人物小窗
            x, y, w, h, r = L.PIP
            c.save(); c.translate(0, 10)
            c.drawRRect(lib.rrect(x, y, w, h, r), lib.paint(lib.BLACK, 0.28, blur=22))
            c.restore()
            c.save(); c.clipRRect(lib.rrect(x, y, w, h, r), True)
            _, (sx, sy, sw, sh) = L.host_rects(host.width(), host.height(), *L.host_setting())  # 和成片一样的裁法
            c.drawImageRect(host, skia.Rect.MakeXYWH(sx, sy, sw, sh), skia.Rect.MakeXYWH(x, y, w, h), lib.SAMP, None,
                            skia.Canvas.kFast_SrcRectConstraint)
            c.restore()
            T.pip_frame(c, x, y, w, h, r, 1.0)
        T.sub(c, getattr(demo, 'SUB', '字幕的样子'), lib.CX, L.SUB_Y, L.SUB_SIZE, L.SUB_MAXW)
        p = os.path.join(a.out, f'{a.style}_{lib.ORIENT}_{name}.png')
        surf.makeImageSnapshot().save(p)
        shots.append(p)
    from PIL import Image
    ims = [Image.open(p).convert('RGB') for p in shots]
    k = 0.5 if not lib.VERTICAL else 0.36
    ims = [im.resize((int(im.width * k), int(im.height * k)), Image.LANCZOS) for im in ims]
    gap = 16
    if lib.VERTICAL:
        sheet = Image.new('RGB', (sum(i.width for i in ims) + gap * (len(ims) + 1), ims[0].height + 2 * gap), 'white')
        x = gap
        for im in ims:
            sheet.paste(im, (x, gap)); x += im.width + gap
    else:
        sheet = Image.new('RGB', (ims[0].width * 2 + gap * 3, (ims[0].height + gap) * ((len(ims) + 1) // 2) + gap), 'white')
        for i, im in enumerate(ims):
            sheet.paste(im, (gap + (i % 2) * (im.width + gap), gap + (i // 2) * (im.height + gap)))
    out = os.path.join(a.out, f'{a.style}_{lib.ORIENT}.png')
    sheet.save(out)
    print(out)


def use(style, sdir):
    import shutil, json
    if not os.path.exists('project.json'):
        sys.exit('--use 要在工程的 _工程 文件夹里运行')
    shutil.copy(os.path.join(sdir, 'theme.py'), 'theme.py')
    shutil.copy(_demo_file(sdir), f'示例_{style}.py')
    cfg = json.load(open('project.json', encoding='utf-8'))
    cfg['style'] = style
    json.dump(cfg, open('project.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'风格「{style}」装好了：theme.py（部件说明见 {os.path.join(sdir, "风格卡.md")}）')


def _demo_file(sdir):
    """风格自己的 示例.py；没有就用 styles/示例.py（所有风格共用同一套部件，示例页面也通用）"""
    own = os.path.join(sdir, '示例.py')
    return own if os.path.exists(own) else os.path.join(os.path.dirname(sdir), '示例.py')


def _host_from_take(out, take='口播_粗剪.mp4'):
    """从粗剪口播里取一帧（1/3 处，套上调色）当小窗里的人；没有口播画面返回 None"""
    if not os.path.exists(take):
        return None
    try:
        import intake, grade
        info = intake.probe(take) or {}
        if 'w' not in info:
            return None
        t = round(info['dur'] / 3, 2)
        im = grade.frame_at(take, t, 1080, vf=grade.host_vf(t))
        p = os.path.join(out, '_人物.png')
        im.save(p)
        return p
    except Exception as e:                         # 取不到就用示意人影，不影响出风格图
        print(f'（没取到口播画面：{e}）')
        return None


def _fake_host(skia, lib):
    """示意的人影（没有口播截图时）"""
    surf = skia.Surface(600, 800)
    c = surf.getCanvas()
    c.clear(lib.col((206, 196, 184)))
    c.drawCircle(300, 300, 120, lib.paint((120, 104, 92)))
    c.drawRRect(lib.rrect(110, 450, 380, 420, 160), lib.paint((92, 100, 120)))
    return surf.makeImageSnapshot()


if __name__ == '__main__':
    main()
