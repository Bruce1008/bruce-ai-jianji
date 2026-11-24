"""Procedural sound effects (48 kHz stereo float32) + mixer."""
import functools
import numpy as np
from scipy import signal

SR = 48000
_rng = np.random.default_rng(7)


def _t(d):
    return np.arange(int(d * SR)) / SR


def _noise(n, seed=None):
    r = np.random.default_rng(seed) if seed is not None else _rng
    return r.standard_normal(n)


def _norm(y):
    m = np.max(np.abs(y)) + 1e-9
    return y / m


def _st(mono, pan=0.0):
    """constant-power pan; pan may be scalar or per-sample array in [-1, 1]"""
    p = (np.asarray(pan) + 1) * np.pi / 4
    return np.stack([mono * np.cos(p), mono * np.sin(p)], 1)


def _sweep_bp(x, fc, q=1.0, block=128):
    out = np.zeros_like(x)
    zi = np.zeros((1, 2))
    for i in range(0, len(x), block):
        f = float(np.clip(fc[min(i, len(fc) - 1)], 60, SR * 0.42))
        bw = f / q
        lo, hi = max(30.0, f - bw / 2), min(SR * 0.47, f + bw / 2)
        sos = signal.butter(1, [lo, hi], btype='band', fs=SR, output='sos')
        y, zi = signal.sosfilt(sos, x[i:i + block], zi=zi)
        out[i:i + block] = y
    return out


def _lp(x, f, order=2):
    return signal.sosfilt(signal.butter(order, f, 'low', fs=SR, output='sos'), x)


def _hp(x, f, order=2):
    return signal.sosfilt(signal.butter(order, f, 'high', fs=SR, output='sos'), x)


def _fade(y, a=0.002, r=0.01):
    n = len(y)
    na, nr = max(1, int(a * SR)), max(1, int(r * SR))
    env = np.ones(n)
    env[:na] = np.linspace(0, 1, na)
    env[-nr:] = np.minimum(env[-nr:], np.linspace(1, 0, nr))
    return y * env if y.ndim == 1 else y * env[:, None]


# ------------------------------------------------------------------ generators
@functools.lru_cache(None)
def whoosh(d=0.55, f0=260.0, f1=3400.0, peak=0.55, pan0=-0.6, pan1=0.6, seed=1):
    n = int(d * SR)
    x = np.arange(n) / n
    up = np.clip(x / peak, 0, 1)
    down = np.clip((x - peak) / (1 - peak), 0, 1)
    fc = f0 * (f1 / f0) ** np.where(x < peak, up ** 1.3, 1 - 0.55 * down)
    y = _sweep_bp(_noise(n, seed), fc, q=0.8)
    body = _lp(_noise(n, seed + 1), 220)
    env = np.where(x < peak, up ** 2.4, np.exp(-down * 4.2))
    y = _norm(y) * env + _norm(body) * env * 0.35
    return _fade(_st(_norm(y), np.linspace(pan0, pan1, n)))


@functools.lru_cache(None)
def swish(d=0.26, f0=1400.0, f1=6500.0, seed=3):
    return whoosh(d, f0, f1, 0.45, -0.2, 0.2, seed)


@functools.lru_cache(None)
def pop(f=520.0, d=0.16):
    t = _t(d)
    fr = f * (1 + 1.1 * np.exp(-t * 55))
    y = np.sin(2 * np.pi * np.cumsum(fr) / SR) * np.exp(-t * 34)
    click = _hp(_noise(len(t), 11), 2500) * np.exp(-t * 900) * 0.25
    return _fade(_st(_norm(y + click)))


@functools.lru_cache(None)
def blip(f=900.0, d=0.12):
    t = _t(d)
    fr = f * (1 + 0.7 * (1 - np.exp(-t * 60)))
    y = (np.sin(2 * np.pi * np.cumsum(fr) / SR) + 0.15 * np.sin(6 * np.pi * np.cumsum(fr) / SR)) * np.exp(-t * 30)
    return _fade(_st(_norm(y)))


@functools.lru_cache(None)
def ding(f=1320.0, d=1.3):
    t = _t(d)
    parts = [(1.0, 1.0, 1.0), (2.0, 0.42, 1.7), (3.01, 0.22, 2.6), (4.17, 0.12, 3.4), (5.43, 0.07, 4.4)]
    L = sum(a * np.sin(2 * np.pi * f * r * t) * np.exp(-t * k * 2.4) for r, a, k in parts)
    R = sum(a * np.sin(2 * np.pi * f * 1.0025 * r * t + 0.3) * np.exp(-t * k * 2.4) for r, a, k in parts)
    y = np.stack([L, R], 1) * np.minimum(1, t / 0.002)[:, None]
    return _fade(y / np.max(np.abs(y)), 0.001, 0.05)


@functools.lru_cache(None)
def click(second=True):
    d = 0.1
    t = _t(d)
    n = len(t)
    def burst(t0, g):
        tt = np.clip(t - t0, 0, None)
        on = (t >= t0).astype(float)
        return on * g * (_hp(_noise(n, 21), 2200) * np.exp(-tt * 1400) * 0.7 + np.sin(2 * np.pi * 3300 * tt) * np.exp(-tt * 700) * 0.5)
    y = burst(0.0, 1.0) + (burst(0.055, 0.55) if second else 0)
    return _fade(_st(_norm(y)), 0.0005, 0.005)


@functools.lru_cache(None)
def key(seed=0):
    d = 0.07
    t = _t(d)
    r = np.random.default_rng(seed)
    y = _sweep_bp(_noise(len(t), seed + 40), np.full(len(t), r.uniform(1800, 3200)), 1.2) * np.exp(-t * 380)
    y = _norm(y) + 0.5 * np.sin(2 * np.pi * r.uniform(150, 210) * t) * np.exp(-t * 110)
    return _fade(_st(_norm(y), r.uniform(-0.25, 0.25)), 0.0005, 0.005)


def typing(d, rate=11.0, seed=5):
    r = np.random.default_rng(seed)
    out = np.zeros((int((d + 0.2) * SR), 2))
    tt = 0.0
    i = 0
    while tt < d:
        k = key(i % 8)
        s = int(tt * SR)
        g = r.uniform(0.6, 1.0)
        out[s:s + len(k)] += k[:len(out) - s] * g
        tt += r.uniform(0.6, 1.4) / rate
        i += 1
    return out


@functools.lru_cache(None)
def impact(d=1.6, low=46.0):
    t = _t(d)
    f = low + 80 * np.exp(-t * 10)
    sub = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 2.6)
    body = _lp(_noise(len(t), 31), 900) * np.exp(-t * 13)
    crack = _hp(_noise(len(t), 32), 3000) * np.exp(-t * 55) * 0.35
    y = np.tanh(1.6 * (_norm(sub) + 0.7 * _norm(body))) + crack
    return _fade(_st(_norm(y)), 0.001, 0.08)


@functools.lru_cache(None)
def thud(f=95.0):
    t = _t(0.3)
    fr = f * (0.55 + 0.45 * np.exp(-t * 25))
    y = np.sin(2 * np.pi * np.cumsum(fr) / SR) * np.exp(-t * 16) + 0.3 * _lp(_noise(len(t), 33), 600) * np.exp(-t * 40)
    return _fade(_st(_norm(y)))


@functools.lru_cache(None)
def riser(d=1.3):
    n = int(d * SR)
    x = np.arange(n) / n
    fc = 300 * (7500 / 300) ** (x ** 1.4)
    yl = _norm(_sweep_bp(_noise(n, 51), fc, 1.1))
    yr = _norm(_sweep_bp(_noise(n, 52), fc, 1.1))
    tone = np.sin(2 * np.pi * np.cumsum(180 * (5 ** x)) / SR) * 0.25
    env = x ** 2.6
    y = np.stack([(yl + tone) * env, (yr + tone) * env], 1)
    return _fade(y / np.max(np.abs(y)), 0.01, 0.015)


@functools.lru_cache(None)
def beep():
    out = np.zeros(int(0.22 * SR))
    for t0 in (0.0, 0.11):
        t = _t(0.075)
        y = (np.sin(2 * np.pi * 2100 * t) + 0.18 * np.sin(2 * np.pi * 6300 * t)) * np.minimum(1, t / 0.003) * np.minimum(1, (0.075 - t) / 0.01)
        s = int(t0 * SR)
        out[s:s + len(y)] += y
    return _st(_norm(out))


@functools.lru_cache(None)
def scratch():
    d = 0.22
    n = int(d * SR)
    x = np.arange(n) / n
    y = _sweep_bp(_noise(n, 61), 4200 * (0.22) ** x, 1.4)
    env = np.minimum(1, x / 0.08) * np.exp(-x * 3)
    return _fade(_st(_norm(y) * env, np.linspace(-0.4, 0.4, n)))


@functools.lru_cache(None)
def flip():
    out = np.zeros((int(0.2 * SR), 2))
    for t0, g in ((0.0, 1.0), (0.07, 0.6)):
        w = whoosh(0.1, 2200.0, 6500.0, 0.35, 0.0, 0.0, 71)
        s = int(t0 * SR)
        out[s:s + len(w)] += w * g
    return out / np.max(np.abs(out))


@functools.lru_cache(None)
def glitch(d=0.38, seed=81):
    r = np.random.default_rng(seed)
    n = int(d * SR)
    y = np.zeros(n)
    i = 0
    while i < n:
        seg = int(r.uniform(0.012, 0.04) * SR)
        t = np.arange(seg) / SR
        kind = r.integers(0, 3)
        if kind == 0:
            s = np.sign(np.sin(2 * np.pi * r.uniform(90, 1400) * t))
        elif kind == 1:
            s = np.round(_noise(seg, int(r.integers(1e6))) * 3) / 3
        else:
            s = np.sin(2 * np.pi * r.uniform(1500, 4000) * t)
        y[i:i + seg] = s[:n - i] * r.uniform(0.3, 1.0) * (r.random() > 0.15)
        i += seg
    y = _lp(y, 7000)
    env = np.minimum(1, np.arange(n) / (0.01 * SR)) * np.linspace(1, 0.5, n)
    return _fade(_st(_norm(y) * env, r.uniform(-0.3, 0.3)), 0.001, 0.02)


@functools.lru_cache(None)
def sparkle(seed=91):
    r = np.random.default_rng(seed)
    out = np.zeros((int(0.9 * SR), 2))
    for k in range(9):
        t0 = r.uniform(0, 0.45)
        f = r.uniform(2600, 5200)
        t = _t(0.35)
        y = np.sin(2 * np.pi * f * t) * np.exp(-t * 14) * np.minimum(1, t / 0.002)
        s = int(t0 * SR)
        out[s:s + len(y)] += _st(y, r.uniform(-0.7, 0.7)) * r.uniform(0.4, 1)
    return out / np.max(np.abs(out))


@functools.lru_cache(None)
def levelup():
    notes = [523.25, 659.25, 783.99, 1046.5]
    out = np.zeros((int(1.1 * SR), 2))
    for i, f in enumerate(notes):
        d = 0.5 if i == 3 else 0.2
        t = _t(d)
        y = (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(6 * np.pi * f * t) + 0.12 * np.sin(10 * np.pi * f * t))
        y = y * np.exp(-t * (5 if i == 3 else 11)) * np.minimum(1, t / 0.004)
        s = int(i * 0.085 * SR)
        out[s:s + len(y)] += _st(_lp(y, 5000))
    return _fade(out / np.max(np.abs(out)), 0.001, 0.05)


@functools.lru_cache(None)
def tick(f=2300.0):
    t = _t(0.035)
    y = np.sin(2 * np.pi * f * t) * np.exp(-t * 260) + 0.25 * _hp(_noise(len(t), 101), 3000) * np.exp(-t * 1100)
    return _fade(_st(_norm(y)), 0.0003, 0.004)


@functools.lru_cache(None)
def buzz():
    t = _t(0.2)
    y = np.sign(np.sin(2 * np.pi * 150 * t)) * 0.6 + np.sin(2 * np.pi * 300 * t) * 0.4
    y = _lp(y, 1800) * np.minimum(1, t / 0.005) * np.minimum(1, (0.2 - t) / 0.03)
    return _st(_norm(y))


@functools.lru_cache(None)
def bonk():
    t = _t(0.28)
    fr = 420 * np.exp(-t * 8) + 110
    y = np.sin(2 * np.pi * np.cumsum(fr) / SR) * np.exp(-t * 14) + 0.2 * _lp(_noise(len(t), 111), 1500) * np.exp(-t * 60)
    return _fade(_st(_norm(y)))


# ---- recorded sounds: CC0 recordings from freesound via Openverse, one-shot sounds
# that synthesis does badly (paper, tape, pen, stamp, shutter, knock ...). Files: <name>.<variant>.wav, mono 16-bit
# 48 kHz, trimmed and peak-normalised, in _工程/sfx/ (copied from the skill's assets/sfx) or the skill itself.
# List and sources: assets/sfx/README.md. Levels in cuelib.G (calibrated against the synthesized sounds).
import os as _os, glob as _glob
from scipy.io import wavfile as _wav

import lib as _lib
_SFX_DIRS = ['sfx', _os.path.join(_lib.SKILL_DIR, 'assets', 'sfx')]


@functools.lru_cache(None)
def sample_files():
    """{name: [path of variant 1, 2, ...]} from the first folder that has recordings"""
    for d in _SFX_DIRS:
        fs = sorted(_glob.glob(_os.path.join(d, '*.*.wav')))
        if fs:
            out = {}
            for f in fs:
                out.setdefault(_os.path.basename(f).split('.')[0], []).append(f)
            return out
    return {}


@functools.lru_cache(None)
def _sample_offsets():
    """per-variant dB offsets (levels.json, written with the library): variants of one name play equally loud"""
    import json as _json
    for d in _SFX_DIRS:
        f = _os.path.join(d, 'levels.json')
        if _os.path.exists(f):
            return _json.load(open(f, encoding='utf-8')).get('offset', {})
    return {}


@functools.lru_cache(None)
def sample(name, v=1, rate=1.0, lp=None, d=None, pan=0.0, rev=False, loop=False):
    """a recording. v: variant (1, 2 ...); rate < 1 plays it lower and slower (0.85 = softer, heavier), > 1 higher;
    lp: low-pass Hz (vertical videos: soft, few highs); d: cut to d seconds with a fade (loop=True repeats it up to
    d first, e.g. pencil under a handwritten note); pan -1..1; rev: reversed"""
    fs = sample_files()[name]
    f = fs[(v - 1) % len(fs)]
    off = _sample_offsets().get(_os.path.basename(f)[:-4], 0.0)
    sr, y = _wav.read(f)
    y = y.astype(np.float64) / (32768.0 if y.dtype == np.int16 else 1.0)
    if y.ndim > 1:
        y = y.mean(1)
    if sr != SR:
        y = signal.resample_poly(y, SR, sr)
    if rate != 1.0:
        y = signal.resample(y, int(len(y) / rate))
    if rev:
        y = y[::-1]
    if lp:
        y = _lp(y, lp, 4)
    if d and loop and len(y) < d * SR:
        k = int(0.03 * SR)                               # 30 ms crossfade between repeats
        out = y.copy()
        while len(out) < d * SR:
            r = np.linspace(0, 1, k)
            out = np.r_[out[:-k], out[-k:] * (1 - r) + y[:k] * r, y[k:]]
        y = out
    if d and len(y) > d * SR:
        y = y[:int(d * SR)]
    return _fade(_st(_norm(y) * 10 ** (off / 20), pan), 0.001, 0.04)


GEN = dict(whoosh=whoosh, swish=swish, pop=pop, blip=blip, ding=ding, click=click, key=key, impact=impact,
           thud=thud, riser=riser, beep=beep, scratch=scratch, flip=flip, glitch=glitch, sparkle=sparkle,
           levelup=levelup, tick=tick, buzz=buzz, bonk=bonk)


def render_cue(name, kw):
    kw = {k: v for k, v in kw.items() if not k.startswith('_')}       # '_anchor' is timing info, not a param
    if name == 'typing':
        return typing(**kw)
    if name in GEN:
        return GEN[name](**kw)
    return sample(name, **kw)


def mix(cues, n_samples):
    bus = np.zeros((n_samples, 2), np.float64)
    for t, name, db, kw in cues:
        y = render_cue(name, kw)
        s = int(round(t * SR))
        if s >= n_samples: continue
        if s < 0:
            y = y[-s:]; s = 0
        e = min(n_samples, s + len(y))
        bus[s:e] += y[:e - s] * (10 ** (db / 20))
    return bus
