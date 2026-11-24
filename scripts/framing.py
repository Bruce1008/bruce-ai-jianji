"""人物取景：看口播原片里人脸在哪，定下「人物全屏」和横屏「人物小窗」各裁原片的哪一块。
调完色、选风格之前做一次（只有录音、没有画面就跳过）。

usage（在 _工程/ 里）：
  python framing.py                                 按现在的设置出 人物取景.png
  python framing.py --focus 0.5,0.47 [--zoom 1.1]   试另一个人脸位置 / 小窗松紧（zoom 大 = 小窗里人更大）
  python framing.py --focus 0.5,0.47 --save         定下来：存进 project.json，render.py、style_preview.py 都用它

人物取景.png
  上排：原片 3 个时间点。灰线是 10% 网格（边上标了 .1 … .9），绿十字 = 现在设的人脸位置（两眼中间），
        红框 = 人物全屏裁的那块，橙框 = 横屏小窗裁的那块
  下排：实际效果。人物全屏（中间那个时间点）+ 每个时间点的小窗
看什么：红框、橙框里头顶和下巴都在，脸在框的中间偏上。绿十字要落在两眼中间；不对就照网格读出那一点的 x、y，带 --focus 再出一次。
"""
import os, sys, json, argparse, re
import intake, grade
import layout as L
from lib import W, H, VERTICAL
from PIL import Image, ImageDraw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--video', default='口播_粗剪.mp4')
    ap.add_argument('--focus', default=None, help='x,y（0..1）')
    ap.add_argument('--zoom', type=float, default=None)
    ap.add_argument('--save', action='store_true')
    ap.add_argument('--out', default='人物取景.png')
    a = ap.parse_args()
    if not os.path.exists(a.video):
        sys.exit(f'没有 {a.video}（先做第 5 步粗剪，或用 --video 指定口播）')
    info = intake.probe(a.video) or {}
    if 'w' not in info:
        sys.exit('口播只有声音，没有人物画面，不用取景')
    vw, vh, dur = info['w'], info['h'], info['dur']
    focus0, zoom0 = L.host_setting()
    focus = tuple(float(x) for x in a.focus.split(',')) if a.focus else focus0
    zoom = a.zoom if a.zoom else zoom0
    if os.path.exists('scenes.py') and re.search(r'^\s*(HOST_FOCUS|PIP_ZOOM)\s*=', open('scenes.py', encoding='utf-8').read(), re.M):
        print('注意：scenes.py 里写了 HOST_FOCUS / PIP_ZOOM，渲染时用的是那里的值，不是这里的')

    full, pip = L.host_rects(vw, vh, focus, zoom)
    times = [round(dur * k, 2) for k in (0.2, 0.5, 0.8)]
    frames = [grade.frame_at(a.video, t, vw, vf=grade.host_vf(t)) for t in times]

    th = 560                                        # 上排每张的高
    tw = int(vw * th / vh)
    s = th / vh
    tops = []
    for im in frames:
        im = im.resize((tw, th), Image.LANCZOS)
        d = ImageDraw.Draw(im)
        for k in range(1, 10):
            x, y = tw * k / 10, th * k / 10
            d.line([(x, 0), (x, th)], fill=(200, 200, 200), width=1)
            d.line([(0, y), (tw, y)], fill=(200, 200, 200), width=1)
            d.text((x + 2, 2), f'.{k}', fill=(255, 255, 255))
            d.text((2, y + 2), f'.{k}', fill=(255, 255, 255))
        for (x, y, w, h), clr in ((full, (230, 40, 40)), (pip, (255, 150, 0))):
            if VERTICAL and clr != (230, 40, 40):
                continue
            d.rectangle([x * s, y * s, (x + w) * s, (y + h) * s], outline=clr, width=3)
        cx, cy = focus[0] * tw, focus[1] * th
        d.line([(cx - 14, cy), (cx + 14, cy)], fill=(40, 220, 90), width=3)
        d.line([(cx, cy - 14), (cx, cy + 14)], fill=(40, 220, 90), width=3)
        tops.append(im)

    def cut(im, r, size):
        x, y, w, h = r
        return im.crop((int(x), int(y), int(x + w), int(y + h))).resize(size, Image.LANCZOS)

    fs = (480, 270) if not VERTICAL else (270, 480)
    bottom = [cut(frames[1], full, fs)]
    if not VERTICAL:
        bottom += [cut(im, pip, (203, 270)) for im in frames]

    gap = 14
    top_w = len(tops) * tw + (len(tops) + 1) * gap
    bot_w = sum(b.width for b in bottom) + (len(bottom) + 1) * gap
    sheet = Image.new('RGB', (max(top_w, bot_w), th + max(b.height for b in bottom) + 3 * gap), (40, 40, 40))
    x = gap
    for im in tops:
        sheet.paste(im, (x, gap)); x += tw + gap
    x = gap
    for b in bottom:
        sheet.paste(b, (x, th + 2 * gap)); x += b.width + gap
    sheet.save(a.out)
    print(f'{a.out}：人脸中心 {focus[0]:.2f},{focus[1]:.2f}，小窗松紧 {zoom:g}（原片 {vw}x{vh}，看 {", ".join(f"{t:g}s" for t in times)}）')

    if a.save:
        cfg = json.load(open('project.json', encoding='utf-8'))
        cfg['host_focus'] = [round(focus[0], 3), round(focus[1], 3)]
        cfg['pip_zoom'] = round(zoom, 3)
        json.dump(cfg, open('project.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('已存进 project.json')


if __name__ == '__main__':
    main()
