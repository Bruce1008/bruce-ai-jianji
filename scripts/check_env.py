"""第 1 步：检查并安装环境（Mac + Windows）。

usage:
  python check_env.py              只检查，打印一张表
  python check_env.py --install    缺什么装什么：ffmpeg、Python 包、字体、转写模型（约 2–3 GB，看网速 5–30 分钟）
  python check_env.py --no-model   检查/安装时跳过转写模型

最后一行是 PYTHON=<路径>：之后所有脚本都用这个 Python 运行（可能是专用环境 ~/.bruce-ai-jianji/venv）。

装在哪：
  Python 包    当前 Python 已经全有就直接用；否则建一个专用环境 ~/.bruce-ai-jianji/venv，不动你电脑上别的 Python
  ffmpeg       Mac 用 Homebrew，Windows 用 winget
  字体         ~/.bruce-ai-jianji/fonts（全部是可商用的开源字体）
  转写模型     ~/.cache/huggingface（whisper-large-v3-turbo，约 1.5 GB）
国内网络：pip 自动挑清华镜像和官方源里快的那个；huggingface 连不上用 hf-mirror.com；Homebrew 连不上 ghcr.io 用清华镜像。
不需要 Node.js，也不需要 Chrome。
"""
import os, sys, json, platform, subprocess, shutil, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tools, fonts  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors='replace')
    except Exception:
        pass

HOME = os.environ.get('BAJ_HOME') or os.path.join(os.path.expanduser('~'), '.bruce-ai-jianji')
VENV = os.path.join(HOME, 'venv')
CONFIG = os.path.join(HOME, 'config.json')
IS_WIN = platform.system() == 'Windows'
IS_MAC = platform.system() == 'Darwin'
APPLE_SILICON = IS_MAC and platform.machine() == 'arm64'
MIN_PY = (3, 9)

# (import 名, pip 名)
PKGS = [('numpy', 'numpy'), ('scipy', 'scipy'), ('PIL', 'pillow'), ('skia', 'skia-python'),
        ('pyloudnorm', 'pyloudnorm'), ('openpyxl', 'openpyxl'), ('yt_dlp', 'yt-dlp')]
PKGS.append(('mlx_whisper', 'mlx-whisper') if APPLE_SILICON else ('faster_whisper', 'faster-whisper'))
PIN = {'skia-python': 'skia-python==144.0.post2'}      # 引擎用这个版本测过
MODEL = 'mlx-community/whisper-large-v3-turbo' if APPLE_SILICON else 'large-v3-turbo'

PYPI = 'https://pypi.org/simple'
TUNA = 'https://pypi.tuna.tsinghua.edu.cn/simple'


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', **kw)


def venv_python():
    return os.path.join(VENV, 'Scripts', 'python.exe') if IS_WIN else os.path.join(VENV, 'bin', 'python')


# ---------- 查 ----------

PROBE = r'''
import sys, json, importlib, importlib.util
try:
    from importlib.metadata import version as _v
except Exception:
    _v = None
pk = json.loads(sys.argv[1])
out = {"version": list(sys.version_info[:3]), "exe": sys.executable, "pkgs": {}}
for mod, pip in pk:
    ok = importlib.util.find_spec(mod) is not None
    ver = None
    if ok:
        try:
            ver = _v(pip) if _v else "ok"
        except Exception:
            ver = "ok"
        if mod in ("skia", "numpy", "scipy", "PIL"):
            try:
                importlib.import_module(mod)
            except Exception as e:
                ok, ver = False, None
    out["pkgs"][pip] = ver if ok else None
try:
    from huggingface_hub import constants
    out["hf_cache"] = constants.HF_HUB_CACHE
except Exception:
    out["hf_cache"] = None
print("@@" + json.dumps(out))
'''


def probe_python(py):
    """在 py 里查版本和包；py 不能用返回 None"""
    try:
        r = run([py, '-c', PROBE, json.dumps(PKGS)], timeout=180)
    except Exception:
        return None
    line = next((l for l in r.stdout.splitlines() if l.startswith('@@')), None)
    return json.loads(line[2:]) if line else None


def missing_pkgs(info):
    return [pip for _, pip in PKGS if not (info and info['pkgs'].get(pip))]


def ffmpeg_info():
    ff = tools._find('ffmpeg')
    fp = tools._find('ffprobe')
    try:
        r = run([ff, '-hide_banner', '-version'], timeout=20)
        ok = r.returncode == 0 and os.path.basename(fp).startswith('ffprobe') and \
            run([fp, '-version'], timeout=20).returncode == 0
    except Exception:
        return None
    if not ok:
        return None
    first = r.stdout.splitlines()[0] if r.stdout else ''
    ver = first.split()[2] if len(first.split()) > 2 else '?'
    return dict(path=ff, version=ver, x264='--enable-libx264' in r.stdout)


def model_cached(info):
    cache = (info or {}).get('hf_cache') or os.path.join(os.path.expanduser('~'), '.cache', 'huggingface', 'hub')
    if not os.path.isdir(cache):
        return False
    for d in os.listdir(cache):
        if 'whisper-large-v3-turbo' in d:
            snap = os.path.join(cache, d, 'snapshots')
            if os.path.isdir(snap) and any(os.listdir(snap)):
                return True
    return False


def pick_python():
    """选一个 Python：专用环境 > 当前 Python（包齐） > None（要建专用环境）"""
    if os.path.exists(venv_python()):
        return venv_python(), probe_python(venv_python())
    cur = probe_python(sys.executable)
    if cur and tuple(cur['version'][:2]) >= MIN_PY and not missing_pkgs(cur):
        return sys.executable, cur
    return None, cur


# ---------- 装 ----------

def _latency(url):
    curl = shutil.which('curl') or shutil.which('curl.exe')
    if not curl:
        return None
    t = time.time()
    r = run([curl, '-s', '-o', os.devnull, '-f', '--max-time', '6', url + '/pip/'])
    return time.time() - t if r.returncode == 0 else None


def pip_index():
    if os.environ.get('BAJ_PIP_INDEX'):
        return os.environ['BAJ_PIP_INDEX']
    a, b = _latency(PYPI), _latency(TUNA)
    if a is None and b is None:
        return PYPI
    if a is None or (b is not None and b < a * 0.7):
        return TUNA
    return PYPI


def base_python():
    """用来建专用环境的 Python：优先 3.12 / 3.11 / 3.10 / 3.13，其次当前 Python"""
    cands = []
    if IS_WIN:
        py = shutil.which('py')
        if py:
            for v in ('3.12', '3.11', '3.10', '3.13'):
                r = run([py, f'-{v}', '-c', 'import sys;print(sys.executable)'])
                if r.returncode == 0 and r.stdout.strip():
                    cands.append(r.stdout.strip())
    else:
        for v in ('3.12', '3.11', '3.10', '3.13'):
            for p in (shutil.which(f'python{v}'), f'/opt/homebrew/bin/python{v}', f'/usr/local/bin/python{v}'):
                if p and os.path.exists(p):
                    cands.append(p)
    if sys.version_info[:2] >= MIN_PY:
        cands.append(sys.executable)
    for c in cands:
        r = run([c, '-c', 'import venv, sys; print(sys.version_info[:2] >= (3, 9))'])
        if r.returncode == 0 and r.stdout.strip() == 'True':
            return c
    return None


def install_python():
    if IS_MAC and shutil.which('brew'):
        print('用 Homebrew 装 Python 3.12 …', flush=True)
        brew(['install', 'python@3.12'])
    elif IS_WIN and shutil.which('winget'):
        print('用 winget 装 Python 3.12（可能弹出管理员确认）…', flush=True)
        subprocess.run(['winget', 'install', '-e', '--id', 'Python.Python.3.12',
                        '--accept-source-agreements', '--accept-package-agreements'])
    return base_python()


def brew(args):
    env = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE='1', HOMEBREW_NO_INSTALL_CLEANUP='1')
    curl = shutil.which('curl')
    if curl and run([curl, '-sI', '--max-time', '6', 'https://ghcr.io']).returncode != 0:
        print('连不上 ghcr.io，Homebrew 改用清华镜像', flush=True)
        env.update(HOMEBREW_API_DOMAIN='https://mirrors.tuna.tsinghua.edu.cn/homebrew-bottles/api',
                   HOMEBREW_BOTTLE_DOMAIN='https://mirrors.tuna.tsinghua.edu.cn/homebrew-bottles')
    return subprocess.run(['brew'] + args, env=env).returncode == 0


def install_ffmpeg():
    if IS_MAC:
        if not shutil.which('brew'):
            return ('Mac 装 ffmpeg 要先装 Homebrew，它会要开机密码，只能你自己在「终端」里运行：\n'
                    '      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"\n'
                    '    装完按提示把 brew 加进 PATH，然后告诉 AI「装好了」。国内网络慢可以看 references/01-装环境.md 里的镜像装法。')
        print('用 Homebrew 装 ffmpeg（依赖多，3–10 分钟）…', flush=True)
        brew(['install', 'ffmpeg'])
    elif IS_WIN:
        if not shutil.which('winget'):
            return ('这台 Windows 没有 winget：在微软商店装「应用安装程序」(App Installer)，'
                    '或者从 https://www.gyan.dev/ffmpeg/builds/ 下载 ffmpeg-release-essentials.zip，解压到 C:\\ffmpeg。')
        print('用 winget 装 ffmpeg …', flush=True)
        subprocess.run(['winget', 'install', '-e', '--id', 'Gyan.FFmpeg',
                        '--accept-source-agreements', '--accept-package-agreements'])
    else:
        return '这个脚本只管 Mac 和 Windows。Linux 请用系统的包管理器装 ffmpeg。'
    return None if ffmpeg_info() else 'ffmpeg 装完还是找不到：关掉终端重开一次再运行检查；还不行就把 ffmpeg 所在文件夹告诉 AI。'


def make_venv():
    base = base_python() or install_python()
    if not base:
        if IS_MAC:
            return None, '找不到 3.9 以上的 Python：在「终端」运行 xcode-select --install（装苹果命令行工具，自带 Python），装完再检查。'
        return None, '找不到 3.9 以上的 Python：到 https://www.python.org/downloads/ 下载安装，勾上 “Add python.exe to PATH”。'
    print(f'建专用环境 {VENV}（用 {base}）…', flush=True)
    os.makedirs(HOME, exist_ok=True)
    r = run([base, '-m', 'venv', VENV])
    if r.returncode != 0:
        return None, '建专用环境失败：' + (r.stderr or r.stdout)[-400:]
    return venv_python(), None


def pip_install(py, pkgs):
    idx = pip_index()
    print(f'装 Python 包：{" ".join(pkgs)}\n  源：{idx}', flush=True)
    subprocess.run([py, '-m', 'pip', 'install', '-q', '--upgrade', 'pip', '-i', idx, '--timeout', '60'])
    args = [PIN.get(p, p) for p in pkgs]
    r = subprocess.run([py, '-m', 'pip', 'install', '--upgrade', '-i', idx, '--timeout', '60'] + args)
    if r.returncode != 0 and idx != TUNA:
        print('官方源失败，换清华镜像再试 …', flush=True)
        r = subprocess.run([py, '-m', 'pip', 'install', '--upgrade', '-i', TUNA, '--timeout', '60'] + args)
    return r.returncode == 0


DL_MODEL = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
import transcribe as TR
TR._setup_mirror()
if TR.engine() == "mlx":
    from huggingface_hub import snapshot_download
    snapshot_download(os.environ.get("BAJ_WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo"))
else:
    from faster_whisper import download_model
    download_model(os.environ.get("BAJ_WHISPER_MODEL", "large-v3-turbo"))
print("模型下载好了")
'''


def download_model(py):
    print('下载转写模型 whisper-large-v3-turbo（约 1.5 GB）…', flush=True)
    return subprocess.run([py, '-c', DL_MODEL, HERE]).returncode == 0


# ---------- 主流程 ----------

def main():
    install = '--install' in sys.argv
    want_model = '--no-model' not in sys.argv
    problems = []

    # ffmpeg
    ff = ffmpeg_info()
    if not ff and install:
        msg = install_ffmpeg()
        ff = ffmpeg_info()
        if msg and not ff:
            problems.append(msg)

    # Python 和包
    py, info = pick_python()
    if install:
        if not py:
            py, err = make_venv()
            if err:
                problems.append(err)
            info = probe_python(py) if py else None
        miss = missing_pkgs(info) if py else []
        if py and miss:
            if not pip_install(py, miss):
                problems.append('Python 包没装全：把上面 pip 的报错发给 AI 看。')
            info = probe_python(py)
    miss = missing_pkgs(info)

    # 字体
    if install:
        fonts.ensure()
    nf = sum(fonts.have(k) for k in fonts.FONTS)

    # 转写模型
    have_model = model_cached(info)
    if install and want_model and py and not miss and not have_model:
        if not download_model(py):
            problems.append('转写模型没下载成功（网络问题居多）：再运行一次 --install 会接着下。')
        have_model = model_cached(probe_python(py))

    # 报告
    ok = lambda b: '✓' if b else '✗'
    ver = '.'.join(map(str, info['version'])) if info else '?'
    print('\n环境检查')
    print(f'  {ok(bool(ff))} ffmpeg      ' + (f'{ff["version"]}  {ff["path"]}' if ff else '没找到'))
    if ff and not ff['x264']:
        print('      ⚠ 这个 ffmpeg 没有 libx264，导出 mp4 会失败：换成 Homebrew / gyan.dev 的完整版')
    print(f'  {ok(bool(py))} Python      ' + (f'{ver}  {py}' if py else f'当前 {ver} 缺包，需要建专用环境'))
    print(f'  {ok(not miss)} Python 包   ' + ('齐了' if not miss else '缺 ' + ', '.join(miss)))
    print(f'  {ok(nf == len(fonts.FONTS))} 字体        {nf}/{len(fonts.FONTS)}  {fonts.FONT_DIR}' +
          ('' if nf == len(fonts.FONTS) else '（缺的用到时自动下载）'))
    print(f'  {ok(have_model)} 转写模型    ' + ('whisper-large-v3-turbo' if have_model else
                                               '还没下载（第一次转写时会自动下载，约 1.5 GB）'))
    print('  ─ 不需要 Node.js / Chrome')
    for p in problems:
        print('\n  ✗ ' + p)

    ready = bool(ff and py and not miss and ff['x264'])
    if ready:
        os.makedirs(HOME, exist_ok=True)
        json.dump({'python': py, 'skill_dir': os.path.dirname(HERE)}, open(CONFIG, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        print('\n环境齐了。之后都用这个 Python 运行脚本：')
        print(f'PYTHON={py}')
    else:
        if not install:
            print('\n还没齐：运行 python check_env.py --install 自动装。')
        sys.exit(1)


if __name__ == '__main__':
    main()
