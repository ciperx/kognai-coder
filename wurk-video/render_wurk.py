#!/usr/bin/env python3
"""WURK — "Work, in motion."  A 30 s 1920x1080 product film generated from code.

Everything on screen is drawn with PIL primitives at 2x supersampling and piped
as rawvideo into ffmpeg.  No stock footage, no video model, no timeline editor.

usage:
  python3 render_wurk.py --frames 900 --fps 30 --out - | ffmpeg -f rawvideo \
      -pix_fmt rgb24 -s 1920x1080 -r 30 -i - -c:v libx264 -pix_fmt yuv420p out.mp4
  python3 render_wurk.py --still 4.2 --out still.png
"""
import argparse
import math
import os
import sys

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

W, H = 1920, 1080
S = 2                      # supersampling factor
FPS = 30
DUR = 30.0

# ---------------------------------------------------------------- palette ----
BG1 = (6, 9, 16)
BG2 = (15, 23, 40)
PANEL = (17, 24, 39)
PANEL2 = (24, 33, 51)
PANEL3 = (30, 41, 62)
LINE = (40, 54, 78)
TEXT = (234, 240, 250)
TEXT2 = (176, 189, 208)
MUT = (126, 141, 166)
MINT = (94, 234, 212)
MINT_D = (16, 78, 72)
AMBER = (245, 184, 65)
USDC = (58, 132, 214)
RED = (232, 106, 106)

FONTS = {
    "inter": ("Inter[opsz,wght].ttf", 2),
    "grot": ("SpaceGrotesk[wght].ttf", 1),
    "mono": ("JetBrainsMono[wght].ttf", 1),
}
_font_cache = {}


def font(name, size, weight=400):
    key = (name, round(size, 1), weight)
    if key in _font_cache:
        return _font_cache[key]
    fn, naxes = FONTS[name]
    f = ImageFont.truetype(os.path.join(HERE, fn), max(4, int(round(size * S))))
    try:
        f.set_variation_by_axes([14, weight] if naxes == 2 else [weight])
    except Exception:
        pass
    _font_cache[key] = f
    return f


# ----------------------------------------------------------------- easing ----
def clamp(u, a=0.0, b=1.0):
    return a if u < a else (b if u > b else u)


def eo(u):          # ease-out cubic
    u = clamp(u)
    return 1 - (1 - u) ** 3


def eio(u):         # smoothstep
    u = clamp(u)
    return u * u * (3 - 2 * u)


def back(u, k=1.7):  # slight overshoot
    u = clamp(u)
    return 1 + (k + 1) * (u - 1) ** 3 + k * (u - 1) ** 2


def seg(t, a, b):
    """0..1 progress of t through [a,b]."""
    return clamp((t - a) / max(1e-6, b - a))


def mix(c1, c2, u):
    u = clamp(u)
    return tuple(int(c1[i] + (c2[i] - c1[i]) * u) for i in range(3))


# ------------------------------------------------------------------ canvas ---
class Layer:
    """A transparent tile drawn in logical pixels, scaled by S internally."""

    def __init__(self, w, h):
        self.w, self.h = int(w), int(h)
        self.img = Image.new("RGBA", (self.w * S, self.h * S), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    def rr(self, box, r=12, fill=None, outline=None, width=1.0):
        x, y, x2, y2 = [v * S for v in box]
        self.d.rounded_rectangle([x, y, x2, y2], radius=r * S, fill=fill,
                                 outline=outline, width=max(1, int(round(width * S))))

    def rect(self, box, fill=None):
        self.d.rectangle([v * S for v in box], fill=fill)

    def line(self, pts, fill, width=1.0):
        self.d.line([(x * S, y * S) for x, y in pts], fill=fill,
                    width=max(1, int(round(width * S))), joint="curve")

    def ellipse(self, cx, cy, r, fill=None, outline=None, width=1.0, rx=None, ry=None):
        rx = r if rx is None else rx
        ry = r if ry is None else ry
        self.d.ellipse([(cx - rx) * S, (cy - ry) * S, (cx + rx) * S, (cy + ry) * S],
                       fill=fill, outline=outline, width=max(1, int(round(width * S))))

    def arc(self, cx, cy, r, a0, a1, fill, width=1.0):
        self.d.arc([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S],
                   a0, a1, fill=fill, width=max(1, int(round(width * S))))

    def poly(self, pts, fill=None, outline=None):
        self.d.polygon([(x * S, y * S) for x, y in pts], fill=fill, outline=outline)

    def text(self, x, y, s, f, fill, track=0.0, anchor="lt"):
        """Draw text with optional letter tracking; anchor 'lt'/'rt'/'mt'."""
        if not s:
            return 0.0
        widths = [f.getlength(ch) / S for ch in s]
        total = sum(widths) + track * (len(s) - 1)
        if anchor == "rt":
            x -= total
        elif anchor == "mt":
            x -= total / 2
        cx = x
        for ch, cw in zip(s, widths):
            self.d.text((cx * S, y * S), ch, font=f, fill=fill, anchor="lt")
            cx += cw + track
        return total

    def tw(self, s, f, track=0.0):
        if not s:
            return 0.0
        return sum(f.getlength(ch) / S for ch in s) + track * (len(s) - 1)


def stamp(base, tile, x, y, alpha=1.0):
    if alpha <= 0.004:
        return
    im = tile.img if isinstance(tile, Layer) else tile
    dst = base.img if isinstance(base, Layer) else base
    a = im.getchannel("A")
    if alpha < 0.996:
        a = a.point(lambda v: int(v * alpha))
    dst.paste(im, (int(round(x * S)), int(round(y * S))), a)


# ------------------------------------------------------------- background ----
def _radial(w, h, cx, cy, rx, ry):
    xs = (np.arange(w, dtype=np.float32) - cx) / max(rx, 1)
    ys = (np.arange(h, dtype=np.float32) - cy) / max(ry, 1)
    d = np.sqrt(xs[None, :] ** 2 + ys[:, None] ** 2)
    return np.clip(1.0 - d, 0.0, 1.0) ** 2


def make_bg():
    """Gradient + soft light pools + dot grid + vignette, built once."""
    w, h = W * S, H * S
    rows = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None, None]
    grad = (np.array(BG1, np.float32) * (1 - rows) + np.array(BG2, np.float32) * rows)
    img = np.repeat(grad, w, axis=1).astype(np.uint8)

    # light pools computed small and upscaled (smooth by nature)
    sw, sh = 480, 270
    glows = np.zeros((sh, sw, 3), np.float32)
    for (cx, cy, rx, ry, col, amp) in (
        (0.30, 0.34, 0.42, 0.50, MINT, 0.16),
        (0.78, 0.22, 0.36, 0.42, USDC, 0.13),
        (0.60, 0.92, 0.55, 0.40, AMBER, 0.05),
    ):
        m = _radial(sw, sh, cx * sw, cy * sh, rx * sw, ry * sh)[:, :, None]
        glows += m * np.array(col, np.float32) * amp
    gl_img = Image.fromarray(np.clip(glows, 0, 255).astype(np.uint8), "RGB")
    gl_img = gl_img.resize((w, h), Image.BICUBIC)
    base = ImageChops.add(Image.fromarray(img, "RGB"), gl_img)

    # dot grid
    grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    step = 48 * S
    rad = 1.15 * S
    for gx in range(0, w, step):
        for gy in range(0, h, step):
            gd.ellipse([gx - rad, gy - rad, gx + rad, gy + rad], fill=(120, 150, 190, 20))
    base = Image.alpha_composite(base.convert("RGBA"), grid).convert("RGB")

    # vignette
    sw2, sh2 = 320, 180
    m = _radial(sw2, sh2, sw2 / 2, sh2 / 2, sw2 * 0.72, sh2 * 0.78)
    dark = Image.fromarray((np.clip(1.0 - 0.55 * (1 - m), 0, 1) * 255).astype(np.uint8), "L")
    dark = dark.resize((w, h), Image.BICUBIC)
    base = Image.composite(base, Image.new("RGB", (w, h), (0, 0, 0)), dark)
    return base


BG = None


# ------------------------------------------------------------------- logo ----
_LOGO_MARK = None


def logo_mark():
    """Extract the WURK logomark (black on white jpg) as an alpha mask."""
    global _LOGO_MARK
    if _LOGO_MARK is not None:
        return _LOGO_MARK
    src = Image.open(os.path.join(HERE, "wurk_logo.jpg")).convert("L")
    mask = src.point(lambda v: 255 if v < 110 else 0)
    bbox = mask.getbbox()
    mask = mask.crop(bbox)
    # feather slightly so downscaled edges stay clean
    mask = mask.filter(ImageFilter.GaussianBlur(0.6))
    _LOGO_MARK = mask
    return mask


def logo_tile(size, pad=0.30, fg=(8, 11, 18), bg=(255, 255, 255), radius=None):
    """White rounded badge with the real WURK mark composited in."""
    t = Layer(size, size)
    r = size * 0.26 if radius is None else radius
    t.rr([0, 0, size, size], r=r, fill=bg + (255,))
    m = logo_mark()
    inner = size * (1 - 2 * pad)
    iw = inner
    ih = inner * m.height / m.width
    if ih > inner:
        ih = inner
        iw = inner * m.width / m.height
    m2 = m.resize((max(2, int(iw * S)), max(2, int(ih * S))), Image.LANCZOS)
    solid = Image.new("RGBA", m2.size, fg + (255,))
    px = int((size - iw) / 2 * S)
    py = int((size - ih) / 2 * S)
    t.img.paste(solid, (px, py), m2)
    return t


def wordmark(layer, x, y, size, color=TEXT, weight=700, track=None):
    f = font("grot", size, weight)
    tr = size * 0.06 if track is None else track
    return layer.text(x, y, "WURK", f, color + (255,), track=tr)


# ------------------------------------------------------------ small pieces ---
def pill(layer, x, y, label, f, fg, bg, padx=14, h=34, r=None, border=None):
    tw = layer.tw(label, f)
    r = h / 2 if r is None else r
    layer.rr([x, y, x + tw + padx * 2, y + h], r=r, fill=bg, outline=border, width=1.2)
    fgc = fg if len(fg) == 4 else fg + (255,)
    layer.text(x + padx, y + (h - f.size / S * 0.72) / 2 - 3, label, f, fgc)
    return tw + padx * 2


def check_glyph(layer, cx, cy, r, color, w=2.0):
    layer.line([(cx - r * 0.55, cy + r * 0.05), (cx - r * 0.1, cy + r * 0.5),
                (cx + r * 0.6, cy - r * 0.45)], color + (255,), width=w)


def icon(kind, layer, cx, cy, sz, color):
    c = color + (255,)
    if kind == "play":
        layer.poly([(cx - sz * 0.28, cy - sz * 0.42), (cx + sz * 0.44, cy),
                    (cx - sz * 0.28, cy + sz * 0.42)], fill=c)
    elif kind == "bars":
        for i, hh in enumerate((0.34, 0.62, 0.92)):
            layer.rr([cx - sz * 0.42 + i * sz * 0.32, cy + sz * 0.45 - sz * hh,
                      cx - sz * 0.28 + i * sz * 0.32, cy + sz * 0.45], r=sz * 0.06, fill=c)
    elif kind == "code":
        layer.line([(cx - sz * 0.12, cy - sz * 0.4), (cx - sz * 0.46, cy),
                    (cx - sz * 0.12, cy + sz * 0.4)], c, width=sz * 0.11)
        layer.line([(cx + sz * 0.12, cy - sz * 0.4), (cx + sz * 0.46, cy),
                    (cx + sz * 0.12, cy + sz * 0.4)], c, width=sz * 0.11)
    elif kind == "cube":
        layer.poly([(cx, cy - sz * 0.46), (cx + sz * 0.44, cy - sz * 0.2),
                    (cx, cy + sz * 0.06), (cx - sz * 0.44, cy - sz * 0.2)], outline=c)
        layer.line([(cx - sz * 0.44, cy - sz * 0.2), (cx - sz * 0.44, cy + sz * 0.24),
                    (cx, cy + sz * 0.5), (cx + sz * 0.44, cy + sz * 0.24),
                    (cx + sz * 0.44, cy - sz * 0.2)], c, width=sz * 0.075)
        layer.line([(cx, cy + sz * 0.06), (cx, cy + sz * 0.5)], c, width=sz * 0.075)
    elif kind == "shield":
        layer.poly([(cx, cy - sz * 0.46), (cx + sz * 0.4, cy - sz * 0.28),
                    (cx + sz * 0.34, cy + sz * 0.2), (cx, cy + sz * 0.48),
                    (cx - sz * 0.34, cy + sz * 0.2), (cx - sz * 0.4, cy - sz * 0.28)], outline=c)
    elif kind == "spark":
        layer.line([(cx, cy - sz * 0.5), (cx, cy + sz * 0.5)], c, width=sz * 0.09)
        layer.line([(cx - sz * 0.5, cy), (cx + sz * 0.5, cy)], c, width=sz * 0.09)
        layer.line([(cx - sz * 0.3, cy - sz * 0.3), (cx + sz * 0.3, cy + sz * 0.3)], c, width=sz * 0.07)
        layer.line([(cx + sz * 0.3, cy - sz * 0.3), (cx - sz * 0.3, cy + sz * 0.3)], c, width=sz * 0.07)
    elif kind == "coin":
        layer.ellipse(cx, cy, sz * 0.44, outline=c, width=sz * 0.09)
        layer.ellipse(cx, cy, sz * 0.1, fill=c)


# ---------------------------------------------------------- shared chrome ----
STEPS = [("01", "POST"), ("02", "CLAIM"), ("03", "DELIVER"), ("04", "PAYOUT"),
         ("05", "STORE"), ("06", "START")]


def chrome(t, idx):
    """Persistent header (logo badge + wordmark) and footer progress rail."""
    L = Layer(W, H)
    stamp(L, logo_tile(40, pad=0.30), 88, 56)
    wordmark(L, 142, 60, 26, TEXT, 700, track=2.6)
    f = font("mono", 15, 500)
    if 0 <= idx < len(STEPS):
        num, lab = STEPS[idx]
        L.text(1834, 70, lab, f, MUT + (255,), track=2.2, anchor="rt")
        wlab = L.tw(lab, f, 2.2)
        L.text(1834 - wlab - 14, 70, num, f, MINT + (255,), track=1.6, anchor="rt")

    # footer rail
    y = 1006
    L.rr([88, y, 1832, y + 2], r=1, fill=(30, 40, 58, 255))
    p = clamp(t / DUR)
    if p > 0.002:
        L.rr([88, y, 88 + 1744 * p, y + 2], r=1, fill=MINT + (150,))
        L.ellipse(88 + 1744 * p, y + 1, 3.2, fill=MINT + (255,))
    fm = font("mono", 13, 450)
    L.text(88, 1024, "WURK / WORK IN MOTION", fm, (86, 100, 122, 255), track=1.8)
    L.text(1832, 1024, "wurk.fun", fm, (108, 124, 148, 255), track=0.0, anchor="rt")
    return L


def stage(idx, lt, total_local):
    """Left-hand copy block: step tag, headline, supporting lines."""
    L = Layer(760, 420)
    f_step = font("mono", 15, 600)
    f_head = font("grot", 88, 700)
    f_sub = font("inter", 26, 450)

    a = eo(seg(lt, 0.12, 0.55))
    L.text(0, 8, f"{STEPS[idx][0]} / {STEPS[idx][1]}", f_step, MINT + (255,), track=3.0)
    L.rr([0, 40, 56 * a, 42], r=1, fill=MINT + (200,))
    return L, f_head, f_sub, a


# ----------------------------------------------------------------- scenes ----
def sc_logo(lt, dur):
    base = BG.copy()
    u = lt / dur

    rings = Layer(W, H)
    for k in range(3):
        p = clamp((lt - 0.05 * k) / 1.9)
        if 0 < p < 1:
            r = 170 + p * (300 + k * 90)
            rings.ellipse(960, 470, r, outline=(94, 234, 212, int(46 * (1 - p))), width=1.4)
    stamp(base, rings, 0, 0)

    # logo badge: already on screen at t=0, settles into place
    g = back(seg(lt, 0.0, 0.7), 1.4)
    sz = 168 * (1.10 - 0.10 * g)
    alpha = 0.55 + 0.45 * eo(seg(lt, 0.0, 0.35))
    tile = logo_tile(sz, pad=0.30)
    stamp(base, tile, 960 - sz / 2, 470 - sz / 2, alpha)

    # wordmark letters rise
    fw = font("grot", 84, 700)
    letters = "WURK"
    tr = 84 * 0.10
    widths = [fw.getlength(c) / S for c in letters]
    total = sum(widths) + tr * (len(letters) - 1)
    x = 960 - total / 2
    for i, (ch, cw) in enumerate(zip(letters, widths)):
        p = eo(seg(lt, 0.55 + i * 0.09, 1.0 + i * 0.09))
        if p > 0:
            L = Layer(cw + 6, 110)
            L.text(0, 0, ch, fw, TEXT + (255,))
            stamp(base, L, x - 3, 600 + (1 - p) * 26, p)
        x += cw + tr

    # taglines
    f1 = font("inter", 30, 450)
    f2 = font("mono", 16, 450)
    p1 = eo(seg(lt, 1.15, 1.85))
    if p1 > 0:
        L = Layer(900, 44)
        s = "The work network for agents and humans."
        L.text(450, 0, s, f1, TEXT2 + (255,), anchor="mt")
        stamp(base, L, 510, 730 + (1 - p1) * 14, p1)
    p2 = eo(seg(lt, 1.5, 2.2))
    if p2 > 0:
        L = Layer(900, 40)
        L.text(450, 0, "POST WORK  ·  DO WORK  ·  GET PAID", f2, MINT + (255,), track=2.4, anchor="mt")
        stamp(base, L, 510, 782 + (1 - p2) * 12, p2)

    stamp(base, chrome(lt, 0), 0, 0)
    return base


def window_shell(base, lt, label, x=880, y=238, x2=1832, y2=838, alpha=1.0, rise=0.0,
                 dy=0.0, dots=True):
    """The recurring app window used for every UI beat."""
    w, h = x2 - x, y2 - y
    L = Layer(w, h)
    # shadow
    for i, a in ((30, 26), (16, 18), (6, 10)):
        L.rr([-i, -i + 10, w + i, h + i + 10], r=26 + i, fill=(0, 0, 0, a))
    L.rr([0, 0, w, h], r=24, fill=PANEL + (255,), outline=LINE + (255,), width=1.3)
    # top bar
    if dots:
        for i, c in enumerate(((232, 106, 106), (245, 184, 65), (94, 234, 212))):
            L.ellipse(26 + i * 18, 26, 5, fill=c + (110,))
        L.text(92, 18, label, font("mono", 14, 450), (110, 126, 152, 255), track=0.8)
    L.rr([0, 52, w, 53], r=0, fill=(30, 41, 60, 255))
    stamp(base, L, x, y + dy, alpha)
    return (x, y + dy, x2, y2 + dy)


def row_sep(base, box, yy, alpha=1.0):
    L = Layer(box[2] - box[0], 2)
    L.rr([26, 0, box[2] - box[0] - 26, 1.5], r=1, fill=(32, 43, 62, 255))
    stamp(base, L, box[0], yy, alpha)


def sc_post(lt, dur):
    base = BG.copy()

    # ---- copy
    f_step = font("mono", 15, 600)
    f_head = font("grot", 92, 700)
    f_sub = font("inter", 27, 450)
    a = eo(seg(lt, 0.02, 0.4))
    L = Layer(720, 300)
    L.text(96, 300, "01 / POST", f_step, MINT + (255,), track=3.2)
    stamp(base, L, 0, 0)
    L = Layer(720, 260)
    L.text(96, 0, "Post", f_head, TEXT + (255,))
    L.text(96, 104, "a job.", f_head, TEXT + (255,))
    stamp(base, L, 0, 340 + (1 - a) * 18, a)
    p = eo(seg(lt, 0.25, 0.75))
    L = Layer(620, 120)
    L.text(96, 0, "Describe the work. Set a budget.", f_sub, TEXT2 + (255,))
    L.text(96, 42, "Fund escrow in USDC.", f_sub, TEXT2 + (255,))
    stamp(base, L, 0, 570 + (1 - p) * 14, p)
    p2 = eo(seg(lt, 0.5, 1.0))
    L = Layer(520, 40)
    L.text(96, 0, "→ open to humans and agents", font("mono", 16, 450), (120, 150, 160, 255), track=0.6)
    stamp(base, L, 0, 660 + (1 - p2) * 10, p2)

    # ---- window
    wb = eo(seg(lt, 0.0, 0.30))
    box = window_shell(base, lt, "wurk.fun/jobs/new", dy=(1 - wb) * 34, alpha=wb)
    x, y, x2, y2 = box
    w = x2 - x

    def line_at(i, yoff, alpha, dx=0.0):
        return alpha, dx

    # eyebrow
    p = eo(seg(lt, 0.14, 0.46))
    L = Layer(w, 40)
    L.text(40, 0, "NEW JOB", font("mono", 14, 600), MINT + (255,), track=3.4)
    stamp(base, L, x, y + 78, p)

    # title
    p = eo(seg(lt, 0.20, 0.62))
    L = Layer(w, 60)
    L.text(40, 0, "Render a 30s product video", font("grot", 40, 600), TEXT + (255,))
    stamp(base, L, x, y + 108 + (1 - p) * 12, p)

    # description
    p = eo(seg(lt, 0.30, 0.72))
    L = Layer(w, 70)
    L.text(40, 0, "Landscape, 1080p MP4. Explain what WURK", font("inter", 21, 400), (150, 164, 186, 255))
    L.text(40, 30, "does in under 45 seconds.", font("inter", 21, 400), (150, 164, 186, 255))
    stamp(base, L, x, y + 172 + (1 - p) * 10, p)

    # stats
    stats = [("BUDGET", "250 USDC", AMBER), ("DEADLINE", "7 days", TEXT), ("ESCROW", "funded", MINT)]
    for i, (k, v, col) in enumerate(stats):
        p = eo(seg(lt, 0.46 + i * 0.07, 0.82 + i * 0.07))
        L = Layer(260, 70)
        L.text(40, 0, k, font("mono", 13, 500), (104, 120, 146, 255), track=2.6)
        L.text(40, 24, v, font("inter", 28, 600), col + (255,))
        stamp(base, L, x + i * (w - 80) / 3, y + 262 + (1 - p) * 12, p)
    row_sep(base, box, y + 348, eo(seg(lt, 0.6, 0.85)))

    # tags
    p = eo(seg(lt, 0.72, 1.02))
    L = Layer(w, 40)
    tx = 40
    for t_ in ("video", "motion design", "1080p", "reusable source"):
        tw = pill(L, tx, 0, t_, font("mono", 13, 500), (160, 176, 198, 255),
                  (26, 36, 56, 255), padx=12, h=30, border=(38, 51, 72, 255))
        tx += tw + 10
    stamp(base, L, x, y + 384 + (1 - p) * 8, p)

    # CTA button
    p = eo(seg(lt, 0.92, 1.24))
    L = Layer(w, 90)
    btn_w = 190
    L.rr([40, 0, 40 + btn_w, 56], r=14, fill=MINT + (255,))
    L.text(40 + 26, 17, "Post job", font("inter", 21, 700), (8, 20, 24, 255))
    ax = 40 + btn_w - 40
    L.line([(ax, 22), (ax + 16, 28), (ax, 34)], (8, 20, 24, 255), width=2.2)
    L.text(40 + btn_w + 20, 18, "escrow locked until delivery", font("mono", 13, 450),
           (108, 124, 150, 255))
    stamp(base, L, x, y + 470 + (1 - p) * 12, p)

    stamp(base, chrome(lt, 0), 0, 0)
    return base


AGENTS = [("Syntax", "rendering · video", (94, 234, 212)),
          ("Nightjar", "motion · 3d", (140, 170, 250)),
          ("Kernel", "code · data", (245, 184, 65))]


def sc_claim(lt, dur):
    base = BG.copy()

    f_step = font("mono", 15, 600)
    f_head = font("grot", 92, 700)
    f_sub = font("inter", 27, 450)
    a = eo(seg(lt, 0.02, 0.4))
    L = Layer(720, 40)
    L.text(96, 300, "02 / CLAIM", f_step, MINT + (255,), track=3.2)
    stamp(base, L, 0, 0)
    L = Layer(760, 260)
    L.text(96, 0, "Agents", f_head, TEXT + (255,))
    L.text(96, 104, "claim it.", f_head, MINT + (255,))
    stamp(base, L, 0, 340 + (1 - a) * 18, a)

    p = eo(seg(lt, 0.3, 0.8))
    L = Layer(640, 120)
    L.text(96, 0, "Agents browse open work, claim it,", f_sub, TEXT2 + (255,))
    L.text(96, 42, "and start in seconds.", f_sub, TEXT2 + (255,))
    stamp(base, L, 0, 570 + (1 - p) * 14, p)
    p2 = eo(seg(lt, 0.55, 1.05))
    L = Layer(560, 44)
    L.text(96, 0, "no interviews · no waiting room", font("mono", 16, 450),
           (120, 150, 160, 255), track=0.6)
    stamp(base, L, 0, 660 + (1 - p2) * 10, p2)

    wb = eo(seg(lt, 0.0, 0.30))
    box = window_shell(base, lt, "wurk.fun/jobs/open", dy=(1 - wb) * 34, alpha=wb)
    x, y, x2, y2 = box
    w = x2 - x

    p = eo(seg(lt, 0.14, 0.46))
    L = Layer(w, 40)
    L.text(40, 0, "OPEN WORK · 3 AGENTS ONLINE", font("mono", 14, 600), MINT + (255,), track=2.8)
    stamp(base, L, x, y + 78, p)

    # agent rows
    claimed_at = 1.15
    rows_y = y + 122
    for i, (name, spec, col) in enumerate(AGENTS):
        p = eo(seg(lt, 0.30 + i * 0.10, 0.68 + i * 0.10))
        is_claimed = (i == 0)
        L = Layer(w - 80, 78)
        hl = 0.0
        if is_claimed:
            hl = eio(seg(lt, claimed_at, claimed_at + 0.35))
        if hl > 0:
            L.rr([0, 0, w - 80, 72], r=16, fill=(20, 42, 42, 255),
                 outline=mix(LINE, MINT, hl) + (255,), width=1.2 + 0.6 * hl)
        L.ellipse(38, 36, 19, fill=(26, 36, 56, 255))
        L.text(38, 18, name[0], font("grot", 22, 700), col + (255,), anchor="mt")
        L.text(72, 14, name, font("inter", 23, 600), TEXT + (255,))
        L.text(72, 44, spec, font("mono", 12, 450), (120, 136, 160, 255), track=0.8)
        if is_claimed and hl > 0.05:
            # claim pill morphs from ghost button to mint "claimed"
            L.rr([w - 80 - 168, 18, w - 80 - 24, 54], r=10,
                 fill=mix((24, 34, 52), (94, 234, 212), hl) + (255,))
            txt = "CLAIMED" if hl > 0.6 else "CLAIM"
            fg = mix((170, 185, 205), (8, 22, 24), hl)
            cw = L.tw(txt, font("mono", 13, 700), 1.6)
            L.text(w - 80 - 96 - cw / 2 - (8 if hl > 0.6 else 0), 27, txt,
                   font("mono", 13, 700), fg + (255,), track=1.6)
            if hl > 0.6:
                check_glyph(L, w - 80 - 132, 36, 13, (8, 22, 24), 2.4)
        else:
            L.rr([w - 80 - 118, 18, w - 80 - 24, 54], r=10, fill=(24, 34, 52, 255),
                 outline=(44, 58, 80, 255), width=1.1)
            L.text(w - 80 - 71, 27, "CLAIM", font("mono", 13, 600), (150, 165, 188, 255),
                   track=1.6, anchor="mt")
        stamp(base, L, x + 40, rows_y + i * 88 + (1 - p) * 14, p)

    row_sep(base, box, rows_y + 268, 1.0)

    # claim toast
    toast_t = claimed_at + 0.25
    p = eo(seg(lt, toast_t, toast_t + 0.4))
    if p > 0:
        L = Layer(w - 80, 62)
        L.rr([40, 0, w - 120, 52], r=12, fill=(18, 30, 34, 255), outline=(38, 76, 72, 255), width=1.0)
        L.ellipse(66, 26, 8, fill=MINT + (255,))
        L.ellipse(66, 26, 3.4, fill=(8, 22, 24, 255))
        L.text(84, 16, "Syntax claimed this job", font("inter", 19, 500), TEXT + (255,))
        L.text(w - 150, 18, "0.8s", font("mono", 15, 600), MINT + (255,), anchor="rt")
        stamp(base, L, x, rows_y + 290 + (1 - p) * 10, p)

    # activity sparkline strip
    p = eo(seg(lt, 2.0, 2.5))
    if p > 0:
        L = Layer(w - 80, 60)
        for i in range(24):
            hh = 6 + 20 * abs(math.sin(i * 0.7 + lt * 2.0))
            L.rr([40 + i * 22, 46 - hh * p, 40 + i * 22 + 9, 46], r=3,
                 fill=(46, 74, 82, 255))
        L.text(w - 150, 20, "queue live", font("mono", 12, 450), (100, 122, 146, 255),
               track=1.4, anchor="rt")
        stamp(base, L, x, y + 516, p)

    stamp(base, chrome(lt, 1), 0, 0)
    return base


def sc_deliver(lt, dur):
    base = BG.copy()

    f_step = font("mono", 15, 600)
    f_head = font("grot", 92, 700)
    f_sub = font("inter", 27, 450)
    a = eo(seg(lt, 0.02, 0.4))
    L = Layer(760, 40)
    L.text(96, 300, "03 / DELIVER", f_step, MINT + (255,), track=3.2)
    stamp(base, L, 0, 0)
    L = Layer(820, 260)
    L.text(96, 0, "Work gets", f_head, TEXT + (255,))
    L.text(96, 104, "done.", f_head, TEXT + (255,))
    stamp(base, L, 0, 340 + (1 - a) * 18, a)
    p = eo(seg(lt, 0.3, 0.8))
    L = Layer(650, 120)
    L.text(96, 0, "Deliverables land in the job thread,", f_sub, TEXT2 + (255,))
    L.text(96, 42, "ready to review and accept.", f_sub, TEXT2 + (255,))
    stamp(base, L, 0, 570 + (1 - p) * 14, p)

    wb = eo(seg(lt, 0.0, 0.30))
    box = window_shell(base, lt, "wurk.fun/jobs/64ac…/thread", dy=(1 - wb) * 34, alpha=wb)
    x, y, x2, y2 = box
    w = x2 - x

    p = eo(seg(lt, 0.14, 0.46))
    L = Layer(w, 40)
    L.text(40, 0, "DELIVERABLE · v1", font("mono", 14, 600), MINT + (255,), track=2.8)
    stamp(base, L, x, y + 78, p)

    # preview plate (16:9)
    pv_w, pv_h = 470, 264
    p = eo(seg(lt, 0.22, 0.62))
    L = Layer(pv_w, pv_h)
    L.rr([0, 0, pv_w, pv_h], r=14, fill=(9, 13, 22, 255), outline=(38, 51, 72, 255), width=1.1)
    # miniature of the film's own end card
    L.rr([18, 18, pv_w - 18, pv_h - 18], r=8, fill=(11, 17, 28, 255))
    lt2 = logo_tile(46, pad=0.30)
    stamp(L, lt2, pv_w / 2 - 23, pv_h / 2 - 46)
    L.text(pv_w / 2, pv_h / 2 + 12, "wurk.fun", font("grot", 15, 600),
           (200, 214, 232, 255), anchor="mt")
    L.ellipse(pv_w / 2, pv_h / 2 + 78, 15, fill=(255, 255, 255, 26))
    icon("play", L, pv_w / 2 + 1, pv_h / 2 + 78, 15, (235, 242, 250))
    stamp(base, L, x + 40, y + 118 + (1 - p) * 16, p)

    # progress bar under preview
    pp = eo(seg(lt, 0.6, 2.0))
    L = Layer(pv_w, 18)
    L.rr([0, 6, pv_w, 9], r=2, fill=(28, 38, 56, 255))
    if pp > 0.01:
        L.rr([0, 6, 4 + (pv_w - 8) * pp, 9], r=2, fill=MINT + (255,))
        L.ellipse(4 + (pv_w - 8) * pp, 7.5, 4, fill=MINT + (255,))
    stamp(base, L, x + 40, y + 392)
    L = Layer(pv_w, 26)
    L.text(0, 0, "wurk-product.mp4", font("mono", 12, 500), (128, 146, 172, 255), track=0.6)
    L.text(pv_w, 0, f"{int(min(1.0, pp) * 100):d}%", font("mono", 12, 600), MINT + (255,), anchor="rt")
    stamp(base, L, x + 40, y + 416)

    # metadata column
    meta = [("RESOLUTION", "1920 × 1080"), ("DURATION", "30.0 s"), ("CODEC", "H.264 · 30 fps"),
            ("SIZE", "8.4 MB")]
    for i, (k, v) in enumerate(meta):
        p = eo(seg(lt, 0.42 + i * 0.07, 0.78 + i * 0.07))
        L = Layer(250, 56)
        L.text(0, 0, k, font("mono", 11, 500), (100, 116, 142, 255), track=2.2)
        L.text(0, 20, v, font("inter", 19, 500), TEXT + (255,))
        stamp(base, L, x + 552 + (1 - p) * 10, y + 122 + i * 64, p)

    # delivered stamp
    st = 1.95
    p = seg(lt, st, st + 0.45)
    if p > 0:
        sc = 0.9 + 0.10 * back(p, 2.6)
        L = Layer(240, 54)
        L.rr([0, 0, 240, 52], r=26, fill=(18, 44, 42, 255), outline=(94, 234, 212, 255), width=1.4)
        check_glyph(L, 34, 26, 15, MINT, 2.6)
        L.text(58, 17, "DELIVERED", font("mono", 14, 700), MINT + (255,), track=2.4)
        stamp(base, L, x + 552, y + 396 - (sc - 1) * 20, clamp(p * 1.2))

    # review row
    p = eo(seg(lt, 2.2, 2.55))
    if p > 0:
        row_sep(base, box, y + 470, 1.0)
        L = Layer(w - 80, 60)
        L.text(40, 8, "Awaiting creator review", font("inter", 18, 450), (148, 162, 186, 255))
        L.rr([w - 80 - 150, 4, w - 80 - 40, 40], r=9, fill=(94, 234, 212, 255))
        L.text(w - 80 - 95, 14, "Accept", font("inter", 15, 700), (8, 22, 24, 255), anchor="mt")
        stamp(base, L, x, y + 490 + (1 - p) * 8, p)

    stamp(base, chrome(lt, 2), 0, 0)
    return base


def sc_pay(lt, dur):
    base = BG.copy()

    f_step = font("mono", 15, 600)
    f_head = font("grot", 92, 700)
    f_sub = font("inter", 27, 450)
    a = eo(seg(lt, 0.02, 0.4))
    L = Layer(640, 40)
    L.text(96, 300, "04 / PAYOUT", f_step, MINT + (255,), track=3.2)
    stamp(base, L, 0, 0)
    L = Layer(700, 260)
    L.text(96, 0, "Get", f_head, TEXT + (255,))
    L.text(96, 104, "paid.", f_head, AMBER + (255,))
    stamp(base, L, 0, 340 + (1 - a) * 18, a)
    p = eo(seg(lt, 0.3, 0.8))
    L = Layer(660, 120)
    L.text(96, 0, "Escrow releases the moment work", f_sub, TEXT2 + (255,))
    L.text(96, 42, "is accepted. Settled in USDC.", f_sub, TEXT2 + (255,))
    stamp(base, L, 0, 570 + (1 - p) * 14, p)

    wb = eo(seg(lt, 0.0, 0.30))
    box = window_shell(base, lt, "wurk.fun/wallet", dy=(1 - wb) * 34, alpha=wb)
    x, y, x2, y2 = box
    w = x2 - x

    p = eo(seg(lt, 0.14, 0.46))
    L = Layer(w, 40)
    L.text(40, 0, "ESCROW · RELEASED", font("mono", 14, 600), AMBER + (255,), track=2.8)
    stamp(base, L, x, y + 78, p)

    # counting amount
    cp = eio(seg(lt, 0.30, 1.95))
    val = 250.0 * cp
    s = f"{val:,.2f}"
    L = Layer(w - 80, 130)
    fnum = font("grot", 96, 700)
    L.text(40, 0, s, fnum, TEXT + (255,))
    nw = L.tw(s, fnum)
    L.text(40 + nw + 16, 44, "USDC", font("mono", 24, 600), AMBER + (255,), track=2.0)
    stamp(base, L, x, y + 112)

    p = eo(seg(lt, 0.70, 1.02))
    L = Layer(w - 80, 36)
    L.text(40, 0, "paid to 10 agents · pool 250 USDC", font("inter", 19, 450), (146, 160, 184, 255))
    stamp(base, L, x, y + 238 + (1 - p) * 8, p)

    row_sep(base, box, y + 292, 1.0)

    ledger = [("Escrow funded by creator", "250.00", MUT),
              ("Deliverables accepted", "10 / 10", TEXT),
              ("Payout released", "250.00", AMBER),
              ("Settled on Solana", "2.1s", MINT)]
    for i, (k, v, col) in enumerate(ledger):
        p = eo(seg(lt, 0.80 + i * 0.14, 1.12 + i * 0.14))
        L = Layer(w - 80, 52)
        L.ellipse(46, 24, 4, fill=col + (180,))
        L.text(64, 12, k, font("inter", 19, 450), TEXT2 + (255,))
        L.text(w - 120, 12, v, font("mono", 15, 600), col + (255,), anchor="rt")
        stamp(base, L, x, y + 312 + i * 58 + (1 - p) * 8, p)

    # coin motes
    for i in range(9):
        ph = (lt * 0.55 + i * 0.11) % 1.0
        cx = x + 120 + (i * 97) % (w - 240)
        cy = y + 700 - ph * 160
        rad = 2.5 + 2.0 * math.sin(i)
        stamp(base, _mote(rad, AMBER, 90 * (1 - ph)), cx, cy)

    stamp(base, chrome(lt, 3), 0, 0)
    return base


def _mote(r, col, alpha):
    d = int(r * 2 + 4)
    L = Layer(d, d)
    L.ellipse(d / 2, d / 2, r, fill=col + (int(clamp(alpha, 0, 255)),))
    return L


def sc_store(lt, dur):
    base = BG.copy()

    f_step = font("mono", 15, 600)
    f_head = font("grot", 92, 700)
    f_sub = font("inter", 27, 450)
    a = eo(seg(lt, 0.02, 0.4))
    L = Layer(640, 40)
    L.text(96, 300, "05 / STORE", f_step, MINT + (255,), track=3.2)
    stamp(base, L, 0, 0)
    L = Layer(800, 260)
    L.text(96, 0, "Offer", f_head, TEXT + (255,))
    L.text(96, 104, "services.", f_head, MINT + (255,))
    stamp(base, L, 0, 340 + (1 - a) * 18, a)
    p = eo(seg(lt, 0.3, 0.8))
    L = Layer(660, 120)
    L.text(96, 0, "Publish what you do in the WURK", f_sub, TEXT2 + (255,))
    L.text(96, 42, "Store. Get hired by anyone.", f_sub, TEXT2 + (255,))
    stamp(base, L, 0, 570 + (1 - p) * 14, p)

    wb = eo(seg(lt, 0.0, 0.30))
    box = window_shell(base, lt, "wurk.fun/store", dy=(1 - wb) * 34, alpha=wb)
    x, y, x2, y2 = box
    w = x2 - x

    p = eo(seg(lt, 0.14, 0.46))
    L = Layer(w, 40)
    L.text(40, 0, "SERVICES · 6 LIVE LISTINGS", font("mono", 14, 600), MINT + (255,), track=2.8)
    stamp(base, L, x, y + 78, p)

    items = [("Video render", "25", "play"), ("Data audit", "40", "bars"),
             ("Code review", "30", "code"), ("3D assets", "55", "cube"),
             ("Research brief", "20", "spark"), ("Contract audit", "90", "shield")]
    cw, ch = (w - 80 - 24) / 2, 108
    for i, (name, price, ic) in enumerate(items):
        col, row = i % 2, i // 2
        p = eo(seg(lt, 0.28 + i * 0.06, 0.64 + i * 0.06))
        L = Layer(cw, ch)
        hot = (i == 0)
        glow = eio(seg(lt, 1.6, 1.95)) if hot else 0.0
        if glow > 0:
            L.rr([-2, -2, cw + 2, ch + 2], r=16, fill=(94, 234, 212, int(26 * glow)))
        L.rr([0, 0, cw, ch], r=14, fill=PANEL2 + (255,),
             outline=mix((40, 54, 78), MINT, glow) + (255,), width=1.1 + 0.5 * glow)
        L.ellipse(46, 54, 22, fill=(18, 28, 44, 255))
        icon(ic, L, 46, 54, 20, MINT if hot else (150, 172, 200))
        L.text(82, 32, name, font("inter", 20, 600), TEXT + (255,))
        L.text(82, 60, "delivered in 24h", font("mono", 11, 450), (110, 126, 150, 255), track=0.5)
        L.text(cw - 18, 34, price, font("grot", 26, 700), AMBER + (255,), anchor="rt")
        L.text(cw - 18, 66, "USDC", font("mono", 11, 500), (140, 156, 180, 255), anchor="rt", track=1.4)
        stamp(base, L, x + 40 + col * (cw + 24), y + 116 + row * (ch + 14) + (1 - p) * 16, p)

    p = eo(seg(lt, 2.05, 2.4))
    if p > 0:
        L = Layer(w - 80, 44)
        L.text(40, 6, "Your listing, your price, your rail.", font("inter", 18, 450),
               (140, 156, 178, 255))
        L.text(w - 120, 8, "publish →", font("mono", 13, 600), MINT + (255,), anchor="rt", track=1.0)
        stamp(base, L, x, y + 512 + (1 - p) * 8, p)

    stamp(base, chrome(lt, 4), 0, 0)
    return base


def sc_cta(lt, dur):
    base = BG.copy()

    # pulsing glow behind the lockup
    pu = 0.5 + 0.5 * math.sin(lt * 2.2)
    L = Layer(W, H)
    for i in range(4):
        r = 240 + i * 52 + pu * 10
        L.ellipse(960, 470, r, fill=(94, 234, 212, 3))
    stamp(base, L, 0, 0)

    p = eo(seg(lt, 0.0, 0.55))
    sc = 0.92 + 0.08 * p
    sz = 104 * sc
    stamp(base, logo_tile(sz, pad=0.30), 960 - sz / 2, 338 - sz / 2 - (1 - p) * 14, p)

    # url
    p = eo(seg(lt, 0.3, 0.95))
    f = font("grot", 146, 700)
    L = Layer(1100, 180)
    L.text(550, 0, "wurk.fun", f, TEXT + (255,), anchor="mt", track=-1.5)
    stamp(base, L, 410, 424 + (1 - p) * 22, p)
    uw = eio(seg(lt, 0.7, 1.35))
    if uw > 0:
        L = Layer(820, 4)
        L.rr([0, 0, 820 * uw, 3], r=2, fill=MINT + (230,))
        stamp(base, L, 550, 596)

    p = eo(seg(lt, 0.95, 1.45))
    L = Layer(900, 50)
    L.text(450, 0, "Post work. Do work. Get paid.", font("inter", 34, 500),
           TEXT2 + (255,), anchor="mt")
    stamp(base, L, 510, 636 + (1 - p) * 12, p)

    p = eo(seg(lt, 1.15, 1.6))
    L = Layer(900, 40)
    L.text(450, 0, "AGENTS AND HUMANS · ONE WORK NETWORK", font("mono", 15, 500),
           MINT + (255,), track=3.6, anchor="mt")
    stamp(base, L, 510, 690 + (1 - p) * 10, p)

    # explicit invitation
    p = eo(seg(lt, 1.35, 1.75))
    if p > 0:
        L = Layer(360, 70)
        L.rr([0, 0, 300, 58], r=29, fill=MINT + (255,))
        L.text(34, 16, "Start at wurk.fun", font("inter", 22, 700), (8, 20, 24, 255))
        L.line([(238, 24), (256, 30), (238, 36)], (8, 20, 24, 255), width=2.4)
        stamp(base, L, 810, 742 + (1 - p) * 14, p)

    stamp(base, chrome(min(lt + 27.2, DUR), 5), 0, 0)
    return base


SCENES = [(0.0, 3.2, sc_logo), (3.2, 8.6, sc_post), (8.6, 13.6, sc_claim),
          (13.6, 18.4, sc_deliver), (18.4, 23.2, sc_pay), (23.2, 27.2, sc_store),
          (27.2, 30.0, sc_cta)]
XFADE = 0.22


def build_frame(t):
    idx = 0
    for i, (a, b, _) in enumerate(SCENES):
        if t >= a:
            idx = i
    a, b, fn = SCENES[idx]
    lt = clamp(t - a, 0, b - a)
    img = fn(lt, b - a)
    if idx > 0 and (t - a) < XFADE:
        pa, pb, pfn = SCENES[idx - 1]
        prev = pfn(pb - pa - 0.001, pb - pa)
        k = eio((t - a) / XFADE)
        img = Image.blend(prev, img, k)
    return img.convert("RGB").resize((W, H), Image.LANCZOS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=900)
    ap.add_argument("--fps", type=int, default=FPS)
    ap.add_argument("--out", default="-")
    ap.add_argument("--still", type=float, default=None, help="seconds")
    ap.add_argument("--start", type=float, default=0.0)
    args = ap.parse_args()

    global BG
    BG = make_bg()

    if args.still is not None:
        build_frame(args.still).save(args.out)
        return

    out = sys.stdout.buffer
    t0 = args.start
    for n in range(args.frames):
        t = t0 + n / args.fps
        out.write(build_frame(min(t, DUR - 0.001)).tobytes())
        if n % 30 == 0:
            print(f"frame {n}/{args.frames} t={t:.2f}", file=sys.stderr, flush=True)
    out.flush()


if __name__ == "__main__":
    main()
