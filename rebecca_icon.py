"""Draws Rebecca's tray icon. Pillow only, so it also works headless (used to generate assets/rebecca.ico)."""
from PIL import Image, ImageDraw

MODE_COLORS = {"orbit": (0, 220, 255), "pan": (61, 255, 156), "zoom": (255, 196, 0), "twist": (255, 80, 200)}


def make_icon(live=False, mode=None, size=64):
    """Idle: grey ring + two dots (a 'pinch'). Live: cyan ring; centre dot grows and changes colour per gesture."""
    s = size / 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ring = (0, 220, 255, 255) if live else (120, 140, 150, 255)
    d.ellipse((3 * s, 3 * s, 61 * s, 61 * s), fill=(3, 16, 26, 255), outline=ring, width=max(1, int(5 * s)))
    if live:
        col = MODE_COLORS.get(mode, (0, 220, 255))
        r = (15 if mode else 6) * s
        d.ellipse((32 * s - r, 32 * s - r, 32 * s + r, 32 * s + r), fill=col + (255,))
    else:
        for cx in (25, 39):
            d.ellipse(((cx - 4) * s, 28 * s, (cx + 4) * s, 36 * s), fill=ring)
    return img


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "assets/rebecca.ico"
    make_icon(True, "orbit", 256).save(out, format="ICO",
                                       sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", out)
