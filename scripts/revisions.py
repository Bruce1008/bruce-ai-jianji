"""第 10 步：读修改表（只读，不改表）。

usage（在 _工程/ 里）：python revisions.py [修改表.xlsx]      不写 = 工程根目录的 修改表.xlsx
打印每一行「待改」：行号、时间（成片时间 → 口播时间）、问题、截图（找到了给完整路径）、类型，
以及这个时间落在哪个镜头（scenes.py 里 TIMELINE 第几条、画面函数名）。
跳过模板自带的灰色示例行、「已改」的行和空行。最后打印下一个版本的文件名 NEXT=成片_vN.mp4。

成片时间 → 口播时间：成片里有定格（hold=N）时两者不一样，按 video_only.holds.json 换算；没有定格就相同。
"""
import os, sys, re, json

EXAMPLES = {'花字挡住了脸', '口水音太多', '案例画面太短，还没看清就切走了', '“然后”这个口头禅太密，挨得近的删掉一个'}


def parse_time(s):
    """'00:15' / '1:20 以后' / '00:15-00:20' / '全片' -> (t0, t1)；全片 -> (None, None)；看不懂 -> False"""
    s = str(s or '').strip()
    if not s or '全片' in s:
        return None, None
    ts = [int(m[0]) * 60 + float(m[1]) for m in re.findall(r'(\d+)\s*[:：]\s*(\d+(?:\.\d+)?)', s)]
    if not ts:
        m = re.match(r'^(\d+(?:\.\d+)?)\s*秒?', s)
        ts = [float(m.group(1))] if m else []
    if not ts:
        return False
    if len(ts) >= 2:
        return ts[0], ts[1]
    return (ts[0], float('inf')) if re.search(r'以后|之后|往后|后面', s) else (ts[0], ts[0])


def main():
    import openpyxl
    here = os.getcwd()
    proj = os.path.dirname(here) if os.path.exists('project.json') else here
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(proj, '修改表.xlsx')
    if not os.path.exists(path):
        sys.exit(f'找不到修改表：{path}')
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb['修改表'] if '修改表' in wb.sheetnames else wb.worksheets[0]
    folder = os.path.dirname(os.path.abspath(path))

    tm = None
    if os.path.exists('video_only.holds.json'):
        import holds
        hs = holds.load('video_only.holds.json')
        if hs:
            tm = holds.TimeMap(hs, 1e9)
    tl = []
    try:
        sys.path.insert(0, here)
        import scenes as SC
        tl = SC.TIMELINE
    except Exception as e:
        print(f'（读不了 scenes.py，镜头位置不标：{e}）')

    def shot(v):
        k = max([i for i, d in enumerate(tl) if d['t'] <= v] or [0]) if tl else None
        if k is None:
            return ''
        d = tl[k]
        what = '人物全屏' if d.get('host') else d['mg'].__name__ if 'mg' in d else '视频素材' if 'clip' in d else '?'
        return f'TIMELINE[{k}] t={d["t"]:.2f} {what}'

    def v_of(o):
        return tm.pic(o)[0] if tm else o

    n = 0
    for r, row in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
        tcell, prob, shot_f, kind, state = (list(row) + [None] * 5)[:5]
        if not prob or str(prob).strip() in EXAMPLES or str(state or '').strip() == '已改':
            continue
        n += 1
        tt = parse_time(tcell)
        if tt is False:
            where = f'时间看不懂：{tcell}'
        elif tt[0] is None:
            where = '全片'
        else:
            v0 = v_of(tt[0])
            where = f'成片 {tcell} → 口播 {v0:.2f}s'
            if tt[1] not in (tt[0], float('inf')):
                where += f'–{v_of(tt[1]):.2f}s'
            elif tt[1] == float('inf'):
                where += ' 以后'
            where += f'　镜头 {shot(v0)}'
        img = ''
        if shot_f:
            p = os.path.join(folder, str(shot_f).strip())
            img = f'\n    截图：{p}' + ('' if os.path.exists(p) else '（没找到这个文件）')
        print(f'第 {r} 行 [{kind or "未分类"}] {prob}\n    {where}{img}')
    if not n:
        print('修改表里没有「待改」的行。')

    out_dir = os.path.join(proj, '成片')
    k = 2
    while os.path.exists(os.path.join(out_dir, f'成片_v{k}.mp4')):
        k += 1
    print(f'NEXT=成片_v{k}.mp4')


if __name__ == '__main__':
    main()
