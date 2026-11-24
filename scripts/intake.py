"""第 3 步：收内容。读口播稿、检查口播视频和素材，报告给用户。

usage: python intake.py [工程文件夹]        （不写 = 当前文件夹或它的上一级）
writes: _工程/口播稿.txt          口播稿纯文本（一段一行）
        _工程/脚本表.json         用的是三列脚本表时：每行 {口播词, 画面, 参考资料}
        _工程/媒体信息.json       口播视频和素材的时长、尺寸、横竖、帧率
        _工程/口播_合并.mp4       口播有好几条时：按文件名顺序接成一条（只有录音时是 口播_合并.wav）
最后一行 TAKE=<路径>：第 5 步转写、剪气口用的口播原片（一条就是它本身，几条就是合并后的那个）。

口播稿支持：docx、rtf、txt、md、csv（三列脚本表）、md 表格（三列脚本表）。
不用 Mac 自带的 textutil，Windows 上一样能读。

在别的脚本里：
  import intake
  text = intake.read_script('口播稿.docx')          # 纯文本
  rows = intake.read_table('脚本表.csv')            # 三列脚本表 -> [{'口播词', '画面', '参考资料'}]，不是脚本表返回 None
"""
import os, sys, re, json, csv, io, zipfile, subprocess
import tools

SCRIPT_EXT = ('.docx', '.rtf', '.txt', '.md', '.csv')
VIDEO_EXT = ('.mp4', '.mov', '.m4v', '.mkv', '.avi', '.webm', '.flv', '.wmv', '.mts')
AUDIO_EXT = ('.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg')
IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.heic', '.svg')


# ---------- 读文本 ----------

def _read_text_file(path):
    raw = open(path, 'rb').read()
    for enc in ('utf-8-sig', 'gb18030', 'utf-16'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode('utf-8', 'ignore')


def _docx_text(path):
    """docx = zip 里的 word/document.xml；按段落取 w:t，不需要 python-docx"""
    with zipfile.ZipFile(path) as z:
        xml = z.read('word/document.xml').decode('utf-8')
    paras = []
    for p in re.findall(r'<w:p[ >].*?</w:p>', xml, flags=re.S):
        p = re.sub(r'<w:tab/>', '<w:t>\t</w:t>', p)
        p = re.sub(r'<w:br[^>]*/>', '<w:t>\n</w:t>', p)
        paras.append(_unxml(''.join(re.findall(r'<w:t(?: [^>]*)?>(.*?)</w:t>', p, flags=re.S))))
    return '\n'.join(paras)


def _unxml(s):
    return (s.replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
             .replace('&apos;', "'").replace('&amp;', '&'))


_RTF_SKIP = {'fonttbl', 'colortbl', 'expandedcolortbl', 'stylesheet', 'info', 'pict', 'header', 'footer',
             'listtable', 'listoverridetable', 'rsidtbl', 'generator', 'xmlnstbl', 'themedata', 'datastore',
             'latentstyles', 'colorschememapping', 'pgdsctbl', 'mmathPr'}


_RTF_CHARSET = {0: None, 1: None, 128: 'cp932', 129: 'cp949', 134: 'gbk', 136: 'big5', 161: 'cp1253',
                162: 'cp1254', 177: 'cp1255', 178: 'cp1256', 186: 'cp1257', 204: 'cp1251', 222: 'cp874', 238: 'cp1250'}


def _rtf_text(path):
    """够用的 RTF 解析：\\uN 和 \\'hh 转字，跳过字体表等目录组，\\par、换行符转行"""
    data = open(path, 'rb').read().decode('latin-1')
    m = re.search(r'\\ansicpg(\d+)', data)
    cp = 'cp' + m.group(1) if m else 'cp1252'
    if cp == 'cp936':
        cp = 'gbk'
    # 字体表：\fN 用哪个字符集。\'hh 要按当前字体的字符集解码（中文字体常是 134 = GBK，和文档的 ansicpg 不一样）
    fcs = {int(a): _RTF_CHARSET.get(int(b)) for a, b in re.findall(r'\\f(\d+)[^;{}]*?\\fcharset(\d+)', data)}
    out, hexbuf = [], bytearray()
    stack = []                         # (skip, uc, font)
    skip, uc, font, pending_skip = False, 1, None, 0
    i, n = 0, len(data)

    def flush_hex():
        if hexbuf:
            if not skip:
                out.append(bytes(hexbuf).decode(fcs.get(font) or cp, 'ignore'))
            hexbuf.clear()

    while i < n:
        ch = data[i]
        if ch == '{':
            flush_hex()
            stack.append((skip, uc, font))
            i += 1
            # 目录组：{\*\xxx 或 {\fonttbl 这类，整组跳过
            m = re.match(r'\\\*|\\([a-zA-Z]+)', data[i:])
            if m and (m.group(0) == '\\*' or m.group(1) in _RTF_SKIP):
                skip = True
            continue
        if ch == '}':
            flush_hex()
            skip, uc, font = stack.pop() if stack else (False, 1, None)
            i += 1
            continue
        if ch == '\\':
            nxt = data[i + 1] if i + 1 < n else ''
            if nxt == "'":                               # \'hh
                if pending_skip:
                    pending_skip -= 1
                else:
                    hexbuf.append(int(data[i + 2:i + 4], 16))
                i += 4
                continue
            flush_hex()
            if nxt in '\\{}':
                if not skip:
                    out.append(nxt)
                i += 2
                continue
            if nxt in '\r\n':                            # 反斜杠 + 换行 = 段落
                if not skip:
                    out.append('\n')
                i += 2
                continue
            if nxt == '~':
                if not skip:
                    out.append(' ')
                i += 2
                continue
            m = re.match(r'\\([a-zA-Z]+)(-?\d+)? ?', data[i:])
            if not m:
                i += 2
                continue
            word, arg = m.group(1), m.group(2)
            i += m.end()
            if word == 'uc':
                uc = int(arg)
            elif word == 'f' and arg is not None:
                font = int(arg)
            elif word == 'u':
                v = int(arg)
                if v < 0:
                    v += 65536
                if not skip:
                    out.append(chr(v))
                pending_skip = uc
            elif word in ('par', 'line', 'row'):
                if not skip:
                    out.append('\n')
            elif word in ('tab', 'cell'):
                if not skip:
                    out.append('\t')
            continue
        if ch in '\r\n':
            i += 1
            continue
        flush_hex()
        if pending_skip:
            pending_skip -= 1
        elif not skip:
            out.append(ch)
        i += 1
    flush_hex()
    return ''.join(out)


# ---------- 三列脚本表 ----------

_COL_SPEECH = ('口播词', '口播', '台词', '文案', '旁白')
_COL_VISUAL = ('画面', '画面要求', '镜头')
_COL_REF = ('参考资料', '参考', '素材', '资料')


def _rows_to_table(rows):
    if not rows:
        return None
    head = [h.strip().lstrip('\ufeff') for h in rows[0]]

    def find(names):
        for j, h in enumerate(head):
            if any(h.startswith(nm) for nm in names):
                return j
        return None
    js, jv, jr = find(_COL_SPEECH), find(_COL_VISUAL), find(_COL_REF)
    if js is None:
        return None
    out = []
    for r in rows[1:]:
        get = lambda j: (r[j].strip() if j is not None and j < len(r) else '')
        if not any(get(j) for j in (js, jv, jr)):
            continue
        out.append({'口播词': get(js), '画面': get(jv), '参考资料': get(jr)})
    return out


def _md_table_rows(text):
    rows = []
    for line in text.splitlines():
        s = line.strip()
        if not (s.startswith('|') and s.endswith('|')):
            if rows:
                break          # 第一张表结束
            continue
        cells = [c.strip() for c in s.strip('|').split('|')]
        if all(re.fullmatch(r':?-{2,}:?', c) for c in cells if c):
            continue
        rows.append(cells)
    return rows


def read_table(path):
    """三列脚本表（csv 或 md 表格）-> [{'口播词','画面','参考资料'}]；不是脚本表返回 None"""
    ext = os.path.splitext(path)[1].lower()
    if ext == '.csv':
        return _rows_to_table(list(csv.reader(io.StringIO(_read_text_file(path)))))
    if ext == '.md':
        text = _read_text_file(path)
        # md 模板里的说明表（列|填什么|注意）不是脚本表：找表头含「口播」的那张
        for block in re.split(r'\n\s*\n', text):
            t = _rows_to_table(_md_table_rows(block))
            if t:
                t = [r for r in t if r['口播词']]
                if t:
                    return t
    return None


def read_script(path):
    """口播稿 -> 纯文本（一段一行，去掉空行）"""
    ext = os.path.splitext(path)[1].lower()
    table = read_table(path) if ext in ('.csv', '.md') else None
    if table:
        text = '\n'.join(r['口播词'] for r in table if r['口播词'])
    elif ext == '.docx':
        text = _docx_text(path)
    elif ext == '.rtf':
        text = _rtf_text(path)
    elif ext in ('.txt', '.md', '.csv'):
        text = _read_text_file(path)
    else:
        raise ValueError(f'不认识的口播稿格式：{path}（支持 {", ".join(SCRIPT_EXT)}；pdf/pages 请另存为 docx 或 txt）')
    lines = [re.sub(r'[ \t\u3000]+', ' ', l).strip() for l in text.replace('\r', '\n').split('\n')]
    return '\n'.join(l for l in lines if l)


# ---------- 媒体 ----------

def probe(path):
    """ffprobe -> {dur, w, h, fps, rot, audio, orient}；w/h 已按旋转换过来"""
    r = subprocess.run([tools.FFPROBE, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path],
                       capture_output=True, text=True, encoding='utf-8', errors='ignore')
    if r.returncode != 0:
        return None
    j = json.loads(r.stdout or '{}')
    v = next((s for s in j.get('streams', []) if s.get('codec_type') == 'video'
              and not (s.get('disposition') or {}).get('attached_pic')), None)
    a = any(s.get('codec_type') == 'audio' for s in j.get('streams', []))
    dur = float((j.get('format') or {}).get('duration') or 0)
    info = dict(dur=round(dur, 2), audio=a)
    if v:
        w, h = int(v.get('width') or 0), int(v.get('height') or 0)
        rot = 0
        for sd in v.get('side_data_list') or []:
            if 'rotation' in sd:
                rot = int(sd['rotation'])
        rot = int((v.get('tags') or {}).get('rotate', rot))
        if abs(rot) % 180 == 90:
            w, h = h, w
        num, den = (v.get('avg_frame_rate') or v.get('r_frame_rate') or '0/1').split('/')
        fps = round(float(num) / float(den), 2) if float(den or 0) else 0
        info.update(w=w, h=h, fps=fps, rot=rot, orient=('竖' if h > w else '横' if w > h else '方'))
    return info


def _fmt_dur(s):
    m, s = divmod(int(round(s)), 60)
    return f'{m}分{s:02d}秒' if m else f'{s}秒'


def find_project(start=None):
    d = os.path.abspath(start or os.getcwd())
    for cand in (d, os.path.dirname(d)):
        if os.path.exists(os.path.join(cand, '_工程', 'project.json')):
            return cand
    return None


def _files(folder, exts, recursive=False):
    if not os.path.isdir(folder):
        return []
    out = []
    for root, dirs, fs in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(('.', '_'))]
        for f in sorted(fs):
            if f.lower().endswith(exts) and not f.startswith(('.', '~$')):
                out.append(os.path.join(root, f))
        if not recursive:
            break
    return out


def concat_takes(takes, infos, work):
    """几条口播按顺序接成一条，尺寸和帧率以第一条为准（别的条缩放 + 补黑边）。返回 (路径, 问题)"""
    has_v = ['w' in i for i in infos]
    if any(has_v) and not all(has_v):
        return None, '口播里有的是视频、有的只有声音，没法接成一条：都用视频，或都用录音'
    n = len(takes)
    if all(has_v):
        w, h = infos[0]['w'], infos[0]['h']
        fps = infos[0]['fps'] or 30
        out = os.path.join(work, '口播_合并.mp4')
        fl = []
        for k in range(n):
            fl.append(f'[{k}:v:0]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,'
                      f'setsar=1,fps={fps},format=yuv420p[v{k}];'
                      f'[{k}:a:0]aresample=48000,aformat=channel_layouts=stereo[a{k}];')
        fl.append(''.join(f'[v{k}][a{k}]' for k in range(n)) + f'concat=n={n}:v=1:a=1[v][a]')
        maps = ['-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-preset', 'medium', '-crf', '16',
                '-c:a', 'aac', '-b:a', '256k', '-movflags', '+faststart']
    else:
        out = os.path.join(work, '口播_合并.wav')
        fl = [f'[{k}:a:0]aresample=48000,aformat=channel_layouts=mono[a{k}];' for k in range(n)]
        fl.append(''.join(f'[a{k}]' for k in range(n)) + f'concat=n={n}:v=0:a=1[a]')
        maps = ['-map', '[a]', '-c:a', 'pcm_s16le']
    if os.path.exists(out) and os.path.getmtime(out) > max(os.path.getmtime(t) for t in takes):
        return out, None                                  # 已经合并过，口播也没换过
    cmd = [tools.FFMPEG, '-y', '-v', 'error']
    for t in takes:
        cmd += ['-i', t]
    cmd += ['-filter_complex', ''.join(fl)] + maps + [out]
    print(f'正在把 {n} 条口播接成一条 …', flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
    if r.returncode != 0:
        return None, '口播合并失败：' + (r.stderr or '').strip()[-300:]
    return out, None


def main():
    proj = find_project(sys.argv[1] if len(sys.argv) > 1 else None)
    if not proj:
        sys.exit('找不到工程文件夹（里面要有 _工程/project.json）。先运行 new_project.py。')
    work = os.path.join(proj, '_工程')
    cfg = json.load(open(os.path.join(work, 'project.json'), encoding='utf-8'))
    orient = cfg.get('orient', '横屏')
    problems, report = [], []

    # 口播稿
    scripts = _files(os.path.join(proj, '1_口播稿'), SCRIPT_EXT)
    if not scripts:
        problems.append('1_口播稿 里没有口播稿（docx / rtf / txt / md / 脚本表 csv）。没有稿子也能剪，但专有名词更容易听错、画面要靠转写来设计。')
    else:
        if len(scripts) > 1:
            report.append(f'口播稿有 {len(scripts)} 份，用的是第一份：{os.path.basename(scripts[0])}')
        sp = scripts[0]
        text = read_script(sp)
        table = read_table(sp)
        open(os.path.join(work, '口播稿.txt'), 'w', encoding='utf-8').write(text + '\n')
        if table:
            json.dump(table, open(os.path.join(work, '脚本表.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            nv = sum(1 for r in table if r['画面'])
            report.append(f'口播稿：{os.path.basename(sp)}（三列脚本表，{len(table)} 句，其中 {nv} 句写了画面要求）')
        else:
            n_chars = len(re.sub(r'\s', '', text))
            report.append(f'口播稿：{os.path.basename(sp)}（{n_chars} 字，按 5 字/秒 估计约 {_fmt_dur(n_chars / 5)}）')
        holds = re.findall(r'[（(]画面[^）)]*?停留\s*(\d+(?:\.\d+)?)\s*秒[^）)]*[）)]', text)
        if holds:
            report.append(f'稿子里有 {len(holds)} 处「（画面…停留N秒）」：这些字只上屏不念，做成定格页面')

    # 口播视频
    media = {}
    takes = _files(os.path.join(proj, '2_口播视频'), VIDEO_EXT + AUDIO_EXT)
    if not takes:
        problems.append('2_口播视频 里还没有口播视频（或录音）。这是必需的，放进去再继续。')
    take_infos = []
    for p in takes:
        info = probe(p)
        if not info:
            problems.append(f'读不了：{os.path.basename(p)}（文件可能坏了或还在 iCloud/网盘里没下载下来）')
            continue
        take_infos.append(info)
        media[os.path.relpath(p, proj)] = info
        if 'w' not in info:
            report.append(f'口播：{os.path.basename(p)}　只有声音 {_fmt_dur(info["dur"])} → 不露脸模式，全程全屏画面')
            continue
        line = f'口播：{os.path.basename(p)}　{info["w"]}x{info["h"]} {info["orient"]}拍 {info["fps"]:g}fps {_fmt_dur(info["dur"])}'
        if not info['audio']:
            problems.append(f'{os.path.basename(p)} 没有声音轨，没法剪气口和对字幕')
        want = '竖' if orient == '竖屏' else '横'
        if info['orient'] != want:
            line += f'\n      ⚠ 成片是{orient}，口播是{info["orient"]}拍：人物全屏要裁一块再放大'
            short = min(info['w'], info['h'])
            if (orient == '横屏' and info['w'] < 1920 * 0.75) or (orient == '竖屏' and info['h'] < 1920 * 0.75):
                line += f'（原片只有 {short}p 宽，放大后会糊一点）'
        report.append(line)
    take = takes[0] if len(takes) == 1 else None
    if len(takes) > 1 and len(take_infos) == len(takes):
        take, err = concat_takes(takes, take_infos, work)
        if err:
            problems.append(err)
        else:
            report.append(f'口播有 {len(takes)} 条，按文件名顺序接成了一条 _工程/{os.path.basename(take)}'
                          f'（{" → ".join(os.path.basename(t) for t in takes)}）。顺序不对请改文件名，再跑一次。')

    # 素材
    mats = _files(os.path.join(proj, '3_素材'), VIDEO_EXT + IMAGE_EXT + AUDIO_EXT, recursive=True)
    n_img = sum(1 for m in mats if m.lower().endswith(IMAGE_EXT))
    n_vid = sum(1 for m in mats if m.lower().endswith(VIDEO_EXT))
    report.append(f'素材：图片 {n_img} 张、视频 {n_vid} 段' + ('' if mats else '（还没有，第 4 步可以帮你找）'))
    for p in mats:
        if p.lower().endswith(VIDEO_EXT):
            info = probe(p)
            if info:
                media[os.path.relpath(p, proj)] = info
    refs = _files(os.path.join(proj, '4_参考图'), IMAGE_EXT)
    if refs:
        report.append(f'参考图：{len(refs)} 张（调色和选风格时用）')
    bgm = _files(os.path.join(proj, '5_BGM'), AUDIO_EXT)
    if bgm:
        report.append(f'BGM：{os.path.basename(bgm[0])}（会铺满全片、压在人声下面）')

    json.dump(media, open(os.path.join(work, '媒体信息.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'工程：{proj}（{orient}）')
    for r in report:
        print('  ' + r)
    if problems:
        print('\n需要你处理：')
        for p in problems:
            print('  ✗ ' + p)
    if take:
        print(f'TAKE={os.path.abspath(take)}')
    sys.exit(0 if take else 1)


if __name__ == '__main__':
    main()
