"""Generate wordmark.svg, favicon.svg and favicon.ico for PartnerPortal.

Run from the repository root with an Inter Bold font file (OFL, from
https://github.com/rsms/inter):

    venv/bin/python tools/make_logo.py path/to/Inter-Bold.woff2 static

It rewrites static/wordmark.svg, static/favicon.svg and static/favicon.ico.
The lettering is outlined so the logo never depends on a font being loaded.
"""
import math
import sys

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw

FONT, OUT = sys.argv[1], sys.argv[2]
BLUE = "#2747A6"

# --- The mark -------------------------------------------------------------
# Two chain links on a horizontal axis, sharing their middle side, each open
# at one end (the open end stops 15 degrees short so the gap survives at
# 16px); the group is turned 45 degrees so the axis runs up-right.
W = 5.0          # stroke
R = 6.0          # link radius (link height 12)
LINKS = [
    "M11.796 -7.553A6 6 0 0 0 6 -12L-10 -12A6 6 0 0 0 -10 0L6 0",
    "M-11.796 7.553A6 6 0 0 0 -6 12L10 12A6 6 0 0 0 10 0L-6 0",
]


def rot(x, y):
    s = math.sqrt(0.5)
    return (x + y) * s, (y - x) * s


def samples():
    """Centerline points of both links, densely, in rotated coordinates."""
    def arc(cx, cy, a0, a1, n=60):
        return [(cx + R * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
                 cy + R * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
                for i in range(n + 1)]

    def line(p, q, n=80):
        return [(p[0] + (q[0] - p[0]) * i / n, p[1] + (q[1] - p[1]) * i / n)
                for i in range(n + 1)]

    a = (arc(6, -6, -15, -90) + line((6, -12), (-10, -12))
         + arc(-10, -6, 270, 90) + line((-10, 0), (6, 0)))
    b = [(-x, -y) for x, y in a]
    return [rot(x, y) for x, y in a + b]


PTS = samples()
MINX = min(p[0] for p in PTS) - W / 2
MAXX = max(p[0] for p in PTS) + W / 2
MINY = min(p[1] for p in PTS) - W / 2
MAXY = max(p[1] for p in PTS) + W / 2
MW, MH = MAXX - MINX, MAXY - MINY


def mark_svg(color, tx, ty, scale=1.0):
    paths = "".join(f'<path d="{d}"/>' for d in LINKS)
    return (f'<g transform="translate({tx:.2f} {ty:.2f}) scale({scale:.4f}) '
            f'translate({-MINX:.3f} {-MINY:.3f}) rotate(-45)" fill="none" '
            f'stroke="{color}" stroke-width="{W}" stroke-linecap="round" '
            f'stroke-linejoin="round">{paths}</g>')


# --- The lettering ----------------------------------------------------------
font = TTFont(FONT)
upm = font["head"].unitsPerEm
cap = font["OS/2"].sCapHeight
cmap = font.getBestCmap()
gs = font.getGlyphSet()
hmtx = font["hmtx"]

TEXT = "Partner Portal"
CAP_H = MH * 0.44                 # cap height relative to the mark
k = CAP_H / cap                   # font units -> svg units
TRACK = -0.012 * upm              # a touch tighter than default
GAP = MH * 0.32                   # mark to lettering

pen_x = 0.0
glyph_paths = []
baseline = (MH + CAP_H) / 2       # caps centered on the mark
x0 = MW + GAP
for ch in TEXT:
    name = cmap[ord(ch)]
    pen = SVGPathPen(gs)
    gs[name].draw(TransformPen(pen, (k, 0, 0, -k, x0 + pen_x * k, baseline)))
    d = pen.getCommands()
    if d:
        glyph_paths.append(d)
    pen_x += hmtx[name][0] + TRACK
text_w = (pen_x - TRACK) * k

TW = x0 + text_w
wordmark = (
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {TW:.1f} {MH:.1f}" '
    f'width="{TW:.0f}" height="{MH:.0f}" role="img" aria-label="Partner Portal">'
    + mark_svg("currentColor", 0, 0)
    + f'<path fill="currentColor" d="{" ".join(glyph_paths)}"/></svg>\n')
open(f"{OUT}/wordmark.svg", "w").write(wordmark)

# --- Favicon ----------------------------------------------------------------
# A white rounded tile with the mark in brand blue. The tile keeps the blue
# readable on a dark browser tab strip as well as a light one.
S = 512
PAD = 0.15 * S
sc = (S - 2 * PAD) / max(MW, MH)
fx = (S - MW * sc) / 2
fy = (S - MH * sc) / 2
favicon = (
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}">'
    f'<rect width="{S}" height="{S}" rx="{S * 0.22:.0f}" fill="#FFFFFF"/>'
    + mark_svg(BLUE, fx, fy, sc) + "</svg>\n")
open(f"{OUT}/favicon.svg", "w").write(favicon)

# The .ico, drawn directly: a disc stamped along the dense centerline is a
# round-capped stroke. Supersampled, then reduced to each icon size.
SS = 1024
img = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
dr = ImageDraw.Draw(img)
dr.rounded_rectangle((0, 0, SS - 1, SS - 1), radius=int(SS * 0.22), fill="#FFFFFF")
f = SS / S
rad = W / 2 * sc * f
for x, y in PTS:
    cx = (fx + (x - MINX) * sc) * f
    cy = (fy + (y - MINY) * sc) * f
    dr.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=BLUE)
img.save(f"{OUT}/favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
if len(sys.argv) > 3:  # optional preview PNG
    img.resize((256, 256), Image.LANCZOS).save(sys.argv[3], "PNG")
print(f"mark {MW:.1f}x{MH:.1f}  wordmark {TW:.1f}x{MH:.1f}")
