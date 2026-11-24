"""开源字体：清单、下载、加载。全部是 SIL OFL（可商用、可嵌入视频），第一次用时下载到 ~/.bruce-ai-jianji/fonts/。

usage:
  python fonts.py ensure [key ...]     下载缺的字体（不写 key = 全部）
  python fonts.py list                 列出字体和是否已下载

在代码里：
  import fonts
  tf = fonts.typeface('noto_sans_sc', 700)    # skia.Typeface；可变字体按字重克隆
"""
import os, sys, functools, subprocess, shutil, tempfile

FONT_DIR = os.environ.get('BAJ_FONTS') or os.path.join(os.path.expanduser('~'), '.bruce-ai-jianji', 'fonts')

_GF = 'google/fonts@main/ofl/'
_GF_RAW = 'https://raw.githubusercontent.com/google/fonts/main/ofl/'


def _gf(path):
    """google/fonts 仓库里的文件：先 jsDelivr（国内一般能连），再 GitHub"""
    return ['https://cdn.jsdelivr.net/gh/' + _GF + path.replace('[', '%5B').replace(']', '%5D'),
            _GF_RAW + path.replace('[', '%5B').replace(']', '%5D')]


# key: (文件名, 下载地址列表, 说明, 是否可变字体)
FONTS = {
    'noto_sans_sc':  ('NotoSansSC[wght].ttf', _gf('notosanssc/NotoSansSC[wght].ttf'), '思源黑体（通用正文、缺字兜底）', True),
    'noto_serif_sc': ('NotoSerifSC[wght].ttf', _gf('notoserifsc/NotoSerifSC[wght].ttf'), '思源宋体（报刊、黑底科技）', True),
    'xiaolai':       ('Xiaolai-Regular.ttf',
                      ['https://github.com/lxgw/kose-font/releases/download/v3.126/Xiaolai-Regular.ttf'],
                      '小赖字体（手写：手绘笔记的正文和字幕）', False),
    'zcool_kuaile':  ('ZCOOLKuaiLe-Regular.ttf', _gf('zcoolkuaile/ZCOOLKuaiLe-Regular.ttf'), '站酷快乐体（圆粗标题、印章字）', False),
    'nunito':        ('Nunito[wght].ttf', _gf('nunito/Nunito[wght].ttf'), 'Nunito（圆头英文）', True),
    'bebas_neue':    ('BebasNeue-Regular.ttf', _gf('bebasneue/BebasNeue-Regular.ttf'), 'Bebas Neue（华尔街财经大数字）', False),
    'montserrat':    ('Montserrat[wght].ttf', _gf('montserrat/Montserrat[wght].ttf'), 'Montserrat（西文无衬线）', True),
    'playfair':      ('PlayfairDisplay[wght].ttf', _gf('playfairdisplay/PlayfairDisplay[wght].ttf'), 'Playfair Display（西文衬线）', True),
}


def path(key):
    return os.path.join(FONT_DIR, FONTS[key][0])


def have(key):
    p = path(key)
    return os.path.exists(p) and os.path.getsize(p) > 50_000


def _download(url, dest):
    """curl（python.org 的 Python 常缺证书，curl 更稳），失败返回 False"""
    tmp = dest + '.part'
    curl = shutil.which('curl') or shutil.which('curl.exe')
    if curl:
        r = subprocess.run([curl, '-sfL', '--retry', '2', '--connect-timeout', '15', '--max-time', '600',
                            '-o', tmp, url])
        ok = r.returncode == 0
    else:
        import urllib.request
        try:
            urllib.request.urlretrieve(url, tmp)
            ok = True
        except Exception:
            ok = False
    if ok and os.path.exists(tmp) and os.path.getsize(tmp) > 50_000:
        with open(tmp, 'rb') as f:
            head = f.read(4)
        if head in (b'\x00\x01\x00\x00', b'OTTO', b'true', b'ttcf'):
            os.replace(tmp, dest)
            return True
    if os.path.exists(tmp):
        os.remove(tmp)
    return False


def ensure(keys=None, quiet=False):
    """下载缺的字体；返回下载失败的 key 列表"""
    os.makedirs(FONT_DIR, exist_ok=True)
    failed = []
    for k in (keys or FONTS):
        if have(k):
            continue
        name, urls, note, _ = FONTS[k]
        if not quiet:
            print(f'下载字体 {name}（{note}）…', flush=True)
        if not any(_download(u, path(k)) for u in urls):
            failed.append(k)
            print(f'  ✗ {name} 下载失败。可以手动下载放到 {FONT_DIR}：{urls[0]}', flush=True)
    return failed


@functools.lru_cache(None)
def _base(key):
    import skia
    if not have(key):
        ensure([key], quiet=True)
    tf = skia.Typeface.MakeFromFile(path(key)) if have(key) else None
    if tf is None:
        raise RuntimeError(f'字体 {FONTS[key][0]} 不可用：先运行 python fonts.py ensure {key}')
    return tf


@functools.lru_cache(None)
def typeface(key, weight=400):
    """skia.Typeface；可变字体（[wght]）按 weight 克隆出对应字重"""
    import skia
    tf = _base(key)
    if not FONTS[key][3]:
        return tf
    # skia-python 不替我们保留这些对象：中间对象要一直留着引用，否则字重会被悄悄忽略
    coord = skia.FontArguments.VariationPosition.Coordinate(int.from_bytes(b'wght', 'big'), float(weight))
    coords = skia.FontArguments.VariationPosition.Coordinates([coord])
    pos = skia.FontArguments.VariationPosition(coords)
    args = skia.FontArguments()
    args.setVariationDesignPosition(pos)
    _KEEP.extend([coord, coords, pos, args])
    return tf.makeClone(args) or tf


_KEEP = []


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'list'
    if cmd == 'ensure':
        bad = ensure(sys.argv[2:] or None)
        print('字体齐了' if not bad else f'还缺：{bad}')
        sys.exit(1 if bad else 0)
    for k, (name, urls, note, var) in FONTS.items():
        print(f"{'✓' if have(k) else '✗'} {k:14s} {name:28s} {note}")
    print('字体文件夹：', FONT_DIR)
