"""第 6 步：给口播调色。照参考图（或默认规则）生成 3D LUT，render.py 读口播时自动套上。

usage（在 _工程/ 里）：
  python grade.py [--ref 参考图] [--video 口播_粗剪.mp4] [--strength 0.8]
  python grade.py off                不调色（删掉调色结果）
writes: grade.json、grade.cube（分段录制时 grade_1.cube、grade_2.cube…）、调色对比.png

参考图：--ref 指定；不指定就用 4_参考图 里文件名带「调色」的那张；都没有就按默认规则（去黄、提亮、轻微 S 曲线）。

规则（照文章踩过的坑）：
  1. 去黄只压 b*（黄-蓝轴），a*（红润）基本不动，也不靠降饱和度
  2. 只做白平衡、亮度、对比度，不做色相映射：衣服、背景的颜色相不会跟着参考图变
     白平衡只看画面里接近中性灰的像素（墙、白衣服），不会因为参考图背景是蓝的就把人调蓝
  3. 分段录制（中途灯光变了）按亮度 / 色温跳变自动分段，每段各算一个 LUT，都对齐同一个目标
  4. 统计量按 2 秒以上平滑，整段用一个固定的 LUT，不逐帧自适应，不会忽明忽暗
"""
import os, sys, json, glob, math, subprocess, argparse
import numpy as np
import tools, fonts

N = 33
IMG_EXT = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')


# ---------- 颜色空间（sRGB D65 <-> Lab） ----------

_M = np.array([[0.4124564, 0.3575761, 0.1804375],
               [0.2126729, 0.7151522, 0.0721750],
               [0.0193339, 0.1191920, 0.9503041]])
_MI = np.linalg.inv(_M)
_WHITE = np.array([0.95047, 1.0, 1.08883])


def rgb2lab(rgb):
    """rgb: (..., 3) 0..1 -> Lab"""
    c = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    xyz = c @ _M.T / _WHITE
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def lab2rgb(lab):
    fy = (lab[..., 0] + 16) / 116
    fx = fy + lab[..., 1] / 500
    fz = fy - lab[..., 2] / 200
    f = np.stack([fx, fy, fz], -1)
    xyz = np.where(f ** 3 > 216 / 24389, f ** 3, (116 * f - 16) / (24389 / 27)) * _WHITE
    c = xyz @ _MI.T
    c = np.clip(c, 0, None)
    return np.clip(np.where(c <= 0.0031308, 12.92 * c, 1.055 * c ** (1 / 2.4) - 0.055), 0, 1)


# ---------- 统计 ----------

def stats(lab):
    """一组像素（N,3 Lab）-> 亮度均值/标准差、整体 a b、中性像素 a b"""
    L, a, b = lab[:, 0], lab[:, 1], lab[:, 2]
    ok = (L > 6) & (L < 97)
    L, a, b = L[ok], a[ok], b[ok]
    chroma = np.hypot(a, b)
    neu = (chroma < 18) & (L > 20) & (L < 92)
    frac = float(neu.mean()) if len(neu) else 0.0
    return dict(L=float(L.mean()), sd=float(L.std()), a=float(a.mean()), b=float(b.mean()),
                na=float(a[neu].mean()) if neu.sum() > 50 else float(a.mean()),
                nb=float(b[neu].mean()) if neu.sum() > 50 else float(b.mean()), neutral=frac)


def video_frames(path, fps=1.0, width=200):
    """每秒一帧小图 -> (n, h, w, 3) 0..1"""
    r = subprocess.run([tools.FFPROBE, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                        'stream=width,height:stream_side_data=rotation', '-of', 'json', path],
                       capture_output=True, text=True)
    s = json.loads(r.stdout)['streams'][0]
    w, h = s['width'], s['height']
    rot = next((int(sd.get('rotation', 0)) for sd in s.get('side_data_list', []) or [] if 'rotation' in sd), 0)
    if abs(rot) in (90, 270):
        w, h = h, w
    hh = int(round(width * h / w / 2)) * 2
    raw = subprocess.run([tools.FFMPEG, '-v', 'error', '-i', path, '-vf', f'fps={fps},scale={width}:{hh}',
                          '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True).stdout
    n = len(raw) // (width * hh * 3)
    return np.frombuffer(raw[:n * width * hh * 3], np.uint8).reshape(n, hh, width, 3) / 255.0


def segments(per_sec, min_len=6):
    """per_sec: [(L, b)] 每秒 -> 分段 [(起秒, 止秒)]。前后各 3 秒的均值比，亮度差 >6 或 b 差 >4 算跳变"""
    n = len(per_sec)
    if n < 2 * min_len:
        return [(0, n)]
    arr = np.array(per_sec)
    cuts = [0]
    i = min_len
    while i <= n - min_len:
        before, after = arr[max(cuts[-1], i - 3):i].mean(0), arr[i:i + 3].mean(0)
        if abs(after[0] - before[0]) > 6 or abs(after[1] - before[1]) > 4:
            cuts.append(i)
            i += min_len
        else:
            i += 1
    cuts.append(n)
    return list(zip(cuts[:-1], cuts[1:]))


# ---------- 变换 ----------

def plan(src, ref, strength):
    """源统计 + 目标 -> 变换参数（亮度 gamma、对比度 r、a/b 平移）"""
    if ref:
        tL = float(np.clip(ref['L'], src['L'] - 15, src['L'] + 15))
        db = float(np.clip(ref['nb'] - src['nb'], -14, 8))
        da = float(np.clip(0.3 * (ref['na'] - src['na']), -3, 3))
        r_sd = ref['sd']
    else:
        tL = max(src['L'], min(src['L'] + 8, 56))
        db = -0.6 * max(0.0, src['nb'] - 4)             # 偏黄才压，压掉 60%
        da = 0.0
        r_sd = None
    tL = src['L'] + (tL - src['L']) * strength
    g = math.log(max(tL, 1) / 100) / math.log(max(src['L'], 1) / 100)
    g = float(np.clip(g, 0.72, 1.3))
    est_sd = src['sd'] * g * (tL / max(src['L'], 1))
    r = float(np.clip(r_sd / max(est_sd, 1), 0.85, 1.25)) if r_sd else 1.08
    r = 1 + (r - 1) * strength
    return dict(gamma=g, contrast=r, pivot=tL, da=da * strength, db=db * strength)


def apply(lab, p):
    L = np.clip(lab[..., 0], 0, 100)
    L = 100 * (L / 100) ** p['gamma']
    L = L + (p['contrast'] - 1) * (L - p['pivot']) * np.sin(np.pi * L / 100)
    w = np.sin(np.pi * np.clip(L, 0, 100) / 100) ** 0.7          # 白平衡主要作用在中间调，纯黑纯白不染色
    out = np.stack([L, lab[..., 1] + p['da'] * w, lab[..., 2] + p['db'] * w], -1)
    return out


def write_cube(path, p):
    v = np.linspace(0, 1, N)
    b, g, r = np.meshgrid(v, v, v, indexing='ij')           # r 变化最快
    rgb = np.stack([r, g, b], -1).reshape(-1, 3)
    out = lab2rgb(apply(rgb2lab(rgb), p))
    with open(path, 'w', encoding='ascii') as f:
        f.write(f'TITLE "bruce-ai-jianji"\nLUT_3D_SIZE {N}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n')
        for x in out:
            f.write(f'{x[0]:.6f} {x[1]:.6f} {x[2]:.6f}\n')


def describe(src, p):
    parts = []
    dL = 100 * (src['L'] / 100) ** p['gamma'] - src['L']
    if abs(dL) >= 1:
        parts.append(f'{"提亮" if dL > 0 else "压暗"} {abs(dL):.0f}')
    if abs(p['db']) >= 1:
        parts.append(f'{"去黄" if p["db"] < 0 else "加暖"} {abs(p["db"]):.0f}')
    if abs(p['da']) >= 1:
        parts.append(f'{"加红润" if p["da"] > 0 else "减红"} {abs(p["da"]):.0f}')
    if abs(p['contrast'] - 1) >= 0.03:
        parts.append(f'对比度 ×{p["contrast"]:.2f}')
    return '、'.join(parts) or '基本不动'


# ---------- 给 render.py 用 ----------

def host_vf(ss=0.0, folder='.'):
    """读口播时要加的滤镜（ss = 这个读取器从原片第几秒开始读，分段 LUT 的时间要跟着平移）；没调色返回 None"""
    cfg_p = os.path.join(folder, 'grade.json')
    if not os.path.exists(cfg_p):
        return None
    cfg = json.load(open(cfg_p, encoding='utf-8'))
    segs = cfg.get('segments') or []
    if len(segs) == 1:
        return f"lut3d=file={segs[0]['cube']}"
    out = []
    for k, s in enumerate(segs):
        t0 = -1e9 if k == 0 else s['t0'] - ss
        t1 = 1e9 if k == len(segs) - 1 else s['t1'] - ss
        if t1 <= 0:
            continue
        out.append(f"lut3d=file={s['cube']}:enable='between(t,{t0:.3f},{t1:.3f})'")
    return ','.join(out) or None


# ---------- 对比图 ----------

def frame_at(path, t, width, vf=None):
    filt = (vf + ',' if vf else '') + f'scale={width}:-2'
    raw = subprocess.run([tools.FFMPEG, '-v', 'error', '-ss', f'{t:.2f}', '-i', path, '-frames:v', '1', '-vf', filt,
                          '-f', 'image2pipe', '-vcodec', 'png', '-'], capture_output=True).stdout
    from PIL import Image
    import io
    return Image.open(io.BytesIO(raw)).convert('RGB')


def compare(video, dur, ref_path, out, notes):
    from PIL import Image, ImageDraw, ImageFont
    vertical = frame_at(video, 0.5, 64).height > 64
    tw = 300 if vertical else 520
    ts = [dur * k for k in (0.2, 0.5, 0.8)]
    pairs = [(frame_at(video, t, tw), frame_at(video, t, tw, host_vf(t))) for t in ts]
    th = pairs[0][0].height
    refw = tw if ref_path else 0
    pad, top = 16, 48
    pairs_w = (tw + pad) * 2 * (3 if vertical else 1)      # 竖片三组并排，横片三组上下排
    W = pad + pairs_w + (refw + pad if ref_path else 0)
    H = top + (th + pad) * (1 if vertical else 3) + 60
    sheet = Image.new('RGB', (W, H), (246, 246, 242))
    d = ImageDraw.Draw(sheet)
    try:
        fonts.ensure(['noto_sans_sc'], quiet=True)
        F = ImageFont.truetype(fonts.path('noto_sans_sc'), 22)
        Fs = ImageFont.truetype(fonts.path('noto_sans_sc'), 17)
    except Exception:
        F = Fs = ImageFont.load_default()
    for k, (a, b) in enumerate(pairs):
        if vertical:
            x0, y0 = pad + k * 2 * (tw + pad), top
        else:
            x0, y0 = pad, top + k * (th + pad)
        sheet.paste(a, (x0, y0))
        sheet.paste(b, (x0 + tw + pad, y0))
        d.text((x0 + 8, y0 + 6), f'原片 {ts[k]:.0f}s', fill=(255, 255, 255), font=Fs, stroke_width=2, stroke_fill=(0, 0, 0))
        d.text((x0 + tw + pad + 8, y0 + 6), '调色后', fill=(255, 255, 255), font=Fs, stroke_width=2, stroke_fill=(0, 0, 0))
    if ref_path:
        r = Image.open(ref_path).convert('RGB')
        r.thumbnail((refw, H - top - 70))
        rx = W - refw - pad
        sheet.paste(r, (rx, top))
        d.text((rx + 8, top + 6), '参考图', fill=(255, 255, 255), font=Fs, stroke_width=2, stroke_fill=(0, 0, 0))
    d.text((pad, 12), '调色对比（左原片，右调色后）', fill=(30, 30, 40), font=F)
    d.text((pad, H - 46), notes[:90], fill=(70, 70, 70), font=Fs)
    sheet.save(out)


# ---------- 主流程 ----------

def default_video():
    for p in ('口播_粗剪.mp4', 'voice_cut.mp4'):
        if os.path.exists(p):
            return p
    takes = sorted(glob.glob(os.path.join('..', '2_口播视频', '*')))
    return takes[0] if takes else None


def default_ref():
    imgs = [p for p in sorted(glob.glob(os.path.join('..', '4_参考图', '*'))) if p.lower().endswith(IMG_EXT)]
    named = [p for p in imgs if '调色' in os.path.basename(p)]
    return named[0] if named else None


def off(quiet=False):
    for p in glob.glob('grade*.cube') + ['grade.json']:
        if os.path.exists(p):
            os.remove(p)
    if not quiet:
        print('不调色了：口播按原片颜色用')


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'off':
        return off()
    ap = argparse.ArgumentParser()
    ap.add_argument('--ref')
    ap.add_argument('--video')
    ap.add_argument('--strength', type=float, default=0.8)
    a = ap.parse_args()
    video = a.video or default_video()
    if not video:
        sys.exit('找不到口播视频')
    ref_path = a.ref or default_ref()

    frames = video_frames(video)
    if len(frames) == 0:
        sys.exit(f'{video} 没有画面（只有声音就不用调色）')
    labs = [rgb2lab(f.reshape(-1, 3)) for f in frames]
    per_sec = [(float(l[:, 0].mean()), float(l[:, 2].mean())) for l in labs]
    segs = segments(per_sec)
    ref = None
    if ref_path:
        from PIL import Image
        im = Image.open(ref_path).convert('RGB')
        im.thumbnail((320, 320))
        ref = stats(rgb2lab(np.asarray(im, np.float64).reshape(-1, 3) / 255.0))

    off(quiet=True)
    cfg = dict(video=video, ref=ref_path, strength=a.strength, segments=[])
    notes = []
    for k, (s0, s1) in enumerate(segs):
        src = stats(np.concatenate(labs[s0:s1]))
        p = plan(src, ref, a.strength)
        cube = 'grade.cube' if len(segs) == 1 else f'grade_{k + 1}.cube'
        write_cube(cube, p)
        cfg['segments'].append(dict(t0=float(s0), t1=float(s1), cube=cube, src=src, params=p))
        notes.append((f'第 {k + 1} 段 {s0}–{s1}s：' if len(segs) > 1 else '') + describe(src, p))
    json.dump(cfg, open('grade.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    summary = ('照参考图 ' + os.path.basename(ref_path) if ref_path else '默认规则（没有参考图）') + '：' + '；'.join(notes)
    if len(segs) > 1:
        summary += f'（检测到灯光变化，分 {len(segs)} 段各调各的）'
    compare(video, len(frames), ref_path, '调色对比.png', summary)
    print(summary)
    print('对比图：' + os.path.abspath('调色对比.png'))


if __name__ == '__main__':
    main()
