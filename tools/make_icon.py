"""Sinh icon thương hiệu (assets/icon.ico + icon.png).

Tile bo góc accent phẳng với chữ 'T' trắng — khớp mark trong app
(`ui_utils._render_icon_pixmap`), không gradient. Chạy lại khi đổi nhận diện:

    python tools/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BRAND = (91, 98, 240)  # #5b62f0 — accent phẳng, khớp ui_utils.BRAND
ASSETS = Path(__file__).resolve().parents[1] / "python-app" / "assets"
_FONT_CANDIDATES = (
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/seguisb.ttf",
)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, int(size * 0.58))
    return ImageFont.load_default()


def render(size: int) -> Image.Image:
    scale = 4  # vẽ lớn rồi thu nhỏ để cạnh mượt (supersampling)
    big = size * scale
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))

    margin = round(big * 0.07)
    radius = round(big * 0.28)
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (margin, margin, big - margin, big - margin), radius=radius, fill=255
    )
    tile = Image.new("RGBA", (big, big), (*BRAND, 255))
    canvas.paste(tile, (0, 0), mask)

    draw = ImageDraw.Draw(canvas)
    font = _load_font(big)
    box = draw.textbbox((0, 0), "T", font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    draw.text(
        ((big - tw) / 2 - box[0], (big - th) / 2 - box[1]),
        "T",
        font=font,
        fill=(255, 255, 255, 255),
    )
    return canvas.resize((size, size), Image.LANCZOS)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [render(size) for size in sizes]
    images[-1].save(ASSETS / "icon.png")
    images[-1].save(
        ASSETS / "icon.ico",
        format="ICO",
        sizes=[(size, size) for size in sizes],
    )
    print(f"Wrote {ASSETS / 'icon.ico'} and icon.png ({sizes})")


if __name__ == "__main__":
    main()
