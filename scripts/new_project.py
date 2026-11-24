"""第 2 步：建工程文件夹。

usage: python new_project.py <放在哪> [--name 片名] [--orient 横屏|竖屏] [--no-open]

在 <放在哪> 下面建 「YYYY-MM-DD_片名」（没给片名叫「YYYY-MM-DD_剪辑工程」，重名自动加 _2、_3）：
  1_口播稿/  2_口播视频/  3_素材/找来的/  4_参考图/  5_BGM/  _工程/  成片/  修改表.xlsx  先看我.txt
_工程/ 里放一份剪辑脚本和 project.json（横屏还是竖屏、技能在哪、用哪个 Python），以后改片子都从这里接着做。
最后打开这个文件夹，最后一行打印 PROJECT=<路径>。
"""
import os, sys, re, json, shutil, datetime, platform, subprocess, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import tools  # noqa: E402,F401  （Windows 终端打印中文不崩）

FOLDERS = ['1_口播稿', '2_口播视频', '3_素材', os.path.join('3_素材', '找来的'), '4_参考图', '5_BGM', '_工程', '成片']
NO_COPY = {'check_env.py', 'new_project.py'}

README = """这个文件夹是一条视频的工程。东西放进对应的文件夹，然后回到对话里告诉 AI「放好了」。

1_口播稿     口播稿：docx / txt / md / rtf 都行；画面要求多的话用三列脚本表（技能文件夹 模板/脚本表模板.csv）
2_口播视频   你录的口播视频，一条或几条（几条按文件名顺序接起来）；只有录音也行，那就全程放画面
3_素材       你自己的图片、视频、录屏。文件名写清楚是什么，AI 更容易用对地方
  找来的     AI 帮你找的素材放这里，来源和授权记在 素材清单.xlsx
4_参考图     可选：想要的调色效果、想要的画面风格，各放一两张截图
5_BGM        可选：背景音乐，放一首就行（要可商用的）
修改表.xlsx  看完成片要改哪里写在这里，状态选「待改」；AI 只读不改，改完你自己标「已改」
_工程        剪辑的中间文件，以后改片子要用，别删
成片         开头 15 秒预览、成片、无字幕版、字幕、授权清单都在这里
"""


def safe_name(s):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', s).strip().strip('.')
    return s[:60] or '剪辑工程'


def open_folder(p):
    try:
        if platform.system() == 'Windows':
            os.startfile(p)          # noqa: 只在 Windows 有
        elif platform.system() == 'Darwin':
            subprocess.run(['open', p])
        else:
            subprocess.run(['xdg-open', p])
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('where')
    ap.add_argument('--name', default='剪辑工程')
    ap.add_argument('--orient', default='横屏', choices=['横屏', '竖屏'])
    ap.add_argument('--no-open', action='store_true')
    a = ap.parse_args()

    where = os.path.abspath(os.path.expanduser(a.where))
    os.makedirs(where, exist_ok=True)
    base = f'{datetime.date.today():%Y-%m-%d}_{safe_name(a.name)}'
    proj, k = os.path.join(where, base), 2
    while os.path.exists(proj):
        proj, k = os.path.join(where, f'{base}_{k}'), k + 1

    for f in FOLDERS:
        os.makedirs(os.path.join(proj, f))
    shutil.copy(os.path.join(SKILL_DIR, '模板', '修改表模板.xlsx'), os.path.join(proj, '修改表.xlsx'))
    open(os.path.join(proj, '先看我.txt'), 'w', encoding='utf-8').write(README)

    work = os.path.join(proj, '_工程')
    for f in os.listdir(HERE):
        if f.endswith('.py') and f not in NO_COPY:
            shutil.copy(os.path.join(HERE, f), work)
    cfg = dict(orient=a.orient, name=a.name, created=f'{datetime.datetime.now():%Y-%m-%d %H:%M}',
               skill_dir=SKILL_DIR, python=sys.executable, style=None)
    json.dump(cfg, open(os.path.join(work, 'project.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    if not a.no_open:
        open_folder(proj)
    print(f'建好了：{proj}（{a.orient}，{"1920x1080" if a.orient == "横屏" else "1080x1920"}）')
    print('请把东西放进去：口播稿 → 1_口播稿，口播视频 → 2_口播视频，自己的素材 → 3_素材（可选：参考图、BGM）')
    print(f'PROJECT={proj}')


if __name__ == '__main__':
    main()
