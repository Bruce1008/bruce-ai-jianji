"""Timestamped contact sheet of a material clip, for finding usable moments.

usage: python contact_sheet.py <video> <t0> <t1> <step_s> <out.png>
tip: first pass step=3 over the whole clip, then step=1 (or 0.5) around candidate moments.
Each tile is the first decoded frame at/after its label, i.e. the same frame render.py shows for that src time.
(The ffmpeg fps filter was used before and labelled tiles ~half a step early; don't go back to it.)
"""
import subprocess, sys, json
import tools
import numpy as np
from PIL import Image, ImageDraw, ImageFont

src, t0, t1, step, out = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), sys.argv[5]
info = json.loads(subprocess.run([tools.FFPROBE, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                  'stream=width,height', '-of', 'json', src], capture_output=True, text=True).stdout)
vw, vh = info['streams'][0]['width'], info['streams'][0]['height']
w = 384
h = int(w * vh / vw) // 2 * 2
cmd = [tools.FFMPEG, '-v', 'error', '-ss', str(t0), '-i', src, '-t', str(t1 - t0),
       '-vf', f"select='gte(t\\,selected_n*{step})',scale={w}:{h}", '-fps_mode', 'vfr',
       '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
raw = subprocess.run(cmd, capture_output=True).stdout
n = len(raw) // (w * h * 3)
cols = 5
rows = max(1, (n + cols - 1) // cols)
sheet = Image.new('RGB', (cols * w, rows * h), 'black')
d = ImageDraw.Draw(sheet)
try:
    f = ImageFont.truetype('/Library/Fonts/SF-Pro-Display-Bold.otf', 22)
except Exception:
    f = ImageFont.load_default()
for i in range(n):
    im = Image.fromarray(np.frombuffer(raw[i * w * h * 3:(i + 1) * w * h * 3], np.uint8).reshape(h, w, 3))
    x, y = (i % cols) * w, (i // cols) * h
    sheet.paste(im, (x, y))
    d.rectangle([x, y, x + 84, y + 28], fill='black')
    d.text((x + 4, y + 2), f'{t0 + i * step:.1f}', font=f, fill='yellow')
sheet.save(out)
print(n, 'frames ->', out)
