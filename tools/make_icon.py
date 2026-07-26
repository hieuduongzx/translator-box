"""Sinh icon thương hiệu (assets/icon.ico + icon.png).

Mark vuông lime với chữ 'T' gần đen, khớp `ui_utils._render_icon_pixmap`.
Không gradient, không shadow, không bo góc. Chạy lại bằng:

    python tools/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BRAND = (200, 255, 77)  # #c8ff4d
INK = (10, 10, 11)  # #0a0a0b
ASSETS = Path(__file__).resolve().parents[1] / "python-app" / "assets"
_FONT_CANDIDATES = (
    ASSETS / "IBMPlexMono-SemiBold.ttf",
    Path("C:/Windows/Fonts/consolab.ttf"),
    Path("C:/Windows/Fonts/segoeuib.ttf"),
)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), int(size * 0.54))
    return ImageFont.load_default()


def render(size: int) -> Image.Image:
    scale = 4  # vẽ lớn rồi thu nhỏ để cạnh mượt (supersampling)
    big = size * scale
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))

    margin = round(big * 0.07)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle(
        (margin, margin, big - margin, big - margin),
        fill=(*BRAND, 255),
    )

    font = _load_font(big)
    box = draw.textbbox((0, 0), "T", font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    draw.text(
        ((big - tw) / 2 - box[0], (big - th) / 2 - box[1]),
        "T",
        font=font,
        fill=(*INK, 255),
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
