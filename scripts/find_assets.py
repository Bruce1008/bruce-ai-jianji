"""第 4 步：找素材。两类分开找、分开记。

可商用（默认）：Openverse、Wikimedia Commons（不要 key），Pexels、Pixabay（免费 key）。
  只收 CC0、公有领域、CC BY、Pexels 许可、Pixabay 许可；NC（禁商用）、ND（禁改）、SA（相同方式共享）一律不要。
官方引用（用户选了才找）：公司、机构官网和官方账号发的演示视频、配图。yt-dlp 或直链下载，截成 ≤10 秒，台标水印保留。
  清单里标「引用·非商用授权」：科普、评论类视频一般算适当引用；接商单、广告的视频要换掉。

在工程的 _工程/ 里运行：
  python find_assets.py search "humanoid robot" [--type image|video] [--n 12] [--orient 横|竖] [--min 1000]
        搜可商用素材（关键词用英文搜得多）。结果编号 c1、c2…，存进 _工程/素材候选.json，
        并出一张候选拼图 _工程/候选拼图/<关键词>.jpg：先看图再挑，别只看标题
  python find_assets.py get c3 --line "对应的那句口播" [--name 短名] [--from 2 --to 8] [--note 备注]
        下载候选到 3_素材/找来的/，记进素材清单
  python find_assets.py official <链接> --line "…" --name 短名 --source "XX 官方" [--page 来源页面] [--from 0:03 --to 0:12]
        下载官方素材：视频页面（YouTube、B 站、官网都行，yt-dlp 能认的）、视频直链或图片直链。
        视频超过 10 秒又没给 --from/--to：只下原片到 _工程/官方原片/，用 contact_sheet.py 看完再带上区间运行一次
  python find_assets.py skip --line "…" --reason "找不到一手来源"
  python find_assets.py sheet        已下载素材拼成一张图 3_素材/找来的/素材拼图.jpg，给用户删不要的
  python find_assets.py sync         用户删了文件以后，清单里对应的行跟着删
  python find_assets.py credits      写 成片/授权清单.md（简介里要贴的署名和画面来源）
  python find_assets.py keys         Pexels / Pixabay key 的状态和申请方法
  python find_assets.py setkey pexels|pixabay <KEY>

清单：_工程/素材清单.json 是底稿，每次改动都重新生成工程根目录的 素材清单.xlsx。
"""
import os, sys, re, json, html, hashlib, shutil, subprocess, datetime, argparse
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlparse
import tools, fonts

UA = 'bruce-ai-jianji/0.1 (open-source video editing skill; python)'
KEYS = os.path.join(os.environ.get('BAJ_HOME') or os.path.join(os.path.expanduser('~'), '.bruce-ai-jianji'), 'keys.json')
IMG_EXT = ('.jpg', '.jpeg', '.png', '.webp', '.gif')
VID_EXT = ('.mp4', '.mov', '.webm', '.m4v', '.mkv', '.m3u8')
OFFICIAL = '引用·非商用授权'
COMMERCIAL = '可商用'
MAX_OFFICIAL_S = 10.0


# ---------- 工程路径 ----------

def proj_dirs():
    here = os.getcwd()
    proj = here if os.path.isdir(os.path.join(here, '_工程')) else os.path.dirname(here)
    if not os.path.isdir(os.path.join(proj, '_工程')):
        sys.exit('请在工程的 _工程 文件夹里运行（找不到 _工程）')
    work = os.path.join(proj, '_工程')
    found = os.path.join(proj, '3_素材', '找来的')
    os.makedirs(found, exist_ok=True)
    return proj, work, found


def jload(p, default):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return default


def jsave(p, obj):
    json.dump(obj, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


# ---------- 网络（curl：证书省心；key 走 -K 配置，不出现在命令行里） ----------

_CURL = shutil.which('curl') or shutil.which('curl.exe')


def http(url, headers=None, out=None, timeout=25):
    """GET；out=None 返回 bytes（失败 None），out=路径 返回是否成功"""
    if _CURL:
        cfg = f'url = "{url}"\n' + ''.join(f'header = "{k}: {v}"\n' for k, v in (headers or {}).items())
        cmd = [_CURL, '-sfL', '--retry', '1', '--connect-timeout', '12', '--max-time', str(timeout), '-A', UA, '-K', '-']
        if out:
            cmd += ['-o', out]
        r = subprocess.run(cmd, input=cfg.encode('utf-8'), capture_output=True)
        if out:
            return r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0
        return r.stdout if r.returncode == 0 else None
    import urllib.request
    try:
        req = urllib.request.Request(url, headers=dict(headers or {}, **{'User-Agent': UA}))
        data = urllib.request.urlopen(req, timeout=timeout).read()
    except Exception:
        return False if out else None
    if out:
        open(out, 'wb').write(data)
        return True
    return data


def http_json(url, headers=None):
    b = http(url, headers)
    try:
        return json.loads(b) if b else None
    except Exception:
        return None


def keys():
    return jload(KEYS, {})


# ---------- 授权 ----------

def _cc(code, version=''):
    """Openverse / Wikimedia 的授权代码 -> (显示名, 要不要署名)；不收的返回 None"""
    c = (code or '').lower().replace('_', '-').strip()
    if c in ('cc0', 'cc-zero', 'cc0-1.0'):
        return 'CC0', False
    if c in ('pdm', 'pd', 'public domain') or c.startswith('pd-') or c.startswith('public domain'):
        return '公有领域', False
    m = re.fullmatch(r'(?:cc-)?by(?:-(\d(?:\.\d)?))?', c)
    if m:
        return f'CC BY {m.group(1) or version}'.strip(), True
    return None                          # by-sa / by-nc / by-nd / 其他：都不要


def _strip_html(s):
    return html.unescape(re.sub(r'<[^>]+>', '', s or '')).strip()


# ---------- 搜索：每个来源返回统一格式的候选 ----------

def _cand(**kw):
    base = dict(type='image', title='', page='', media='', thumb='', w=0, h=0, dur=None, author='',
                license='', credit=False, credit_text='', source='')
    base.update(kw)
    return base


def s_openverse(q, typ, n, orient):
    if typ != 'image':
        return []
    url = (f'https://api.openverse.org/v1/images/?q={quote(q)}&license=cc0,pdm,by&page_size={min(n * 2, 40)}'
           '&mature=false')
    if orient:
        url += '&aspect_ratio=' + ('wide' if orient == '横' else 'tall')
    j = http_json(url)
    if j is None:
        raise RuntimeError('连不上 api.openverse.org')
    out = []
    for r in j.get('results', []):
        lic = _cc(r.get('license'), r.get('license_version') or '')
        if not lic or not r.get('url'):
            continue
        out.append(_cand(title=r.get('title') or '', page=r.get('foreign_landing_url') or '', media=r['url'],
                         thumb=r.get('thumbnail') or r['url'], w=r.get('width') or 0, h=r.get('height') or 0,
                         author=r.get('creator') or '', license=lic[0], credit=lic[1],
                         credit_text=r.get('attribution') or '', source=f"Openverse / {r.get('source') or ''}"))
    return out


def s_wikimedia(q, typ, n, orient):
    ft = 'bitmap' if typ == 'image' else 'video'
    url = ('https://commons.wikimedia.org/w/api.php?action=query&format=json&generator=search&gsrnamespace=6'
           f'&gsrsearch={quote(q + " filetype:" + ft)}&gsrlimit=50&prop=imageinfo'
           '&iiprop=url|size|extmetadata|mime&iiurlwidth=480'
           '&iiextmetadatafilter=LicenseShortName|License|Artist|AttributionRequired|ObjectName')
    j = http_json(url)
    if j is None:
        raise RuntimeError('连不上 commons.wikimedia.org')
    pages = sorted((j.get('query') or {}).get('pages', {}).values(), key=lambda p: p.get('index', 0))
    out = []
    for p in pages:
        ii = (p.get('imageinfo') or [{}])[0]
        em = {k: (v or {}).get('value', '') for k, v in (ii.get('extmetadata') or {}).items()}
        lic = _cc(em.get('License')) or (('公有领域', False) if 'public domain' in em.get('LicenseShortName', '').lower() else None)
        if not lic:
            continue
        title = em.get('ObjectName') or p.get('title', '').replace('File:', '')
        artist = _strip_html(em.get('Artist'))
        lic_name = em.get('LicenseShortName') or lic[0]
        out.append(_cand(type=typ, title=_strip_html(title), page=ii.get('descriptionurl', ''), media=ii.get('url', '').split('?')[0],
                         thumb=ii.get('thumburl') or '', w=ii.get('width') or 0, h=ii.get('height') or 0,
                         author=artist, license=lic[0], credit=lic[1],
                         credit_text=(f'“{_strip_html(title)}” by {artist or "unknown"}, {lic_name}, via Wikimedia Commons '
                                      f'({ii.get("descriptionurl", "")})') if lic[1] else '',
                         source='Wikimedia Commons'))
    return out


def s_pexels(q, typ, n, orient):
    k = keys().get('pexels')
    if not k:
        return None
    o = {'横': '&orientation=landscape', '竖': '&orientation=portrait'}.get(orient, '')
    hd = {'Authorization': k}
    if typ == 'image':
        j = http_json(f'https://api.pexels.com/v1/search?query={quote(q)}&per_page={min(n, 40)}{o}', hd)
        if j is None:
            raise RuntimeError('Pexels 请求失败（key 不对或网络问题）')
        return [_cand(title=p.get('alt') or '', page=p.get('url', ''), media=p['src'].get('original', ''),
                      thumb=p['src'].get('medium', ''), w=p.get('width', 0), h=p.get('height', 0),
                      author=p.get('photographer', ''), license='Pexels 许可', credit=False,
                      credit_text=f"Photo by {p.get('photographer', '')} on Pexels", source='Pexels')
                for p in j.get('photos', [])]
    j = http_json(f'https://api.pexels.com/videos/search?query={quote(q)}&per_page={min(n, 40)}{o}', hd)
    if j is None:
        raise RuntimeError('Pexels 请求失败（key 不对或网络问题）')
    out = []
    for v in j.get('videos', []):
        files = [f for f in v.get('video_files', []) if f.get('file_type') == 'video/mp4' and f.get('width')]
        if not files:
            continue
        best = min(files, key=lambda f: (abs(max(f['width'], f['height']) - 1920), -f['width']))
        out.append(_cand(type='video', title=os.path.basename(urlparse(v.get('url', '')).path.strip('/')),
                         page=v.get('url', ''), media=best['link'], thumb=v.get('image', ''),
                         w=best['width'], h=best['height'], dur=v.get('duration'),
                         author=(v.get('user') or {}).get('name', ''), license='Pexels 许可', credit=False,
                         credit_text=f"Video by {(v.get('user') or {}).get('name', '')} on Pexels", source='Pexels'))
    return out


def s_pixabay(q, typ, n, orient):
    k = keys().get('pixabay')
    if not k:
        return None
    o = {'横': '&orientation=horizontal', '竖': '&orientation=vertical'}.get(orient, '')
    base = 'https://pixabay.com/api/' + ('' if typ == 'image' else 'videos/')
    j = http_json(f'{base}?key={k}&q={quote(q)}&per_page={max(3, min(n, 50))}&safesearch=true{o}')
    if j is None:
        raise RuntimeError('Pixabay 请求失败（key 不对或网络问题）')
    out = []
    for h in j.get('hits', []):
        if typ == 'image':
            out.append(_cand(title=h.get('tags', ''), page=h.get('pageURL', ''), media=h.get('largeImageURL', ''),
                             thumb=h.get('webformatURL', ''), w=h.get('imageWidth', 0), h=h.get('imageHeight', 0),
                             author=h.get('user', ''), license='Pixabay 许可', credit=False,
                             credit_text=f"Image by {h.get('user', '')} from Pixabay", source='Pixabay'))
        else:
            vv = h.get('videos') or {}
            best = vv.get('large') if (vv.get('large') or {}).get('url') else vv.get('medium') or {}
            if not best.get('url'):
                continue
            out.append(_cand(type='video', title=h.get('tags', ''), page=h.get('pageURL', ''), media=best['url'],
                             thumb=best.get('thumbnail') or (vv.get('tiny') or {}).get('thumbnail', ''),
                             w=best.get('width', 0), h=best.get('height', 0), dur=h.get('duration'),
                             author=h.get('user', ''), license='Pixabay 许可', credit=False,
                             credit_text=f"Video by {h.get('user', '')} from Pixabay", source='Pixabay'))
    return out


SOURCES = [('Pexels', s_pexels), ('Pixabay', s_pixabay), ('Openverse', s_openverse), ('Wikimedia', s_wikimedia)]


def cmd_search(a):
    proj, work, found = proj_dirs()
    orient = a.orient if a.orient in ('横', '竖') else ''
    if not a.orient and a.type == 'video':          # 搜视频默认跟成片方向一致
        cfg = jload(os.path.join(work, 'project.json'), {})
        orient = '竖' if cfg.get('orient') == '竖屏' else '横'
    got, notes, ok_sources = [], [], set()
    with ThreadPoolExecutor(4) as ex:
        futs = [(name, ex.submit(fn, a.query, a.type, a.n, orient)) for name, fn in SOURCES]
        for name, f in futs:
            try:
                r = f.result()
            except Exception as e:
                notes.append(f'{name}：{e}')
                continue
            if r is None:
                notes.append(f'{name}：没有 key，跳过（python find_assets.py keys 看怎么免费申请）')
                continue
            ok_sources.add(name)
            r = [c for c in r if max(c['w'], c['h']) >= a.min and c['media']]
            if orient:
                r = [c for c in r if (c['w'] >= c['h']) == (orient == '横')]
            got.append(r)
    if 'Wikimedia' in ok_sources:      # Openverse 也收录 Wikimedia：同一张图只留 Wikimedia 自己那份
        got = [[c for c in r if c['source'] != 'Openverse / wikimedia'] for r in got]
    # 各来源轮流取，避免全是同一家
    merged, i = [], 0
    while len(merged) < a.n and any(i < len(r) for r in got):
        for r in got:
            if i < len(r) and len(merged) < a.n:
                merged.append(r[i])
        i += 1
    store = jload(os.path.join(work, '素材候选.json'), {'next': 1, 'items': {}})
    for c in merged:
        cid = f"c{store['next']}"
        store['next'] += 1
        c.update(id=cid, query=a.query)
        store['items'][cid] = c
    jsave(os.path.join(work, '素材候选.json'), store)
    for nt in notes:
        print('  · ' + nt)
    if not merged:
        print(f'「{a.query}」没搜到能商用的{"图片" if a.type == "image" else "视频"}：换个说法（英文、更具体或更宽泛）再搜')
        return
    for c in merged:
        size = f"{c['w']}x{c['h']}" + (f" {c['dur']}s" if c.get('dur') else '')
        print(f"{c['id']:>5}  {c['license']:<10} {size:<14} {c['source']:<22} {c['title'][:50]}")
    sheet = os.path.join(work, '候选拼图', re.sub(r'[^\w一-鿿-]+', '_', a.query)[:40] + '.jpg')
    make_sheet([(c['id'], c['thumb'], f"{c['license']} {c['w']}x{c['h']}" + (f" {c['dur']}s" if c.get('dur') else ''))
                for c in merged], sheet, os.path.join(work, '候选拼图', 'thumbs'),
               fallback={c['id']: [c['media']] for c in merged if c['type'] == 'image'})
    print(f'候选拼图：{sheet}')


# ---------- 拼图 ----------

def _label_font(size):
    from PIL import ImageFont
    try:
        fonts.ensure(['noto_sans_sc'], quiet=True)
        return ImageFont.truetype(fonts.path('noto_sans_sc'), size)
    except Exception:
        return ImageFont.load_default()


def make_sheet(items, out, cache_dir, cols=4, tw=360, th=240, fallback=None):
    """items = [(编号, 缩略图 url 或本地路径, 说明)]；fallback = {编号: [缩略图失败时再试的 url]}"""
    fallback = fallback or {}
    from PIL import Image, ImageDraw
    os.makedirs(cache_dir, exist_ok=True)

    def fetch(it):
        tag, src, _ = it
        if src and os.path.exists(src):
            return src
        p = os.path.join(cache_dir, hashlib.md5((src or tag).encode()).hexdigest()[:16] + '.img')
        if not os.path.exists(p):
            for u in [src] + fallback.get(tag, []):
                if u and http(u, out=p, timeout=40):
                    break
        return p if os.path.exists(p) else None
    with ThreadPoolExecutor(8) as ex:
        paths = list(ex.map(fetch, items))
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * tw, rows * (th + 34)), (245, 245, 240))
    d = ImageDraw.Draw(sheet)
    f1, f2 = _label_font(22), _label_font(17)
    for k, ((tag, _, note), p) in enumerate(zip(items, paths)):
        x, y = (k % cols) * tw, (k // cols) * (th + 34)
        im = None
        if p:
            try:
                im = _thumb(p)
            except Exception:
                im = None
        if im is not None:
            im.thumbnail((tw - 8, th - 8))
            sheet.paste(im, (x + (tw - im.width) // 2, y + (th - im.height) // 2))
        else:
            d.text((x + 20, y + th // 2), '（缩略图下载失败）', fill=(150, 150, 150), font=f2)
        d.rectangle([x + 4, y + 4, x + 4 + 12 * len(tag) + 16, y + 34], fill=(20, 24, 40))
        d.text((x + 12, y + 6), tag, fill=(255, 255, 255), font=f1)
        d.text((x + 8, y + th + 6), note[:40], fill=(60, 60, 60), font=f2)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    sheet.save(out, quality=88)


def _thumb(p):
    """图片直接开；视频取第 1 秒的一帧"""
    from PIL import Image
    try:
        return Image.open(p).convert('RGB')
    except Exception:
        pass
    r = subprocess.run([tools.FFMPEG, '-v', 'error', '-ss', '1', '-i', p, '-frames:v', '1', '-vf', 'scale=480:-2',
                        '-f', 'image2pipe', '-vcodec', 'png', '-'], capture_output=True)
    import io
    return Image.open(io.BytesIO(r.stdout)).convert('RGB')


# ---------- 下载 / 处理 ----------

def parse_t(s):
    if s is None or s == '':
        return None
    parts = [float(x) for x in str(s).split(':')]
    t = 0.0
    for x in parts:
        t = t * 60 + x
    return t


def fmt_t(t):
    m, s = divmod(t, 60)
    return f'{int(m):02d}:{s:05.2f}'.rstrip('0').rstrip('.') if s % 1 else f'{int(m):02d}:{int(s):02d}'


def probe(p):
    r = subprocess.run([tools.FFPROBE, '-v', 'error', '-show_entries', 'stream=codec_type,codec_name,width,height',
                        '-show_entries', 'format=duration', '-of', 'json', p], capture_output=True, text=True)
    try:
        j = json.loads(r.stdout)
    except Exception:
        return {}
    v = next((s for s in j.get('streams', []) if s.get('codec_type') == 'video'), {})
    return dict(codec=v.get('codec_name'), w=v.get('width', 0), h=v.get('height', 0),
                dur=float((j.get('format') or {}).get('duration') or 0))


def to_mp4(src, dst, t0=None, t1=None):
    """统一成 H.264 MP4（长边 ≤1920），可截一段；返回时长"""
    cmd = [tools.FFMPEG, '-v', 'error', '-y']
    if t0:
        cmd += ['-ss', f'{t0:.3f}']
    cmd += ['-i', src]
    if t1 is not None:
        cmd += ['-t', f'{t1 - (t0 or 0):.3f}']
    cmd += ['-vf', "scale='if(gte(iw,ih),min(1920,iw),-2)':'if(gte(iw,ih),-2,min(1920,ih))'",
            '-c:v', 'libx264', '-crf', '18', '-preset', 'medium', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', dst]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('ffmpeg 转码失败：' + r.stderr[-300:])
    return probe(dst).get('dur', 0)


def shrink(p, limit=3200):
    """图片长边超过 limit 就缩小（画面里最多放大到 1920 宽再推近一点，3200 够用）；返回 (w, h)"""
    from PIL import Image, ImageOps
    im = Image.open(p)
    if max(im.size) <= limit or getattr(im, 'is_animated', False):
        return im.size
    im = ImageOps.exif_transpose(im)
    im.thumbnail((limit, limit), Image.LANCZOS)
    if p.lower().endswith(('.jpg', '.jpeg')):
        im.convert('RGB').save(p, quality=92)
    else:
        im.save(p)
    return im.size


def next_no(rows):
    nums = [int(m.group(1)) for r in rows for m in [re.match(r'(\d+)_', r.get('file', ''))] if m]
    return max(nums, default=0) + 1


def safe(s, n=24):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f\s]+', '_', s).strip('._')
    return s[:n] or '素材'


def add_row(work, proj, row):
    lst = jload(os.path.join(work, '素材清单.json'), {'rows': [], 'skipped': []})
    lst['rows'].append(row)
    jsave(os.path.join(work, '素材清单.json'), lst)
    write_xlsx(proj, lst)


def cmd_get(a):
    proj, work, found = proj_dirs()
    store = jload(os.path.join(work, '素材候选.json'), {'items': {}})
    c = store['items'].get(a.id)
    if not c:
        sys.exit(f'没有候选 {a.id}：先 search')
    lst = jload(os.path.join(work, '素材清单.json'), {'rows': [], 'skipped': []})
    no = a.no or next_no(lst['rows'])
    name = safe(a.name or c['title'] or c['source'])
    ext = os.path.splitext(urlparse(c['media']).path)[1].lower() or ('.mp4' if c['type'] == 'video' else '.jpg')
    tmp = os.path.join(work, '_下载中' + ext)
    print(f"下载 {a.id}：{c['media'][:90]}", flush=True)
    if not http(c['media'], out=tmp, timeout=600):
        sys.exit('下载失败：网络问题或链接失效，换一个候选')
    t0, t1 = parse_t(a.t_from), parse_t(a.t_to)
    if c['type'] == 'video':
        dst = os.path.join(found, f'{no:02d}_{name}.mp4')
        dur = to_mp4(tmp, dst, t0, t1)
        os.remove(tmp)
        info = probe(dst)
    else:
        dst = os.path.join(found, f'{no:02d}_{name}{ext if ext in IMG_EXT else ".jpg"}')
        os.replace(tmp, dst)
        dur, info = None, dict(zip(('w', 'h'), shrink(dst)))
    row = dict(no=no, file=os.path.basename(dst), line=a.line, kind=COMMERCIAL, site=c['source'], page=c['page'],
               media=c['media'], author=c['author'], license=c['license'], credit=c['credit'],
               credit_text=c['credit_text'] if c['credit'] else '',
               span=(f'{fmt_t(t0 or 0)}–{fmt_t(t1)}' if t1 else ''), dur=round(dur, 2) if dur else None,
               size=f"{info.get('w', 0)}x{info.get('h', 0)}", date=f'{datetime.date.today()}', note=a.note or '')
    add_row(work, proj, row)
    print(f"✓ {row['file']}（{row['license']}{'，要署名' if row['credit'] else ''}）")


def _ytdlp(args):
    return subprocess.run([sys.executable, '-m', 'yt_dlp', '--no-playlist', '--no-warnings',
                           '--ffmpeg-location', os.path.dirname(tools.FFMPEG) or tools.FFMPEG] + args,
                          capture_output=True, text=True, encoding='utf-8', errors='replace')


def fetch_official_source(url, work):
    """官方视频原片缓存到 _工程/官方原片/；返回本地路径"""
    cache = os.path.join(work, '官方原片')
    os.makedirs(cache, exist_ok=True)
    key = hashlib.md5(url.encode()).hexdigest()[:12]
    for f in os.listdir(cache):
        if f.startswith(key):
            return os.path.join(cache, f)
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    if ext in ('.mp4', '.mov', '.webm', '.m4v'):
        p = os.path.join(cache, key + ext)
        if http(url, out=p, timeout=900):
            return p
    r = _ytdlp(['-f', 'bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b', '--merge-output-format', 'mp4',
                '-o', os.path.join(cache, key + '.%(ext)s'), url])
    for f in os.listdir(cache):
        if f.startswith(key) and not f.endswith(('.part', '.ytdl')):
            return os.path.join(cache, f)
    err = (r.stderr or r.stdout).strip().splitlines()[-3:]
    hint = ''
    if any('403' in e or 'Forbidden' in e for e in err):
        hint = '\n  403：先升级 yt-dlp（python -m pip install -U yt-dlp）再试'
    elif any('Unsupported URL' in e for e in err):
        hint = '\n  yt-dlp 认不出这个页面：在页面里找视频直链（.mp4），或换官方 YouTube / B 站链接'
    raise RuntimeError('下载失败：' + ' | '.join(err) + hint)


def cmd_official(a):
    proj, work, found = proj_dirs()
    lst = jload(os.path.join(work, '素材清单.json'), {'rows': [], 'skipped': []})
    no = a.no or next_no(lst['rows'])
    name = safe(a.name)
    ext = os.path.splitext(urlparse(a.url).path)[1].lower()
    t0, t1 = parse_t(a.t_from), parse_t(a.t_to)
    if ext in IMG_EXT:
        dst = os.path.join(found, f'{no:02d}_{name}{ext}')
        if not http(a.url, out=dst, timeout=120):
            sys.exit('图片下载失败：链接要是原图直链（右键图片「复制图片地址」）')
        from PIL import Image
        w, h = Image.open(dst).size
        dur, span, size = None, '', f'{w}x{h}'
    else:
        src = fetch_official_source(a.url, work)
        sd = probe(src).get('dur', 0)
        if t0 is None and t1 is None and sd > MAX_OFFICIAL_S + 0.5:
            print(f'原片 {sd:.1f} 秒，已下载到 {src}\n先看一遍挑 ≤10 秒的一段：'
                  f'python contact_sheet.py "{src}" 0 {sd:.0f} 3 看片.png，然后带 --from --to 再运行这条命令')
            return
        t0 = t0 or 0.0
        t1 = min(t1 if t1 is not None else sd, t0 + MAX_OFFICIAL_S, sd or 1e9)
        if (parse_t(a.t_to) or 0) - t0 > MAX_OFFICIAL_S + 0.01:
            print(f'  官方素材每段最多 {MAX_OFFICIAL_S:g} 秒：截到 {fmt_t(t1)}')
        dst = os.path.join(found, f'{no:02d}_{name}.mp4')
        dur = to_mp4(src, dst, t0, t1)
        info = probe(dst)
        span, size = f'{fmt_t(t0)}–{fmt_t(t1)}', f"{info.get('w', 0)}x{info.get('h', 0)}"
    row = dict(no=no, file=os.path.basename(dst), line=a.line, kind=OFFICIAL, site=a.source, page=a.page or a.url,
               media=a.url, author=a.source, license=OFFICIAL, credit=True,
               credit_text=f'画面来源：{a.source}', span=span, dur=round(dur, 2) if dur else None, size=size,
               date=f'{datetime.date.today()}', note=a.note or '')
    add_row(work, proj, row)
    print(f"✓ {row['file']}（{OFFICIAL}，来源：{a.source}）")


def cmd_skip(a):
    proj, work, _ = proj_dirs()
    lst = jload(os.path.join(work, '素材清单.json'), {'rows': [], 'skipped': []})
    lst['skipped'].append(dict(line=a.line, reason=a.reason, date=f'{datetime.date.today()}'))
    jsave(os.path.join(work, '素材清单.json'), lst)
    write_xlsx(proj, lst)
    print(f'记下了：跳过「{a.line[:30]}」（{a.reason}）')


def cmd_sync(a):
    proj, work, found = proj_dirs()
    lst = jload(os.path.join(work, '素材清单.json'), {'rows': [], 'skipped': []})
    keep = [r for r in lst['rows'] if os.path.exists(os.path.join(found, r['file']))]
    gone = [r['file'] for r in lst['rows'] if r not in keep]
    lst['rows'] = keep
    jsave(os.path.join(work, '素材清单.json'), lst)
    write_xlsx(proj, lst)
    print(f'清单还剩 {len(keep)} 个' + (f'；删掉了：{", ".join(gone)}' if gone else ''))


def cmd_sheet(a):
    proj, work, found = proj_dirs()
    lst = jload(os.path.join(work, '素材清单.json'), {'rows': [], 'skipped': []})
    rows = [r for r in lst['rows'] if os.path.exists(os.path.join(found, r['file']))]
    if not rows:
        sys.exit('还没有下载的素材')
    out = os.path.join(found, '素材拼图.jpg')
    make_sheet([(f"{r['no']:02d}", os.path.join(found, r['file']),
                 ('引用 ' if r['kind'] == OFFICIAL else '') + (r['line'] or '')[:22]) for r in rows],
               out, os.path.join(work, '候选拼图', 'thumbs'))
    print(f'素材拼图：{out}')


# ---------- 清单 xlsx / 授权清单 ----------

COLS = [('编号', 'no', 6), ('文件名', 'file', 30), ('对应口播句', 'line', 36), ('类别', 'kind', 14),
        ('来源网站', 'site', 18), ('来源页面', 'page', 40), ('媒体直链', 'media', 40), ('作者', 'author', 16),
        ('授权', 'license', 14), ('要署名', 'credit', 8), ('署名文字', 'credit_text', 40),
        ('原片区间', 'span', 14), ('时长(秒)', 'dur', 9), ('尺寸', 'size', 11), ('获取日期', 'date', 12),
        ('备注', 'note', 30)]


def write_xlsx(proj, lst):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        print('  （没装 openpyxl，素材清单.xlsx 没更新；_工程/素材清单.json 是全的）')
        return
    wb = Workbook()
    ws = wb.active
    ws.title = '素材清单'
    ws.append([c[0] for c in COLS])
    for r in lst['rows']:
        ws.append([('是' if r.get(k) else '否') if k == 'credit' else r.get(k) for _, k, _ in COLS])
    head = PatternFill('solid', fgColor='1F2937')
    for i, (_, _, w) in enumerate(COLS, 1):
        cell = ws.cell(1, i)
        cell.font, cell.fill = Font(bold=True, color='FFFFFF'), head
        ws.column_dimensions[cell.column_letter].width = w
    green, orange = PatternFill('solid', fgColor='DCFCE7'), PatternFill('solid', fgColor='FFEDD5')
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical='top', wrap_text=True)
        row[3].fill = orange if row[3].value == OFFICIAL else green
    ws.freeze_panes = 'C2'
    if lst.get('skipped'):
        s2 = wb.create_sheet('跳过的')
        s2.append(['口播句', '为什么跳过', '日期'])
        for r in lst['skipped']:
            s2.append([r['line'], r['reason'], r['date']])
        for col, w in zip('ABC', (50, 40, 12)):
            s2.column_dimensions[col].width = w
    p = os.path.join(proj, '素材清单.xlsx')
    try:
        wb.save(p)
    except PermissionError:
        print('  素材清单.xlsx 正被 Excel 打开着，没写进去：关掉它再运行 python find_assets.py sync')


def cmd_credits(a):
    proj, work, found = proj_dirs()
    lst = jload(os.path.join(work, '素材清单.json'), {'rows': [], 'skipped': []})
    rows = [r for r in lst['rows'] if os.path.exists(os.path.join(found, r['file']))]
    by = [r for r in rows if r['kind'] == COMMERCIAL and r['credit']]
    free = [r for r in rows if r['kind'] == COMMERCIAL and not r['credit']]
    off = [r for r in rows if r['kind'] == OFFICIAL]
    own = [f for f in os.listdir(os.path.join(proj, '3_素材')) if not f.startswith(('.', '找来的'))]
    L = ['# 授权清单', '', f'生成日期：{datetime.date.today()}', '']
    if off:
        srcs = sorted({r['site'] for r in off})
        L += ['## ⚠ 这条视频用了官方引用素材', '',
              f'共 {len(off)} 个，标「{OFFICIAL}」。科普、评论类视频一般算适当引用；**这条视频要是接商单或广告，先把它们换掉。**', '',
              '简介里贴这句：', '', '```', '画面来源：' + '、'.join(srcs), '```', '']
        L += ['| 文件 | 来源 | 来源页面 | 原片区间 |', '|---|---|---|---|']
        L += [f"| {r['file']} | {r['site']} | {r['page']} | {r['span']} |" for r in off] + ['']
    if by:
        L += ['## 简介里要贴的署名（CC BY）', '', '```']
        L += [r['credit_text'] for r in by] + ['```', '']
    if free:
        L += ['## 不用署名的素材', '']
        L += [f"- {r['file']}：{r['license']}（{r['site']}，{r['page']}）" for r in free] + ['']
    L += ['## 你自己放的素材', '',
          f'3_素材 里你自己放的 {len(own)} 个文件不查授权，版权由你自己负责。' if own else '没有。', '']
    if lst.get('skipped'):
        L += ['## 没找到、跳过的', ''] + [f"- {r['line']}：{r['reason']}" for r in lst['skipped']] + ['']
    os.makedirs(os.path.join(proj, '成片'), exist_ok=True)
    p = os.path.join(proj, '成片', '授权清单.md')
    open(p, 'w', encoding='utf-8').write('\n'.join(L))
    print(f'写好了：{p}')


def cmd_keys(a):
    k = keys()
    print(f"Pexels：{'已设置' if k.get('pexels') else '没有'}　Pixabay：{'已设置' if k.get('pixabay') else '没有'}　（存在 {KEYS}）")
    print('没有 key 也能用：Openverse 和 Wikimedia（图片为主，视频很少）。要多一些视频素材，注册一个免费 key（1 分钟）：')
    print('  Pexels：注册 https://www.pexels.com/join/ → 打开 https://www.pexels.com/api/new/ 填用途 → 复制 API Key')
    print('  Pixabay：注册 https://pixabay.com/accounts/register/ → 登录后打开 https://pixabay.com/api/docs/ ，页面里 key= 后面那串就是')
    print('然后在终端运行：python find_assets.py setkey pexels 你的KEY（key 只存在这台电脑上，不会进工程、不会上传）')


def cmd_setkey(a):
    k = keys()
    k[a.site] = a.key.strip()
    os.makedirs(os.path.dirname(KEYS), exist_ok=True)
    jsave(KEYS, k)
    try:
        os.chmod(KEYS, 0o600)
    except Exception:
        pass
    print(f'{a.site} key 存好了')


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('search')
    s.add_argument('query')
    s.add_argument('--type', default='image', choices=['image', 'video'])
    s.add_argument('--n', type=int, default=12)
    s.add_argument('--orient', default='', help='横 / 竖 / any；搜视频默认跟成片方向一致')
    s.add_argument('--min', type=int, default=1000, help='长边至少多少像素')
    g = sub.add_parser('get')
    g.add_argument('id')
    g.add_argument('--line', default='')
    g.add_argument('--name', default='')
    g.add_argument('--no', type=int, default=0)
    g.add_argument('--from', dest='t_from')
    g.add_argument('--to', dest='t_to')
    g.add_argument('--note', default='')
    o = sub.add_parser('official')
    o.add_argument('url')
    o.add_argument('--line', default='')
    o.add_argument('--name', required=True)
    o.add_argument('--source', required=True, help='例如「Unitree 官方」')
    o.add_argument('--page', default='')
    o.add_argument('--no', type=int, default=0)
    o.add_argument('--from', dest='t_from')
    o.add_argument('--to', dest='t_to')
    o.add_argument('--note', default='')
    k = sub.add_parser('skip')
    k.add_argument('--line', required=True)
    k.add_argument('--reason', required=True)
    sub.add_parser('sheet')
    sub.add_parser('sync')
    sub.add_parser('credits')
    sub.add_parser('keys')
    sk = sub.add_parser('setkey')
    sk.add_argument('site', choices=['pexels', 'pixabay'])
    sk.add_argument('key')
    a = ap.parse_args()
    {'search': cmd_search, 'get': cmd_get, 'official': cmd_official, 'skip': cmd_skip, 'sheet': cmd_sheet,
     'sync': cmd_sync, 'credits': cmd_credits, 'keys': cmd_keys, 'setkey': cmd_setkey}[a.cmd](a)


if __name__ == '__main__':
    main()
