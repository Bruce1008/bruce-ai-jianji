"""SFX cue helpers. A cue = (time_s, effect_name, gain_dBFS, kwargs).

Levels in G were calibrated on the 0929 video: after voice processing (-16 LUFS) these put
transition whooshes ~9 dB and UI pops/clicks ~10-15 dB under the voice, which read as
"clearly audible but never covering speech". Adjust per cue with the db offset, not by editing G.

Cue times are on the voice timeline. When holds.py freezes a finished page, mix_master.py moves every cue with
the picture. A cue that leads its visual event (a whoosh starting 0.3 s before its transition) passes anchor=<the
event's time>, so it stays glued to that event instead of firing before the freeze.
"""
from lib import e_out, e_io, prog, lerp, full_windows

G = dict(whoosh=-11, swish=-14, pop=-12, blip=-16, ding=-21, click=-10, impact=-11, thud=-12, riser=-15,
         beep=-22, scratch=-13, flip=-15, glitch=-14, sparkle=-23, levelup=-20, tick=-15, buzz=-22, bonk=-14,
         typing=-15, key=-15)


# recorded sounds (sfx.sample, 2026-11-23): their levels come with the library (levels.json), each one as loud as the
# synthesized sound it replaces
try:
    import json as _json, os as _os
    import sfx as _sfx
    for _d in _sfx._SFX_DIRS:
        _f = _os.path.join(_d, 'levels.json')
        if _os.path.exists(_f):
            for _k, _v in _json.load(open(_f, encoding='utf-8'))['G'].items():
                G.setdefault(_k, _v)
            break
except Exception as _e:                      # no library: synthesized sounds only
    print('NOTE: recorded SFX levels not loaded:', _e)


# 按「画面动作」起名的音效：cue(t, '@drop')。每个风格在 theme.SFX 里决定用哪个声音（同一份 cues.py 换风格不用改）。
# 值 = (音效名, dB, {参数}) 或 None（这个风格这类动作不出声）
SFX_DEFAULT = {
    'write': ('pen', -8), 'drop': ('paper_drop', -6), 'pop': ('pop', -4), 'mark': ('marker', -4),
    'stamp': ('stamp', 0), 'stick': ('tape', -8), 'tick': ('pen', -6), 'number': ('pop', -3), 'whoosh': ('whip', -4),
}


def _theme():
    import sys
    return sys.modules.get('theme')


def cue(t, name, db=0.0, anchor=None, **kw):
    """db = offset from the base level of that effect; kw = generator params (see sfx.py);
    anchor = time of the visual event this cue belongs to, when the cue starts before it.
    name = '@drop' 这类按动作起名的，交给当前风格的 theme.SFX 换成具体声音；返回 None = 不出声"""
    if name.startswith('@'):
        m = getattr(_theme(), 'SFX', {})
        m = m.get(name[1:], SFX_DEFAULT.get(name[1:])) if name[1:] in m or name[1:] in SFX_DEFAULT else None
        if not m:
            return None
        kw0 = dict(m[2]) if len(m) > 2 else {}
        kw0.update(kw)
        return cue(t, m[0], db + m[1], anchor, **kw0)
    if anchor is not None:
        kw['_anchor'] = anchor
    return (t, name, G[name] + db, kw)


def transition_cues(SC):
    """每个转场一个声音、每个章节开头一声轻响；横屏人物小窗放大成全屏（和缩回）时各一声低 whoosh。
    横屏里 host=True 的条目和紧跟在它后面的条目没有转场声（被人物全屏挡住，换画面是直接切的）。"""
    import lib
    out = []
    tl = SC.TIMELINE
    for i, sc in enumerate(tl[1:], 1):
        T, tr = sc['t'], sc.get('tr', lib.DEFAULT_TR)
        if not lib.VERTICAL and (sc.get('host') or tl[i - 1].get('host')):
            continue
        own = getattr(_theme(), 'TR_SFX', {}).get(tr)          # 风格自己的转场声：[(相对秒数, 音效, dB, {参数}), …]
        if own:
            for dt, nm, db, *kw in own:
                out.append(cue(T + dt, nm, db, anchor=T, **(dict(kw[0]) if kw else {})))
            continue
        if tr == 'push':
            out.append(cue(T - 0.3, 'whoosh', 0, anchor=T, d=0.55, f0=280.0, f1=3600.0, pan0=0.6, pan1=-0.6, seed=i))
        elif tr == 'slideup':
            out.append(cue(T - 0.3, 'whoosh', -1, anchor=T, d=0.55, f0=220.0, f1=2800.0, pan0=0.0, pan1=0.0, seed=i))
        elif tr == 'zoom':
            out.append(cue(T - 0.36, 'whoosh', 0, anchor=T, d=0.7, f0=180.0, f1=2600.0, peak=0.52, pan0=-0.2, pan1=0.2, seed=i))
        elif tr == 'wipe':
            out.append(cue(T - 0.3, 'whoosh', -1, anchor=T, d=0.55, f0=400.0, f1=5200.0, pan0=-0.7, pan1=0.7, seed=i))
            out.append(cue(T - 0.05, 'swish', -2, anchor=T))
        elif tr == 'flash':
            out.append(cue(T - 0.25, 'swish', 2, anchor=T, d=0.3, f0=1200.0, f1=7000.0))
            out.append(cue(T - 0.05, 'sparkle', 0, anchor=T))
        elif tr == 'fade':
            out.append(cue(T - 0.2, 'swish', -6, anchor=T, d=0.45, f0=600.0, f1=2400.0))
        elif tr == 'paper':                      # 纸张类转场（复古报刊）：录音纸声
            out.append(cue(T - 0.34, 'paper_slide', -1, anchor=T))
            out.append(cue(T + 0.04, 'paper_drop', -3, anchor=T, v=1 + i % 2))
        elif tr == 'page':                       # 翻页（手绘笔记）
            out.append(cue(T - 0.32, 'page_flip', -2, anchor=T, v=1 + i % 2))
        elif tr == 'scroll':                     # 往下读（手绘笔记）：轻轻的纸滑声
            out.append(cue(T - 0.3, 'paper_slide', -6, anchor=T))
        elif tr == 'erase':                      # 橡皮擦（手绘笔记）：来回擦的沙沙声
            out.append(cue(T - 0.36, 'pencil', -4, anchor=T, rate=0.8))
        elif tr == 'glitch':
            out.append(cue(T - 0.2, 'glitch', 0, anchor=T, seed=80 + i))
    if not lib.VERTICAL:
        for k, (a, b, d) in enumerate(full_windows(SC)):       # 小窗放大成人物全屏 / 缩回
            out.append(cue(a - 0.04, 'whoosh', -7, anchor=a, d=d + 0.2, f0=200.0, f1=2400.0, peak=0.62, pan0=-0.4, pan1=0.0, seed=200 + k))
            if b < 1e8:
                out.append(cue(b - d - 0.04, 'whoosh', -9, anchor=b - d, d=d + 0.2, f0=2200.0, f1=240.0, peak=0.4, pan0=0.0, pan1=-0.4, seed=300 + k))
    for c_ in getattr(SC, 'CHAPTERS', [])[1:]:
        t0 = c_[0]
        out.append(cue(t0 - 0.1, 'tick', 0, anchor=t0, f=1800.0))
        out.append(cue(t0 + 0.02, 'tick', -2, f=2600.0))
    return out


def times_when(fn, t0, t1, step=1 / 120):
    """first time in [t0,t1] where fn(t) is truthy (sync a sound to a computed animation event)"""
    t = t0
    while t <= t1:
        if fn(t):
            return t
        t += step
    return None
