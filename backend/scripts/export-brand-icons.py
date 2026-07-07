#!/usr/bin/env python3
"""Regenerate raster brand assets from logo-icon.svg (vector source of truth)."""
from __future__ import annotations

import io
import sys
from pathlib import Path

try:
    import cairosvg
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Install dev deps: ./venv/bin/pip install -r requirements-dev.txt"
    ) from exc

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "app" / "static" / "brand"
ICON_SRC = BRAND / "logo-icon.svg"
FAVICON_SRC = BRAND / "logo-favicon.svg"


def render_png(src: Path, size: int) -> Image.Image:
    png_bytes = cairosvg.svg2png(
        url=str(src),
        output_width=size,
        output_height=size,
    )
    return Image.open(io.BytesIO(png_bytes)).convert("RGBA")


def main() -> int:
    if not ICON_SRC.is_file() or not FAVICON_SRC.is_file():
        print(f"Missing source SVG in {BRAND}", file=sys.stderr)
        return 1

    sizes_icon = {
        "favicon-48.png": 48,
        "apple-touch-icon.png": 180,
        "icon-192.png": 192,
        "icon-512.png": 512,
    }
    sizes_favicon = {
        "favicon-16.png": 16,
        "favicon-32.png": 32,
    }

    rendered: dict[str, Image.Image] = {}
    for name, size in sizes_favicon.items():
        img = render_png(FAVICON_SRC, size)
        out = BRAND / name
        img.save(out, format="PNG", optimize=True)
        rendered[name] = img
        print(f"wrote {out} ({size}px, favicon variant)")

    for name, size in sizes_icon.items():
        img = render_png(ICON_SRC, size)
        out = BRAND / name
        img.save(out, format="PNG", optimize=True)
        rendered[name] = img
        print(f"wrote {out} ({size}px)")

    ico_path = BRAND / "favicon.ico"
    rendered["favicon-16.png"].save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)],
        append_images=[rendered["favicon-32.png"], rendered["favicon-48.png"]],
    )
    print(f"wrote {ico_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
