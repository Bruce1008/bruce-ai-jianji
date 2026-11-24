"""Audio: process voice, add synthesized SFX, master, mux with the rendered picture.

usage: python mix_master.py <final_output.mp4> [--video video_only.mp4] [--audio-only]

voice : highpass 70 Hz + gentle compression, then linear gain to -16 LUFS
gate  : noise gate: wherever the voice is below GATE_DB (default -40 dB, 20 ms RMS, measured
        after the -16 LUFS gain) it is muted, so room noise / hum between sentences is gone. Speech keeps an 80 ms
        look-ahead and 220 ms hold so word onsets and tails are not chopped. scenes.py: GATE_DB = -38 (stricter
        than -40 keeps more noise out, looser keeps softer word endings), GATE_DB = None to switch it off.
holds : the voice pauses (silence) where render.py froze the talking head; SFX move with the picture
        (<video>.holds.json, written by render.py)
sfx   : cues.all_cues() rendered by sfx.py (levels from cuelib.G)
master: whole mix to -14 LUFS (抖音/小红书), limiter at 0.74 (-2.6 dBFS) so the AAC-encoded peak stays ≤ -1 dBFS
        (AAC lands ~1.2 dB above the limiter: 0.82 came out at -0.6 dBFS on 1102; 1015 needed 0.74 too), AAC 256k
bgm   : 可选。scenes.py 里 BGM = '../5_BGM/xxx.mp3'（或工程 5_BGM/ 里只有一首时自动用它）：循环或截到成片长度，
        接缝 2 秒交叉淡化，开头 1 秒淡入、结尾 3 秒淡出，整体比人声低 BGM_DB（默认 20）dB。没有就不加。
"""
import sys, os, subprocess, argparse
import tools
import numpy as np
import pyloudnorm as pyln
from scipy.io import wavfile
import scenes as SC
import cues
import sfx
import holds

ap = argparse.ArgumentParser()
ap.add_argument('out')
ap.add_argument('--video', default='video_only.mp4')
ap.add_argument('--audio-only', action='store_true')
a = ap.parse_args()


def noise_gate(v, sr, thr, hold=0.22, look=0.08, blip=0.03, fade=0.02):
    """mute v (n, ch) wherever its 20 ms RMS stays under thr dB; returns (gated v, muted fraction)"""
    hop = sr // 100
    n = len(v) // hop
    p = (v[:n * hop].mean(1).reshape(n, hop) ** 2).mean(1)
    lv = 10 * np.log10(np.convolve(p, np.ones(2) / 2, 'same') + 1e-12)
    op = lv > thr
    d = np.diff(np.r_[0, op.astype(np.int8), 0])
    for s, e in zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]):
        if e - s < round(blip * 100):                       # a click or bump shorter than any syllable
            op[s:e] = False
    lk, hd = round(look * 100), round(hold * 100)
    op = np.convolve(op.astype(np.float64), np.ones(lk + hd + 1))[lk:lk + n] > 0.5
    m = np.repeat(op.astype(np.float64), hop)
    m = np.r_[m, np.full(len(v) - len(m), m[-1] if len(m) else 1.0)]
    k = int(fade * sr)
    c = np.cumsum(np.r_[np.zeros(k // 2), m, np.full(k - k // 2, m[-1])])
    m = (c[k:] - c[:-k])[:len(v)] / k                        # 20 ms fade in / out at each gate edge
    return v * m[:, None], 1 - op.mean()


subprocess.run([tools.FFMPEG, '-v', 'error', '-y', '-i', SC.VOICE, '-vn', '-ac', '2', '-ar', '48000', '-af',
                'highpass=f=70,acompressor=threshold=-28dB:ratio=2.5:attack=8:release=180:knee=6',
                '-c:a', 'pcm_f32le', 'voice_comp.wav'], check=True)
sr, v = wavfile.read('voice_comp.wav')
v = v.astype(np.float64)
meter = pyln.Meter(sr)
lv = meter.integrated_loudness(v)
v *= 10 ** ((-16.0 - lv) / 20)
print(f'voice {lv:.1f} LUFS -> -16.0 LUFS (gain {-16.0 - lv:+.1f} dB)')

thr = getattr(SC, 'GATE_DB', -40.0)
if thr is not None:
    r = 20 * np.log10(np.sqrt((v[:len(v) // 960 * 960].mean(1).reshape(-1, 960) ** 2).mean(1)) + 1e-12)
    floor = float(np.percentile(r, 10))
    if floor > thr - 6:
        print(f'WARNING: noise floor {floor:.0f} dB is close to the gate ({thr:.0f} dB): raised to {min(floor + 6, -34):.0f} dB'
              f' — a noisy take; check soft word endings')
        thr = min(floor + 6, -34.0)
    v, muted = noise_gate(v, sr, thr)
    print(f'noise gate {thr:.0f} dB: noise floor {floor:.0f} dB, {muted:.0%} of the take muted')

dur = len(v) / sr
hf = os.path.splitext(a.video)[0] + '.holds.json'
if os.path.exists(hf):
    tm = holds.TimeMap(holds.load(hf), dur)
    v = tm.voice(v, sr)
    print(f'{len(tm.A)} voice pauses from {hf}: +{tm.dur - dur:.1f} s -> {len(v) / sr:.1f} s')
else:
    tm = holds.TimeMap([], dur)
    print(f'NOTE: no {hf} (render.py video writes it) — mixing without freeze holds')

def load_bgm(n, sr):
    path = getattr(SC, 'BGM', None)
    if path is None:
        d = os.path.join('..', '5_BGM')
        fs = sorted(f for f in os.listdir(d) if f.lower().endswith(('.mp3', '.wav', '.m4a', '.aac', '.flac'))) \
            if os.path.isdir(d) else []
        path = os.path.join(d, fs[0]) if len(fs) == 1 else None
        if len(fs) > 1:
            print(f'NOTE: 5_BGM 里有 {len(fs)} 首，scenes.py 里用 BGM = 指定一首')
    if not path:
        return None
    subprocess.run([tools.FFMPEG, '-v', 'error', '-y', '-i', path, '-vn', '-ac', '2', '-ar', str(sr), '-c:a', 'pcm_f32le',
                    '_bgm.wav'], check=True)
    _, b = wavfile.read('_bgm.wav')
    b = b.astype(np.float64)
    xf = int(2.0 * sr)
    out = b.copy()
    while len(out) < n:                        # loop with a 2 s crossfade at each seam
        k = min(xf, len(out), len(b))
        ramp = np.linspace(0, 1, k)[:, None]
        out = np.concatenate([out[:-k], out[-k:] * (1 - ramp) + b[:k] * ramp, b[k:]])
    out = out[:n]
    fi, fo = int(1.0 * sr), int(3.0 * sr)
    out[:fi] *= np.linspace(0, 1, fi)[:, None]
    out[-fo:] *= np.linspace(1, 0, fo)[:, None]
    lb = meter.integrated_loudness(out)
    target = -16.0 - getattr(SC, 'BGM_DB', 20.0)
    out *= 10 ** ((target - lb) / 20)
    print(f'BGM {os.path.basename(path)}: {lb:.1f} LUFS -> {target:.1f} LUFS（比人声低 {getattr(SC, "BGM_DB", 20.0):.0f} dB）')
    return out


cl = [tm.cue(c) for c in cues.all_cues() if c]
bus = sfx.mix(cl, len(v))
print(f'{len(cl)} SFX cues, sfx peak {20 * np.log10(np.abs(bus).max() + 1e-12):.1f} dBFS')
mix = v + bus
bgm = load_bgm(len(mix), sr)
if bgm is not None:
    mix = mix + bgm
rng = os.path.splitext(a.video)[0] + '.range.json'
if os.path.exists(rng):                       # the video is a segment (render.py video out t0 t1): cut the mix to it
    import json
    r_ = json.load(open(rng, encoding='utf-8'))
    mix = mix[int(round(r_['o0'] * sr)):int(round(r_['o1'] * sr))].copy()
    k = int(0.25 * sr)
    mix[-k:] *= np.linspace(1, 0, k)[:, None]
    print(f"segment {r_['o0']:.2f}-{r_['o1']:.2f} s ({rng})")
lm = meter.integrated_loudness(mix)
master = -14.0 - lm
wavfile.write('mix_pre.wav', sr, mix.astype(np.float32))
print(f'mix {lm:.1f} LUFS, master gain {master:+.1f} dB -> mix_pre.wav')
if a.audio_only:
    sys.exit(0)

subprocess.run([tools.FFMPEG, '-v', 'error', '-y', '-i', a.video, '-i', 'mix_pre.wav', '-map', '0:v', '-map', '1:a',
                '-c:v', 'copy', '-af', f'volume={master:.2f}dB,alimiter=limit=0.74:attack=3:release=60:level=disabled',
                '-c:a', 'aac', '-b:a', '256k', '-ar', '48000', '-shortest', '-movflags', '+faststart', a.out], check=True)
r = subprocess.run([tools.FFMPEG, '-hide_banner', '-nostats', '-i', a.out, '-vn', '-af', 'ebur128=peak=true', '-f', 'null', '-'],
                   capture_output=True, text=True).stderr
summary = r[r.rfind('Summary:'):]
for line in summary.splitlines():
    if 'I:' in line or 'Peak:' in line:
        print('final', line.strip())
print('->', a.out)

# 字幕文件（成片时间，含定格），放在成片旁边：发 B 站、YouTube 时单独上传。只渲了一段（预览）时不写
SUBS = getattr(SC, 'SUBS_FILE', 'subs.srt')
if not os.path.exists(rng) and os.path.exists(SUBS):
    from lib import load_srt

    def _ts(s):
        ms = int(round(max(s, 0) * 1000))
        return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'
    srt = os.path.join(os.path.dirname(os.path.abspath(a.out)), '字幕.srt')
    with open(srt, 'w', encoding='utf-8') as f:
        for k, (s, e, txt) in enumerate(tm.subs(load_srt(SUBS)), 1):
            f.write(f'{k}\n{_ts(s)} --> {_ts(e)}\n{txt}\n\n')
    print('->', srt)
