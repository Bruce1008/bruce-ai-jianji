"""Raw take <-> rough cut time (cut_map.json, written by cut_voice.py cut).

New projects need none of this: they transcribe 口播_粗剪.mp4 and time everything on it. Use it when a project was
already timed on the raw take and is re-cut afterwards (or to find a raw-take moment in the cut):

    import cutmap
    M = cutmap.load()            # cut_map.json in the work dir
    M.to_new(12.3)               # raw seconds -> cut seconds (a time inside a removed bit lands on the splice)
    M.to_raw(10.1)               # cut seconds -> raw seconds
    cutmap.retime(SC, M)         # at the END of a raw-timed scenes.py: TIMELINE / CHAPTERS / FULL / done= move to cut
                                 # time; every page, overlay and STAGE_OVERLAY is called with the raw time, so the
                                 # animations written for the raw take play in step with the cut voice
    cues_new = cutmap.retime_cues(cues_raw, M)
"""
import json, bisect, functools


class CutMap:
    def __init__(self, d):
        self.speed = d['speed']
        self.segs = d['segs']                    # [raw0, raw1, new0, new1]
        self.r0 = [s[0] for s in self.segs]
        self.n0 = [s[2] for s in self.segs]
        self.new_dur = d['new_dur']

    def to_new(self, t):
        i = bisect.bisect_right(self.r0, t) - 1
        if i < 0:
            return 0.0
        r0, r1, n0, n1 = self.segs[i]
        return n0 + (min(t, r1) - r0) / self.speed

    def to_raw(self, t):
        i = bisect.bisect_right(self.n0, t) - 1
        if i < 0:
            return self.segs[0][0]
        r0, r1, n0, n1 = self.segs[i]
        return r0 + (t - n0) * self.speed


def load(path='cut_map.json'):
    return CutMap(json.load(open(path, encoding='utf-8')))


def _wrap(fn, M):
    @functools.wraps(fn)                         # keeps the page name for checks.py and error messages
    def w(c, t, *rest):
        return fn(c, M.to_raw(t), *rest)
    return w


def retime(SC, M):
    tl = []
    for d in SC.TIMELINE:
        d = dict(d)
        d['t'] = M.to_new(d['t'])
        if 'mg' in d: d['mg'] = _wrap(d['mg'], M)
        if 'ov' in d: d['ov'] = _wrap(d['ov'], M)
        if 'done' in d: d['done'] = M.to_new(d['done'])
        if callable(d.get('zoom')):
            z = d['zoom']; d['zoom'] = lambda t, z=z: z(M.to_raw(t))
        tl.append(d)
    SC.TIMELINE = tl
    SC.CHAPTERS = [(M.to_new(t), *rest) for t, *rest in SC.CHAPTERS]
    if getattr(SC, 'FULL', None):
        SC.FULL = [(M.to_new(w[0]), M.to_new(w[1]), *w[2:]) for w in SC.FULL]
    if getattr(SC, 'STAGE_OVERLAY', None):
        ov = SC.STAGE_OVERLAY
        SC.STAGE_OVERLAY = lambda c, t: ov(c, M.to_raw(t))
    return SC


def retime_cues(cl, M):
    out = []
    for t, name, db, kw in cl:
        kw = dict(kw)
        if '_anchor' in kw:
            kw['_anchor'] = M.to_new(kw['_anchor'])
        out.append((M.to_new(t), name, db, kw))
    return out
