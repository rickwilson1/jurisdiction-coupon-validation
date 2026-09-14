#!/usr/bin/env python3
"""Render SYSTEM_ARCHITECTURE_DIAGRAM.txt as a PNG with a monospace font.

Usage:
    python3 render_diagram_png.py [--dark] [input.txt] [output.png]

Flags:
    --dark    Render light text on a near-black background (default: dark text
              on white). Background tint is GitHub-style #0d1117.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
DEFAULT_IN = ROOT / "SYSTEM_ARCHITECTURE_DIAGRAM.txt"
DEFAULT_OUT = ROOT / "SYSTEM_ARCHITECTURE_DIAGRAM.png"

FONT_CANDIDATES = [
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/SFNSMono.ttf",
    "/System/Library/Fonts/Monaco.ttf",
    "/Library/Fonts/Menlo.ttc",
]
FONT_SIZE = 14
LINE_SPACING = 4
PADDING = 28
LIGHT_BG = (255, 255, 255)
LIGHT_FG = (24, 24, 24)
DARK_BG = (13, 17, 23)      # #0d1117 — GitHub-dark style
DARK_FG = (230, 237, 243)   # #e6edf3


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def main(in_path: Path, out_path: Path, dark: bool) -> None:
    text = in_path.read_text(encoding="utf-8")
    lines = text.splitlines() or [""]

    bg = DARK_BG if dark else LIGHT_BG
    fg = DARK_FG if dark else LIGHT_FG

    font = load_font(FONT_SIZE)

    probe = Image.new("RGB", (10, 10), bg)
    pd = ImageDraw.Draw(probe)
    max_w = 0
    for ln in lines:
        bbox = pd.textbbox((0, 0), ln, font=font)
        w = bbox[2] - bbox[0]
        if w > max_w:
            max_w = w
    bbox = pd.textbbox((0, 0), "Mg", font=font)
    line_h = (bbox[3] - bbox[1]) + LINE_SPACING

    img_w = max_w + PADDING * 2
    img_h = line_h * len(lines) + PADDING * 2

    img = Image.new("RGB", (img_w, img_h), bg)
    draw = ImageDraw.Draw(img)

    y = PADDING
    for ln in lines:
        draw.text((PADDING, y), ln, font=font, fill=fg)
        y += line_h

    img.save(out_path, "PNG", optimize=True)
    theme = "dark" if dark else "light"
    print(f"Wrote {out_path}  ({img_w}×{img_h}px, {theme} theme)")


if __name__ == "__main__":
    raw = sys.argv[1:]
    dark = "--dark" in raw
    positional = [a for a in raw if a != "--dark"]
    in_p = Path(positional[0]) if positional else DEFAULT_IN
    out_p = Path(positional[1]) if len(positional) > 1 else DEFAULT_OUT
    main(in_p, out_p, dark)
