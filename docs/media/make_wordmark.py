#!/usr/bin/env python3
"""Render the CLI half-block wordmark (src/cli/src/components/Header.tsx) to a PNG.

The banner uses only four glyphs — █ ▀ ▄ and space — so each character cell is
two stacked sub-cells we can draw as rectangles. No font involved: the PNG is
geometrically identical to the terminal banner at any resolution.

Usage: python3 docs/media/make_wordmark.py  → docs/media/wordmark.png
"""

from PIL import Image, ImageDraw

# Mirror of MARK in Header.tsx: ("read" part, "back" part) per text row.
MARK = [
    ("█▀█ █▀▀ ▄▀█ █▀▄ ", "█▄▄ ▄▀█ █▀▀ █▄▀"),
    ("█▀▄ ██▄ █▀█ █▄▀ ", "█▄█ █▀█ █▄▄ █ █"),
]

FG = "#f0f0f0"    # "read"
BLUE = "#4da3ff"  # "back"
BG = "#0d1117"    # GitHub dark-canvas card

CELL = 26          # sub-cell square, px (char cell = CELL wide × 2*CELL tall)
PAD_X, PAD_Y = 84, 64
RADIUS = 28
SCALE = 2          # supersample for clean rounded corners

# glyph → (top sub-cell filled, bottom sub-cell filled)
GLYPHS = {"█": (True, True), "▀": (True, False), "▄": (False, True), " ": (False, False)}

cols = max(len(r + b) for r, b in MARK)
w = cols * CELL + 2 * PAD_X
h = len(MARK) * 2 * CELL + 2 * PAD_Y

img = Image.new("RGBA", (w * SCALE, h * SCALE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
draw.rounded_rectangle([0, 0, w * SCALE - 1, h * SCALE - 1], RADIUS * SCALE, fill=BG)

for row, (read, back) in enumerate(MARK):
    for col, ch in enumerate(read + back):
        color = FG if col < len(read) else BLUE
        top, bottom = GLYPHS[ch]
        x = (PAD_X + col * CELL) * SCALE
        y = (PAD_Y + row * 2 * CELL) * SCALE
        if top:
            draw.rectangle([x, y, x + CELL * SCALE, y + CELL * SCALE], fill=color)
        if bottom:
            draw.rectangle([x, y + CELL * SCALE, x + CELL * SCALE, y + 2 * CELL * SCALE], fill=color)

img = img.resize((w, h), Image.LANCZOS)
img.save("docs/media/wordmark.png")
print(f"wrote docs/media/wordmark.png ({w}x{h})")
