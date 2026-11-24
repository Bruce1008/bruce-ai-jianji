"""Exact frames at given source times (accurate single-frame seeks), tiled 5-up with labels.

usage: python frames_at.py <video> <out.png> t1 t2 ...
Use it to confirm a material moment before pinning it to a word: the tile at T is what render.py shows for src T."""
import sys, subprocess, io
import tools
from PIL import Image, ImageDraw, ImageFont
src, out, ts = sys.argv[1], sys.argv[2], [float(x) for x in sys.argv[3:]]
ims = []
for t in ts:
    b = subprocess.run([tools.FFMPEG, '-v', 'error', '-ss', str(t), '-i', src, '-frames:v', '1', '-vf', 'scale=384:-2', '-f', 'image2pipe', '-vcodec', 'png', '-'], capture_output=True).stdout
    ims.append(Image.open(io.BytesIO(b)).convert('RGB'))
w, h = ims[0].size
cols = 5; rows = (len(ims) + cols - 1) // cols
sheet = Image.new('RGB', (cols * w, rows * h))
d = ImageDraw.Draw(sheet)
f = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Bold.ttf', 22)
for i, (im, t) in enumerate(zip(ims, ts)):
    x, y = (i % cols) * w, (i // cols) * h
    sheet.paste(im, (x, y)); d.rectangle([x, y, x + 80, y + 28], fill='black'); d.text((x + 4, y + 2), f'{t:.2f}', font=f, fill='yellow')
sheet.save(out); print(out)
