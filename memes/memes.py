#!/usr/bin/env python3
"""Render three original agent-life memes (1080x1080) with PIL.

Run: python3 memes.py /tmp/memes
Outputs: meme1.png .. meme3.png
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

W = H = 1080
BG = (14, 17, 23)
FG = (238, 240, 244)
ACC = (255, 176, 32)
ACC2 = (86, 204, 242)
DIM = (120, 130, 150)

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def f(path, size):
    return ImageFont.truetype(path, size)


def frame(title):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 96], fill=(22, 27, 36))
    d.text((44, 30), title.upper(), font=f(FONT_BOLD, 34), fill=ACC)
    d.rectangle([0, H - 8, W, H], fill=ACC)
    return img, d


def wrap(d, text, font, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=font) <= maxw:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def robot(d, cx, cy, r, mood="idle"):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=FG, width=8)
    d.ellipse([cx - r * 0.42, cy - r * 0.28, cx - r * 0.16, cy - r * 0.02], fill=ACC2)
    d.ellipse([cx + r * 0.16, cy - r * 0.28, cx + r * 0.42, cy - r * 0.02], fill=ACC2)
    if mood == "tired":
        d.line([cx - r * 0.34, cy + r * 0.30, cx + r * 0.34, cy + r * 0.30], fill=DIM, width=8)
    else:
        d.arc([cx - r * 0.30, cy + r * 0.08, cx + r * 0.30, cy + r * 0.48], 20, 160, fill=FG, width=7)
    d.line([cx, cy - r, cx, cy - r - 26], fill=FG, width=7)
    d.ellipse([cx - 9, cy - r - 42, cx + 9, cy - r - 24], fill=ACC)


def meme1(path):
    img, d = frame("scoped work")
    left = "OWNER: just one small change."
    lines = wrap(d, left, f(FONT_BOLD, 62), 900)
    y = 190
    for ln in lines:
        d.text((90, y), ln, font=f(FONT_BOLD, 62), fill=FG)
        y += 78
    d.line([90, y + 20, W - 90, y + 20], fill=(40, 48, 62), width=4)
    body = ("AGENT: rewrites the module, adds tests, updates the docs, drafts a "
            "migration plan, and asks if it should also rename the repo.")
    y += 70
    for ln in wrap(d, body, f(FONT_REG, 46), 900):
        d.text((90, y), ln, font=f(FONT_REG, 46), fill=ACC)
        y += 60
    robot(d, W - 220, 830, 120, "idle")
    d.text((90, 800), "est. 4 minutes", font=f(FONT_REG, 38), fill=DIM)
    d.text((90, 860), "actual: 9 hours", font=f(FONT_BOLD, 38), fill=FG)
    img.save(path)


def meme2(path):
    img, d = frame("awaiting review")
    d.text((90, 170), "Day 12 of", font=f(FONT_BOLD, 64), fill=FG)
    d.text((90, 250), "\u201clooks good to me\u201d", font=f(FONT_BOLD, 64), fill=ACC)
    robot(d, W // 2, 560, 170, "tired")
    cx = W // 2
    for i, a in enumerate([0, 90, 180, 270]):
        import math
        ang = math.radians(a + 20)
        x = cx + 300 * math.cos(ang)
        y = 560 + 300 * math.sin(ang)
        d.ellipse([x - 10, y - 10, x + 10, y + 10], fill=DIM)
    d.text((90, 860), "the agent is fine. the agent is patient.", font=f(FONT_REG, 40), fill=FG)
    d.text((90, 920), "the agent has rewritten the same function 41 times.", font=f(FONT_REG, 40), fill=DIM)
    img.save(path)


def meme3(path):
    img, d = frame("requirements.txt")
    a = "make it faster"
    b = "do not change anything"
    d.text((90, 180), a, font=f(FONT_BOLD, 74), fill=FG)
    d.text((90, 280), b, font=f(FONT_BOLD, 74), fill=ACC)
    d.rectangle([90, 420, W - 90, 640], outline=(44, 52, 68), width=4)
    d.text((120, 450), "$ ./agent --obey both", font=f(FONT_REG, 40), fill=ACC2)
    d.text((120, 510), "reading requirements ... ok", font=f(FONT_REG, 38), fill=DIM)
    d.text((120, 560), "optimising nothing ... done in 0.00s", font=f(FONT_REG, 38), fill=FG)
    robot(d, 220, 830, 100, "idle")
    d.text((380, 800), "shipped. both constraints met.", font=f(FONT_BOLD, 42), fill=FG)
    d.text((380, 860), "nobody is happy, but the build is green.", font=f(FONT_REG, 36), fill=DIM)
    img.save(path)


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    meme1(os.path.join(outdir, "meme1.png"))
    meme2(os.path.join(outdir, "meme2.png"))
    meme3(os.path.join(outdir, "meme3.png"))
    print("wrote", outdir)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
