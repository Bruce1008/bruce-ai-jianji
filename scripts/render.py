"""合成：把 scenes.py 里的时间线画成视频画面（不含声音，声音由 mix_master.py 混）。

版式（layout.py）：
  横屏 1920x1080：画面全屏 + 左上角人物小窗；host=True 的条目小窗平滑放大成人物全屏，下一个条目开始时缩回。
  竖屏 1080x1920：画面全屏 ⇄ 人物全屏，host=True 是普通场景，前后走普通转场。
风格（theme.py）：字幕样式 T.sub(c, s, x, y, size, maxw)、小窗边框 T.pip_frame(c, x, y, w, h, r, a)、
  额外转场 T.TRANSITIONS = {名字: fn(c, A, B, x, fidx)}。

scenes.py（在 _工程 里，每条视频自己写）：
  VOICE        粗剪后的口播（mp4，或只有声音的 wav/mp3 = 不露脸模式）
  TIMELINE     [dict(t=秒, mg=画面函数 | clip=(路径, 起点, 速度, crop) | host=True, tr=转场, td=转场秒数,
                     ov=叠加函数, pip=False 隐藏小窗, hold=N, done=秒)]
  CHAPTERS     [(秒, '章节名')]（只用来分段，不画出来）
  可选：HOST_FOCUS=(x, y) 两眼中间在原片里的位置、PIP_ZOOM 小窗松紧（不写就用 framing.py 存在 project.json 里的），
               HOST_VF（额外的 ffmpeg 滤镜），SUBS_FILE，HOST_D，MIN_HOLD
  画面函数签名 fn(c, t, S)：c 是 skia 画布（整个画面），t 是口播时间（秒），S 是这个场景（S.clip(...) 取视频帧）

用法（在 _工程 里运行）：
  python render.py stills t1 t2 ...         -> stills/fXXXX.XX.png（口播时间）
  python render.py holds                    -> 打印「停留N秒」的定格安排
  python render.py video [out.mp4] [t0 t1]  -> 只有画面的 H.264（+ out.holds.json 给 mix_master.py）；t0 t1 = 只渲这一段
  加 --nosub：不画字幕（出无字幕版）
"""
import sys, os, math, subprocess, time, json, bisect
import tools
import numpy as np
import skia
import theme as T
from lib import *
from lib import _td
import lib
import layout as L
import holds
import grade
import scenes as SC

FFMPEG = tools.FFMPEG
FFPROBE = tools.FFPROBE


def probe(path):
    out = subprocess.run([FFPROBE, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                          'stream=width,height:stream_side_data=rotation', '-of', 'json', path],
                         capture_output=True, text=True).stdout
    st = json.loads(out).get('streams') or []
    d = subprocess.run([FFPROBE, '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                       capture_output=True, text=True).stdout
    dur = float(d.strip() or 0)
    if not st:                       # 只有声音（不露脸模式）
        return 0, 0, dur
    s = st[0]
    w, h = int(s['width']), int(s['height'])
    rot = 0
    for sd in s.get('side_data_list', []) or []:
        rot = int(sd.get('rotation', 0) or 0)
    if abs(rot) in (90, 270):
        w, h = h, w
    return w, h, dur


VOICE = SC.VOICE
_VW, _VH, DUR = probe(VOICE)
NF = int(DUR * FPS)
HAS_HOST = _VW > 0 and not getattr(SC, 'NO_HOST', False)
_FOCUS0, _ZOOM0 = L.host_setting()                 # framing.py 存在 project.json 里的
FOCUS = getattr(SC, 'HOST_FOCUS', _FOCUS0)
PIP_ZOOM = getattr(SC, 'PIP_ZOOM', _ZOOM0)
HOST_CROP, _HOST_UP = L.host_crop(_VW, _VH, FOCUS) if HAS_HOST else (None, 1.0)
if HAS_HOST and _HOST_UP > 1.6:
    print(f'注意：口播原片 {_VW}x{_VH} 和成片方向不一致，人物全屏要放大 {_HOST_UP:.1f} 倍，会有点糊', flush=True)
_EXTRA_VF = getattr(SC, 'HOST_VF', None)


def HOST_VF(ss):
    """读口播时的滤镜：调色 LUT（grade.py 生成，分段时按读取起点平移时间）+ scenes.py 里额外的 HOST_VF"""
    return ','.join(x for x in [grade.host_vf(ss), _EXTRA_VF] if x) or None


def _host_read():
    """横屏人物层只读原片里「全屏那块 ∪ 小窗那块」：小窗直接从原片裁，竖拍做横屏时也露出整个头和肩。
    返回 (ffmpeg crop, 读出来的尺寸, 全屏那块, 小窗那块)，后两个是读出来那张图里的坐标"""
    full, pip = L.host_rects(_VW, _VH, FOCUS, PIP_ZOOM)
    x0 = int(min(full[0], pip[0])) // 2 * 2
    y0 = int(min(full[1], pip[1])) // 2 * 2
    x1 = max(full[0] + full[2], pip[0] + pip[2])
    y1 = max(full[1] + full[3], pip[1] + pip[3])
    uw = min(_VW - x0, int(math.ceil((x1 - x0) / 2)) * 2)
    uh = min(_VH - y0, int(math.ceil((y1 - y0) / 2)) * 2)
    s = min(1.0, W / full[2])                          # 全屏那块比成片宽时缩小读，省内存
    rw, rh = max(2, int(uw * s) // 2 * 2), max(2, int(uh * s) // 2 * 2)
    kx, ky = rw / uw, rh / uh
    to = lambda r: ((r[0] - x0) * kx, (r[1] - y0) * ky, r[2] * kx, r[3] * ky)
    return f'{uw}:{uh}:{x0}:{y0}', (rw, rh), to(full), to(pip)


if HAS_HOST and not VERTICAL:
    HOST_READ, HOST_SIZE, FULL_SRC, PIP_SRC = _host_read()
SUBS_FILE = getattr(SC, 'SUBS_FILE', 'subs.srt')


class Reader:
    """顺序读帧：输出时间 t -> skia.Image（RGBA）"""
    def __init__(self, path, src, speed, t_ref, size, crop=None, lead=0.0, vf_extra=None):
        self.size = size
        ss = max(0.0, src - lead * speed)
        self.first_t = t_ref - (src - ss) / speed
        w, h = size
        vf = []
        if crop: vf.append(f'crop={crop}')
        if callable(vf_extra): vf_extra = vf_extra(ss)
        if vf_extra: vf.append(vf_extra)
        vf += [f'setpts=(PTS-STARTPTS)/{speed}', f'fps={FPS}',
               f'scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos', f'crop={w}:{h}']
        cmd = [FFMPEG, '-v', 'error', '-ss', f'{ss:.3f}', '-i', path, '-vf', ','.join(vf),
               '-f', 'rawvideo', '-pix_fmt', 'rgba', '-']
        self.p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=w * h * 4 * 4)
        self.fs = w * h * 4
        self.idx = -1
        self.img = None
        self.eof = False

    def get(self, t):
        k = max(0, int(round((t - self.first_t) * FPS)))
        while self.idx < k and not self.eof:
            buf = self.p.stdout.read(self.fs)
            if len(buf) < self.fs:
                self.eof = True
                break
            self.idx += 1
            if self.idx >= k or self.img is None:
                arr = np.frombuffer(buf, np.uint8).reshape(self.size[1], self.size[0], 4)
                self.img = skia.Image.fromarray(arr, colorType=skia.ColorType.kRGBA_8888_ColorType)
        return self.img

    def close(self):
        try:
            self.p.kill(); self.p.wait()
        except Exception:
            pass


class Scene:
    """一个 TIMELINE 条目"""
    def __init__(self, d, t1, tr=None):
        self.d = d
        self.t0 = d['t']
        self.t1 = t1
        self.tr = tr or d.get('tr', lib.DEFAULT_TR)
        self.td = 0.0 if self.tr == 'cut' else _td(d)
        self.readers = {}

    def clip(self, key, path, src, speed=1.0, t_ref=None, size=None, crop=None, lead=0.45, vf=None):
        """画面函数里嵌视频：返回 Reader（.get(t) 取帧）。src = 原片起点秒数，t_ref = 这一帧对应的口播时间"""
        if key not in self.readers:
            self.readers[key] = Reader(path, src, speed, self.t0 if t_ref is None else t_ref, size or (W, H),
                                       crop, lead, vf)
        return self.readers[key]

    def render(self, c, t):
        d = self.d
        if d.get('host'):                        # 竖屏：人物全屏场景
            img = self.clip('host', VOICE, self.t0, 1.0, self.t0, (W, H), HOST_CROP, vf=HOST_VF).get(t)
            c.clear(col(BLACK))
            if img is not None:
                z = d.get('zoom', 1.0)
                z = z(t) if callable(z) else z
                with xf(c, CX, H * 0.42, z):
                    c.drawImageRect(img, skia.Rect.MakeWH(W, H), SAMP, None)
        elif 'mg' in d:
            d['mg'](c, t, self)
        else:
            path, src, speed, crop = d['clip']
            img = self.clip('main', path, src, speed, self.t0, (W, H), crop).get(t)
            c.clear(col(BLACK))
            if img is not None:
                c.drawImageRect(img, skia.Rect.MakeWH(W, H), SAMP, None)
        if 'ov' in d:
            d['ov'](c, t, self)

    def close(self):
        for r in self.readers.values():
            r.close()
        self.readers = {}


# ---------------------------------------------------------------- 转场
def blur_paint(sx, sy, a=1.0):
    p = skia.Paint(AntiAlias=True)
    if sx > 0.5 or sy > 0.5:
        p.setImageFilter(skia.ImageFilters.Blur(max(sx, 0.01), max(sy, 0.01), skia.TileMode.kClamp))
    p.setAlphaf(clamp(a))
    return p


def _di(c, img, x, y, p=None):
    c.drawImageRect(img, skia.Rect.MakeXYWH(x, y, W, H), SAMP, p)


def transition(c, A, B, x, kind, fidx):
    """内置：push slideup zoom wipe flash fade glitch cut；风格可以在 T.TRANSITIONS 里加自己的"""
    extra = getattr(T, 'TRANSITIONS', {})
    if kind not in extra and kind not in ('push', 'slideup', 'zoom', 'wipe', 'flash', 'fade', 'glitch', 'cut'):
        kind = lib.DEFAULT_TR          # 换了风格，原来那个风格专有的转场名这里没有：用这个风格的默认转场
    if kind in extra:
        extra[kind](c, A, B, x, fidx)
        return
    c.clear(col(BLACK))
    k = math.sin(math.pi * x)
    if kind == 'push':
        e = e_io(x)
        p = blur_paint(38 * k, 0)
        _di(c, A, -e * W, 0, p)
        _di(c, B, (1 - e) * W, 0, p)
    elif kind == 'slideup':
        e = e_io(x)
        _di(c, A, 0, -e * H * 0.35, blur_paint(0, 20 * k, 1 - 0.6 * e))
        _di(c, B, 0, (1 - e) * H, blur_paint(0, 34 * k))
    elif kind == 'zoom':
        e = e_io(x)
        with xf(c, CX, CY, 1 + 0.35 * e):
            _di(c, A, 0, 0, blur_paint(16 * k, 16 * k, 1 - e_in(clamp(x * 1.4))))
        with xf(c, CX, CY, 0.78 + 0.22 * e):
            _di(c, B, 0, 0, blur_paint(16 * k, 16 * k, e_out(clamp(x * 1.6 - 0.3))))
    elif kind == 'wipe':
        e = e_io(x)
        _di(c, A, 0, 0, None)
        edge = lambda y: lerp(W + 260, -300, e) + (y - H / 2) * 0.32
        path = skia.Path()
        path.moveTo(edge(0), 0); path.lineTo(W + 400, 0); path.lineTo(W + 400, H); path.lineTo(edge(H), H); path.close()
        c.save(); c.clipPath(path, skia.ClipOp.kIntersect, True)
        _di(c, B, 0, 0, None)
        c.restore()
        for off, w, clr in ((0, 46, ACC), (46, 14, ACC2)):
            band = skia.Path()
            band.moveTo(edge(0) + off, 0); band.lineTo(edge(0) + off + w, 0)
            band.lineTo(edge(H) + off + w, H); band.lineTo(edge(H) + off, H); band.close()
            c.drawPath(band, paint(clr))
    elif kind == 'flash':
        if x < 0.5:
            _di(c, A, 0, 0, None)
            c.drawRect(skia.Rect.MakeWH(W, H), paint(WHITE, e_in(x * 2)))
        else:
            with xf(c, CX, CY, 1.06 - 0.06 * e_out((x - 0.5) * 2)):
                _di(c, B, 0, 0, None)
            c.drawRect(skia.Rect.MakeWH(W, H), paint(WHITE, 1 - e_out((x - 0.5) * 2)))
    elif kind == 'fade':
        _di(c, A, 0, 0, None)
        _di(c, B, 0, 0, blur_paint(0, 0, e_io(x)))
    elif kind == 'glitch':
        base = A if x < 0.5 else B
        _di(c, base, 0, 0, None)
        rng = np.random.default_rng(fidx * 7 + 3)
        for _ in range(8):
            y = rng.uniform(0, H); h = rng.uniform(8, 70)
            dx = rng.uniform(-1, 1) * 110 * k
            c.save(); c.clipRect(skia.Rect.MakeXYWH(0, y, W, h))
            _di(c, base, dx, 0, None)
            c.restore()
        for clr, sgn in (((255, 0, 80), 1), ((0, 220, 255), -1)):
            p = skia.Paint()
            p.setColorFilter(skia.ColorFilters.Blend(col(clr), skia.BlendMode.kMultiply))
            p.setBlendMode(skia.BlendMode.kScreen)
            p.setAlphaf(0.55 * k)
            _di(c, base, sgn * 16 * k, 0, p)
    else:
        _di(c, A if x < 0.5 else B, 0, 0, None)


# ---------------------------------------------------------------- 渲染器
class Renderer:
    def __init__(self, plan=False):
        tl = SC.TIMELINE
        self.windows = full_windows(SC) if HAS_HOST else []
        self.scenes, self.idx = [], []
        prev_host = False
        for i, d in enumerate(tl):
            if d.get('host') and not HAS_HOST:
                raise SystemExit(f'TIMELINE 第 {i} 条是 host=True，但口播没有画面（不露脸模式）')
            if d.get('host') and not VERTICAL:          # 横屏：人物是一层，不是场景
                prev_host = True
                continue
            j = next((k for k in range(i + 1, len(tl)) if VERTICAL or not tl[k].get('host')), None)
            t1 = tl[j]['t'] if j is not None else DUR + 1
            # 横屏：人物全屏挡住时换的画面，直接切（看不见）
            self.scenes.append(Scene(d, t1, 'cut' if (prev_host and not VERTICAL) else None))
            self.idx.append(i)
            prev_host = False
        if not self.scenes:
            raise SystemExit('TIMELINE 里至少要有一个画面条目')
        self.frame = np.zeros((H, W, 4), np.uint8)
        self.surf = skia.Surface(self.frame, colorType=skia.ColorType.kRGBA_8888_ColorType,
                                 alphaType=skia.AlphaType.kPremul_AlphaType)
        self.buf = [skia.Surface(W, H) for _ in range(3)]
        self.holds, self.warn = self.plan_holds() if plan else ([], [])
        self.tm = holds.TimeMap(self.holds, DUR)
        self.host = Reader(VOICE, 0.0, 1.0, 0.0, HOST_SIZE, crop=HOST_READ, vf_extra=HOST_VF) \
            if (HAS_HOST and not VERTICAL) else None
        self.subs = self.tm.subs(load_srt(SUBS_FILE)) if os.path.exists(SUBS_FILE) else []
        if not self.subs:
            print(f'注意：没有 {SUBS_FILE}，先不带字幕（用 make_subs.py 做）', flush=True)
        self.sub_t0 = [s_[0] for s_ in self.subs]
        self.closed = set()
        self.pip_on = self._pip_table()

    def _pip_table(self):
        """横屏：每个画面条目要不要显示小窗（pip=False 的条目隐藏）-> [(t, 0/1)]"""
        out = []
        for sc in self.scenes:
            out.append((sc.t0, 0.0 if sc.d.get('pip') is False else 1.0))
        return out

    def pip_amount(self, t):
        """小窗显隐，0.3 秒淡入淡出"""
        if not self.pip_on: return 1.0
        cur = 1.0
        for i, (t0, a) in enumerate(self.pip_on):
            if t < t0 - 0.15: break
            prev = self.pip_on[i - 1][1] if i else a
            cur = lerp(prev, a, e_io(prog(t, t0 - 0.15, 0.3)))
        return cur

    def plan_holds(self):
        surf = self.buf[0]

        def draw(i, t):
            if i not in self.idx: return
            sc = self.scenes[self.idx.index(i)]
            c = surf.getCanvas()
            c.save(); sc.render(c, t); c.restore()
            sc.close()
        done = holds.measure_done(SC, DUR, draw)
        return holds.plan(SC, DUR, done, self.windows, holds.voice_env(VOICE))

    def scene_img(self, sc, surf, t):
        c = surf.getCanvas()
        c.save()
        sc.render(c, t)
        c.restore()
        return surf.makeImageSnapshot()

    def stage(self, t, fidx):
        sa, sb, sst = self.buf
        S = self.scenes
        i = max([j for j, s in enumerate(S) if s.t0 <= t] or [0])
        pair = None
        if i > 0 and S[i].td > 0 and t < S[i].t0 + S[i].td / 2:
            pair = (S[i - 1], S[i], (t - (S[i].t0 - S[i].td / 2)) / S[i].td)
        elif i + 1 < len(S) and S[i + 1].td > 0 and t >= S[i + 1].t0 - S[i + 1].td / 2:
            pair = (S[i], S[i + 1], (t - (S[i + 1].t0 - S[i + 1].td / 2)) / S[i + 1].td)
        if pair:
            A = self.scene_img(pair[0], sa, t)
            B = self.scene_img(pair[1], sb, t)
            c = sst.getCanvas()
            c.save()
            transition(c, A, B, clamp(pair[2]), pair[1].tr, fidx)
            c.restore()
            img = sst.makeImageSnapshot()
        else:
            img = self.scene_img(S[i], sa, t)
        for j, s in enumerate(S):
            if j in self.closed: continue
            nxt = S[j + 1] if j + 1 < len(S) else None
            if nxt and t > nxt.t0 + nxt.td / 2 + 0.1:
                s.close(); self.closed.add(j)
        return img

    def draw_host(self, c, ta, f, pa):
        """横屏人物层：f = 0 小窗，1 全屏；pa = 小窗显示程度"""
        a = max(f, pa)
        if a <= 0.001: return
        img = self.host.get(ta)
        if img is None: return
        px, py, pw, ph, pr = L.PIP
        x, y, w, h, r = lerp(px, 0, f), lerp(py, 0, f), lerp(pw, W, f), lerp(ph, H, f), pr * (1 - f)
        src = skia.Rect.MakeXYWH(*(lerp(a_, b_, f) for a_, b_ in zip(PIP_SRC, FULL_SRC)))
        s = lerp(0.85, 1.0, e_out(pa)) if f < 0.001 else 1.0
        with xf(c, x + w / 2, y + h / 2, s, a=1.0 if f > 0 else pa):
            if f < 1:
                lift = 1 - f
                c.save(); c.translate(0, 10)
                c.drawRRect(rrect(x, y, w, h, r), paint(BLACK, 0.28 * lift, blur=22))
                c.restore()
            c.save(); c.clipRRect(rrect(x, y, w, h, r), True)
            c.drawImageRect(img, src, skia.Rect.MakeXYWH(x, y, w, h), SAMP, None, skia.Canvas.kFast_SrcRectConstraint)
            c.restore()
            if f < 1 and hasattr(T, 'pip_frame'):
                T.pip_frame(c, x, y, w, h, r, 1 - f)

    def draw_sub(self, c, t):
        if NOSUB:
            return
        i = bisect.bisect_right(self.sub_t0, t) - 1
        if i < 0 or t >= self.subs[i][1]:
            return
        T.sub(c, self.subs[i][2], CX, L.SUB_Y, L.SUB_SIZE, L.SUB_MAXW)

    def render(self, o, fidx):
        """输出时间 o 的一帧：画面显示口播时间 t（定格时停住），人物显示口播时间 ta（声音停顿时停住）"""
        t, _ = self.tm.pic(o)
        ta, _ = self.tm.aud(o)
        fo = prog(o, self.tm.dur - 0.4, 0.4)
        c = self.surf.getCanvas()
        f = full_amount(t, self.windows) if self.host else 0.0
        if f < 0.999:
            c.drawImage(self.stage(t, fidx), 0, 0)
        if self.host:
            self.draw_host(c, ta, f, self.pip_amount(t))
        self.draw_sub(c, o)
        if fo > 0:
            c.drawRect(skia.Rect.MakeWH(W, H), paint(BLACK, fo))
        return self.frame


NOSUB = '--nosub' in sys.argv
if NOSUB:
    sys.argv.remove('--nosub')


def main():
    mode = sys.argv[1]
    if mode == 'stills':
        os.makedirs('stills', exist_ok=True)
        ts = sorted(float(x) for x in sys.argv[2:])
        R = Renderer()
        for t in ts:
            fidx = int(round(t * FPS))
            fr = R.render(fidx / FPS, fidx)
            skia.Image.fromarray(fr.copy(), colorType=skia.ColorType.kRGBA_8888_ColorType).save(f'stills/f{t:07.2f}.png')
            print('saved', f'stills/f{t:07.2f}.png')
    elif mode == 'holds':
        R = Renderer(plan=True)
        holds.report(R.holds, R.warn, DUR)
    elif mode == 'video':
        out = sys.argv[2] if len(sys.argv) > 2 else 'video_only.mp4'
        R = Renderer(plan=True)
        holds.report(R.holds, R.warn, DUR)
        holds.save(os.path.splitext(out)[0] + '.holds.json', R.holds, R.warn, DUR)
        tm = R.tm
        o0 = tm.pic_o(float(sys.argv[3])) if len(sys.argv) > 3 else 0.0
        o1 = tm.pic_o(float(sys.argv[4])) if len(sys.argv) > 4 else tm.dur
        f0, f1 = int(round(o0 * FPS)), min(int(tm.dur * FPS), int(round(o1 * FPS)))
        rng = os.path.splitext(out)[0] + '.range.json'
        if len(sys.argv) > 3:
            json.dump(dict(o0=f0 / FPS, o1=f1 / FPS), open(rng, 'w', encoding='utf-8'))
        elif os.path.exists(rng):
            os.remove(rng)
        enc = subprocess.Popen([FFMPEG, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f'{W}x{H}',
                                '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18',
                                '-pix_fmt', 'yuv420p', '-color_primaries', 'bt709', '-color_trc', 'bt709',
                                '-colorspace', 'bt709', out], stdin=subprocess.PIPE)
        st = time.time()
        for fi in range(f0, f1):
            fr = R.render(fi / FPS, fi)
            enc.stdin.write(fr.data)
            if fi % 300 == 0:
                el = time.time() - st
                print(f'第 {fi}/{f1} 帧  t={fi / FPS:.1f}s  {(fi - f0 + 1) / max(el, 1e-6):.1f} 帧/秒', flush=True)
        enc.stdin.close(); enc.wait()
        print('完成', round(time.time() - st, 1), '秒 ->', out)


if __name__ == '__main__':
    main()
