"""找 ffmpeg / ffprobe。Windows 上用 winget 刚装完时，当前终端的 PATH 还没更新，这里会去常见的安装位置找。"""
import os, sys, shutil, glob, platform

# Windows 终端默认 GBK，打印 ✓ ✗ 这类字符会报错：编不了的字换成 ?，不让脚本崩
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors='replace')
    except Exception:
        pass


def _find(name):
    env = os.environ.get('BAJ_' + name.upper())
    if env and os.path.exists(env):
        return env
    p = shutil.which(name)
    if p:
        return p
    if platform.system() == 'Windows':
        la = os.environ.get('LOCALAPPDATA', '')
        cands = [os.path.join(la, 'Microsoft', 'WinGet', 'Links', name + '.exe')]
        cands += glob.glob(os.path.join(la, 'Microsoft', 'WinGet', 'Packages', '*FFmpeg*', '*', 'bin', name + '.exe'))
        cands += [os.path.join('C:\\', 'ffmpeg', 'bin', name + '.exe'),
                  os.path.join(os.environ.get('ProgramFiles', 'C:\\Program Files'), 'ffmpeg', 'bin', name + '.exe')]
    else:
        cands = ['/opt/homebrew/bin/' + name, '/usr/local/bin/' + name]
    for c in cands:
        if os.path.exists(c):
            return c
    return name          # 找不到就用名字，报错时提示装 ffmpeg


def _style_hook():
    """环境变量 BAJ_STYLE=<风格>：这次运行用 styles/<风格>/theme.py，不用 _工程 里装好的那个（换风格试看、一条片子出几个风格）"""
    st = os.environ.get('BAJ_STYLE')
    if not st:
        return
    skill = None
    for p in ('project.json', os.path.join('_工程', 'project.json')):
        if os.path.exists(p):
            import json
            skill = json.load(open(p, encoding='utf-8')).get('skill_dir')
            break
    skill = skill or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(skill, 'styles', st)
    if not os.path.exists(os.path.join(d, 'theme.py')):
        sys.exit(f'BAJ_STYLE：没有风格「{st}」（{d}）')
    if d not in sys.path:
        sys.path.insert(0, d)


_style_hook()

FFMPEG = _find('ffmpeg')
FFPROBE = _find('ffprobe')
