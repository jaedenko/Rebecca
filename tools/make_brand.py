"""Regenerates the logo files and the social preview image:  python tools/make_brand.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from PIL import Image, ImageDraw, ImageFont

from rebecca_icon import MODE_COLORS, make_icon

INK = (4, 18, 26)
OUT = os.path.join(os.path.dirname(__file__), "..", "site")
BOLD = next((p for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/segoeuib.ttf",
                         "/System/Library/Fonts/Supplemental/Arial Bold.ttf") if os.path.exists(p)), None)


def icon(mode="orbit", size=1024):
    """Supersampled so the edges are smooth at large sizes."""
    return make_icon(True, mode, size * 4).resize((size, size), Image.LANCZOS)


def grid(img):
    d = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    for x in range(0, w, 48):
        d.line([(x, 0), (x, h)], fill=(0, 220, 255, 14), width=1)
    for y in range(0, h, 48):
        d.line([(0, y), (w, y)], fill=(0, 220, 255, 14), width=1)
    return d


def font(size):
    return ImageFont.truetype(BOLD, size) if BOLD else ImageFont.load_default()


def social_preview(path):
    W, H, LEFT = 1200, 630, 330
    img = Image.new("RGB", (W, H), INK)
    d = grid(img)

    def fit(text, size):
        while size > 16 and d.textlength(text, font=font(size)) > W - LEFT - 60:
            size -= 1
        return font(size)
    ic = icon("orbit", 200)
    img.paste(ic, (80, 165), ic)
    d.text((LEFT, 150), "Rebecca", font=fit("Rebecca", 110), fill=(216, 250, 255))
    tag = "Inspect CAD models with your hands."
    d.text((LEFT + 2, 285), tag, font=fit(tag, 40), fill=(143, 179, 190))
    x = LEFT + 2
    for label, mode in (("ORBIT", "orbit"), ("PAN", "pan"), ("ZOOM", "zoom"), ("TWIST", "twist")):
        col = MODE_COLORS[mode]
        w = int(d.textlength(label, font=font(26))) + 70
        d.rounded_rectangle([x, 400, x + w, 452], radius=26, fill=(7, 21, 30), outline=col + (255,), width=3)
        d.ellipse([x + 20, 420, x + 32, 432], fill=col + (255,))
        d.text((x + 44, 413), label, font=font(26), fill=(216, 250, 255))
        x += w + 16
    foot = "Version 1.0. Free and open source. Windows 10 and 11."
    d.text((LEFT + 2, 520), foot, font=fit(foot, 26), fill=(143, 179, 190))
    img.save(path, optimize=True)


if __name__ == "__main__":
    brand = os.path.join(OUT, "brand")
    os.makedirs(brand, exist_ok=True)
    icon("orbit", 1024).save(os.path.join(brand, "rebecca-icon.png"))
    for m in MODE_COLORS:
        icon(m, 512).save(os.path.join(brand, f"rebecca-icon-{m}.png"))
    sq = Image.new("RGB", (1080, 1080), INK)
    grid(sq)
    ic = icon("orbit", 560)
    sq.paste(ic, (260, 260), ic)
    sq.save(os.path.join(brand, "rebecca-icon-dark-1080.png"), optimize=True)
    open(os.path.join(brand, "rebecca-icon.svg"), "w").write(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><circle cx="32" cy="32" r="26.5" fill="#03101a" '
        'stroke="#00dcff" stroke-width="5"/><circle cx="32" cy="32" r="15" fill="#00dcff"/></svg>\n')
    social_preview(os.path.join(OUT, "og.png"))
    print("brand files written to", os.path.abspath(brand))
