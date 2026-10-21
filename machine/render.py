#!/usr/bin/env python3
"""Marble Loop v2: code-driven machine animation, seamless by construction.

usage: render2.py --frames 600 --fps 30 --out -   (rawvideo to stdout)
       render2.py --still 120 --out still.png
"""
import argparse
import math
import sys

import numpy as np
from PIL import Image, ImageDraw

W, H = 1920, 1080
SS = 2

BG_TOP = (11, 16, 29)
BG_BOTTOM = (27, 36, 58)
PANEL = (30, 40, 62)
METAL = (60, 74, 100)
METAL_LIGHT = (104, 126, 160)
RAIL = (78, 96, 126)
ACCENT = (242, 176, 72)
ACCENT2 = (82, 206, 194)
BALL = (247, 249, 252)

FLOOR_Y = 700
TOP_Y = 300


def lerp(a, b, u):
    return a + (b - a) * u


def polyline(points):
    pts = [(x * SS, y * SS) for x, y in points]
    segs, total = [], 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        d = math.hypot(x1 - x0, y1 - y0)
        segs.append((x0, y0, x1, y1, d, total))
        total += d
    return segs, total


def at(segs, total, s):
    s = s % 1.0
    target = s * total
    for x0, y0, x1, y1, d, start in segs:
        if target <= start + d or start + d >= total:
            u = 0.0 if d == 0 else min(max((target - start) / d, 0.0), 1.0)
            return lerp(x0, x1, u), lerp(y0, y1, u), (x1 - x0) / d, (y1 - y0) / d
    x0, y0, x1, y1, d, _ = segs[-1]
    return x1, y1, 1.0, 0.0


def bg():
    top = np.array(BG_TOP, dtype=np.float32)
    bot = np.array(BG_BOTTOM, dtype=np.float32)
    rows = np.linspace(0.0, 1.0, H * SS, dtype=np.float32)[:, None]
    img = top[None, :] * (1 - rows) + bot[None, :] * rows
    return Image.fromarray(np.repeat(img[:, None, :], W * SS, axis=1).astype(np.uint8), "RGB")


def draw_gear(d, cx, cy, r, teeth, phase, fill=METAL, edge=METAL_LIGHT):
    d.ellipse([cx - r * 0.80, cy - r * 0.80, cx + r * 0.80, cy + r * 0.80], fill=fill)
    for k in range(teeth):
        a = phase + 2 * math.pi * k / teeth
        hx, hy = cx + math.cos(a) * r * 0.84, cy + math.sin(a) * r * 0.84
        tx, ty = cx + math.cos(a) * r * 1.05, cy + math.sin(a) * r * 1.05
        nx, ny = -math.sin(a), math.cos(a)
        w = r * 0.060
        d.polygon([(hx + nx * w, hy + ny * w), (tx + nx * w * 0.65, ty + ny * w * 0.65),
                   (tx - nx * w * 0.65, ty - ny * w * 0.65), (hx - nx * w, hy - ny * w)], fill=edge)
    d.ellipse([cx - r * 0.30, cy - r * 0.30, cx + r * 0.30, cy + r * 0.30], fill=(46, 58, 82))
    for k in range(5):
        a = -phase + 2 * math.pi * k / 5
        d.line([cx, cy, cx + math.cos(a) * r * 0.72, cy + math.sin(a) * r * 0.72],
               fill=(46, 58, 82), width=int(r * 0.10))
    d.ellipse([cx - r * 0.11, cy - r * 0.11, cx + r * 0.11, cy + r * 0.11], fill=edge)


def draw_path(d, segs):
    for x0, y0, x1, y1, _, _ in segs:
        d.line([x0, y0, x1, y1], fill=(38, 48, 70), width=int(26 * SS))
    for x0, y0, x1, y1, _, _ in segs:
        d.line([x0, y0, x1, y1], fill=RAIL, width=int(9 * SS))


def build_frame(t, T):
    u = (t % T) / T

    path = [
        (300, TOP_Y), (700, TOP_Y),
        (980, 372), (1120, 470),
        (1480, 470), (1560, FLOOR_Y),
        (420, FLOOR_Y),
        (300, 660), (300, TOP_Y),
    ]
    segs, total = polyline(path)

    img = bg()
    d = ImageDraw.Draw(img)

    d.rounded_rectangle([110 * SS, 205 * SS, 1810 * SS, 245 * SS], radius=10 * SS, fill=PANEL)
    d.rounded_rectangle([140 * SS, (FLOOR_Y + 60) * SS, 1780 * SS, (FLOOR_Y + 120) * SS],
                        radius=14 * SS, fill=PANEL)

    # drive belt from the gear train up to the lift wheel
    d.line([200 * SS, 800 * SS, 300 * SS, 340 * SS], fill=(70, 86, 114), width=int(14 * SS))
    d.line([262 * SS, 800 * SS, 362 * SS, 340 * SS], fill=(70, 86, 114), width=int(14 * SS))

    # chute that carries the ball from the upper rail onto the conveyor
    d.line([1478 * SS, 470 * SS, 1548 * SS, FLOOR_Y * SS], fill=(72, 88, 118), width=int(10 * SS))
    d.line([1502 * SS, 470 * SS, 1572 * SS, FLOOR_Y * SS], fill=(72, 88, 118), width=int(10 * SS))
    d.polygon([(420 * SS, (FLOOR_Y - 34) * SS), (500 * SS, (FLOOR_Y - 6) * SS),
               (500 * SS, (FLOOR_Y + 6) * SS), (420 * SS, (FLOOR_Y + 34) * SS)], fill=(72, 88, 118))

    # lift chain with scoops: up the left side, down the right side
    for dirn, cx in ((1, 288),):
        for i in range(9):
            p = ((u * 3 + i / 9.0) % 1.0) if dirn > 0 else ((u * 3 + i / 9.0) % 1.0)
            y = lerp(FLOOR_Y, 330, p if dirn > 0 else 1 - p) * SS
            k = 0.6 + 0.4 * math.sin(math.pi * p)
            d.line([cx * SS - 14 * SS, y] + [cx * SS + 14 * SS, y],
                   fill=(int(120 * k), int(146 * k), int(184 * k)), width=int(7 * SS))
            d.arc([cx * SS - 26 * SS, y - 4 * SS, cx * SS + 26 * SS, y + 34 * SS], 200, 340,
                  fill=(int(120 * k), int(146 * k), int(184 * k)), width=int(6 * SS))

    d.arc([246 * SS, 286 * SS, 366 * SS, 366 * SS], 250, 20, fill=(96, 118, 152), width=int(9 * SS))

    # conveyor drive chain from the small gear to the last roller
    d.line([420 * SS, 762 * SS, 470 * SS, (FLOOR_Y + 34) * SS], fill=(70, 86, 114), width=int(9 * SS))

    draw_path(d, segs)

    for i in range(10):
        cx = (470 + i * 108) * SS
        cy = (FLOOR_Y + 34) * SS
        d.ellipse([cx - 15 * SS, cy - 15 * SS, cx + 15 * SS, cy + 15 * SS], fill=(50, 62, 86))
        a = 10 * math.pi * u + i * 0.7
        d.line([cx, cy, cx + math.cos(a) * 15 * SS, cy + math.sin(a) * 15 * SS],
               fill=ACCENT2, width=int(3 * SS))

    draw_gear(d, 200 * SS, 800 * SS, 118 * SS, 18, 2 * math.pi * u)
    draw_gear(d, 385 * SS, 762 * SS, 76 * SS, 11, -4 * math.pi * u)
    draw_gear(d, 300 * SS, 330 * SS, 54 * SS, 9, 4 * math.pi * u, fill=(52, 66, 92))

    ax, ay = 1120 * SS, 212 * SS
    ang = math.pi / 2 + math.sin(6 * math.pi * u) * 0.45
    ex, ey = ax + math.cos(ang) * 250 * SS, ay + math.sin(ang) * 250 * SS
    d.line([ax, ay, ex, ey], fill=METAL_LIGHT, width=int(8 * SS))
    d.ellipse([ax - 13 * SS, ay - 13 * SS, ax + 13 * SS, ay + 13 * SS], fill=METAL)
    d.ellipse([ex - 22 * SS, ey - 22 * SS, ex + 22 * SS, ey + 22 * SS], fill=ACCENT)
    d.ellipse([ex - 8 * SS, ey - 10 * SS, ex + 4 * SS, ey + 2 * SS], fill=(255, 226, 170))

    for k in range(3):
        s = (u + k / 3.0) % 1.0
        x, y, _, _ = at(segs, total, s)
        r = 23 * SS
        d.ellipse([x - r * 1.15, y + r * 0.55, x + r * 1.15, y + r * 1.15], fill=(18, 24, 38))
        d.ellipse([x - r, y - r, x + r, y + r], fill=BALL)
        d.ellipse([x - r * 0.50, y - r * 0.60, x + r * 0.20, y + r * 0.10], fill=(255, 255, 255))

    d.rectangle([0, 0, W * SS, 6 * SS], fill=ACCENT2)
    d.rectangle([0, H * SS - 6 * SS, W * SS, H * SS], fill=ACCENT)

    return img.resize((W, H), Image.LANCZOS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=600)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--out", default="-")
    ap.add_argument("--still", type=int, default=None)
    args = ap.parse_args()

    T = args.frames / args.fps
    if args.still is not None:
        build_frame(args.still / args.fps, T).save(args.out)
        return

    out = sys.stdout.buffer
    for n in range(args.frames):
        out.write(build_frame(n / args.fps, T).tobytes())
        if n % 60 == 0:
            print(f"frame {n}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
