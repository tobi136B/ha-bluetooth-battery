"""Erzeugt icon.png (128x128) und logo.png (250x100) für das Add-on.

Aufruf: python tools/make_icons.py bt_battery   (benötigt Pillow und DejaVu Fonts)
"""
import sys
from PIL import Image, ImageDraw, ImageFont

BLUE = (10, 132, 255, 255)
WHITE = (255, 255, 255, 255)
GREEN = (52, 199, 89, 255)
DARK = (28, 28, 30, 255)


def draw_symbol(size: int) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, s - 1, s - 1), fill=BLUE)
    # Bluetooth Rune, leicht nach links oben versetzt
    def p(x, y):
        return (s * x, s * y)
    cx, top, bot, w = 0.43, 0.2, 0.8, 0.13
    rune = [p(cx - w, 0.35), p(cx + w, 0.62), p(cx, 0.75), p(cx, 0.25), p(cx + w, 0.38), p(cx - w, 0.65)]
    d.line(rune, fill=WHITE, width=int(s * 0.065), joint="curve")
    # Akku Symbol unten rechts
    bx0, by0, bx1, by1 = 0.58, 0.6, 0.86, 0.78
    r = s * 0.03
    d.rounded_rectangle((*p(bx0, by0), *p(bx1, by1)), radius=r, fill=BLUE, outline=WHITE, width=int(s * 0.03))
    d.rectangle((*p(bx1 + 0.005, 0.66), *p(bx1 + 0.035, 0.72)), fill=WHITE)
    pad = 0.045
    level = 0.7
    fx1 = bx0 + pad + (bx1 - bx0 - 2 * pad) * level
    d.rounded_rectangle((*p(bx0 + pad, by0 + pad), *p(fx1, by1 - pad)), radius=r * 0.4, fill=GREEN)
    return img


def main(out_dir: str) -> None:
    big = draw_symbol(1024)
    big.resize((128, 128), Image.LANCZOS).save(f"{out_dir}/icon.png")

    # Logo: Symbol links, Schriftzug rechts
    scale = 4
    logo = Image.new("RGBA", (250 * scale, 100 * scale), (0, 0, 0, 0))
    logo.paste(draw_symbol(84 * scale), (8 * scale, 8 * scale))
    d = ImageDraw.Draw(logo)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font = ImageFont.truetype(font_path, 24 * scale)
    small = ImageFont.truetype(font_path.replace("-Bold", ""), 15 * scale)
    d.text((102 * scale, 22 * scale), "Bluetooth", font=font, fill=BLUE)
    d.text((102 * scale, 52 * scale), "Battery", font=font, fill=GREEN)
    logo.resize((250, 100), Image.LANCZOS).save(f"{out_dir}/logo.png")


if __name__ == "__main__":
    main(sys.argv[1])
