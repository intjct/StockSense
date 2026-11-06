"""Draws assets/stocksense.ico and stocksense.png (run once; output is committed)."""
import os

from PIL import Image, ImageDraw

S = 1024
here = os.path.dirname(os.path.abspath(__file__))


def draw(size=S):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    k = size / S
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(230 * k), fill=(13, 13, 13, 255))
    # rising line
    pts = [(200, 700), (390, 520), (540, 610), (800, 330)]
    d.line([(x * k, y * k) for x, y in pts], fill=(200, 245, 60, 255), width=int(78 * k), joint="curve")
    for x, y in pts[:-1]:
        r = 39 * k
        d.ellipse([x * k - r, y * k - r, x * k + r, y * k + r], fill=(200, 245, 60, 255))
    # arrow head
    d.polygon([(860 * k, 270 * k), (860 * k, 470 * k), (660 * k, 270 * k)], fill=(200, 245, 60, 255))
    return im


big = draw(1024)
big.resize((256, 256), Image.LANCZOS).save(os.path.join(here, "stocksense.png"))
big.save(os.path.join(here, "stocksense.ico"), sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
print("ok")
