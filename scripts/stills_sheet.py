"""Render several composed frames and tile them 2-up into one image for quick review.

usage: python stills_sheet.py <out.png> t1 t2 t3 ...
(cheap: a few seconds; use this instead of rendering video while iterating)
"""
import sys, subprocess
from PIL import Image

out = sys.argv[1]
ts = [float(x) for x in sys.argv[2:]]
subprocess.run([sys.executable, 'render.py', 'stills'] + [str(t) for t in ts], check=True, capture_output=True)
ims = [Image.open(f'stills/f{t:07.2f}.png').resize((960, 540)) for t in ts]
rows = (len(ims) + 1) // 2
s = Image.new('RGB', (1920, 540 * rows), 'white')
for i, im in enumerate(ims):
    s.paste(im, ((i % 2) * 960, (i // 2) * 540))
s.save(out)
print('->', out)
