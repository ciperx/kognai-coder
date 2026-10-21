#!/usr/bin/env python3
"""WURK film — procedural 30 s soundtrack (numpy only, no samples).

A slow four-chord pad with air, a soft impact on each scene cut and a short
riser into the call to action.  Everything is synthesised from sine partials
and filtered noise, so the audio is as scripted as the picture.

usage: python3 gen_audio.py soundtrack.wav
"""
import sys
import wave

import numpy as np

SR = 48000
DUR = 30.0
N = int(SR * DUR)
t = np.arange(N, dtype=np.float64) / SR

CUTS = [0.0, 3.2, 8.6, 13.6, 18.4, 23.2, 27.2]
CHORDS = [
    (0.0, 3.2, [110.00, 164.81, 220.00]),   # Am
    (3.2, 8.6, [87.31, 130.81, 174.61]),    # F
    (8.6, 13.6, [130.81, 196.00, 261.63]),  # C
    (13.6, 18.4, [98.00, 146.83, 196.00]),  # G
    (18.4, 23.2, [110.00, 164.81, 220.00]), # Am
    (23.2, 27.2, [87.31, 130.81, 174.61]),  # F
    (27.2, 30.0, [130.81, 196.00, 261.63]), # C
]


def env_win(a, b, fade=0.7):
    """Raised-cosine window over [a,b] with soft edges."""
    e = np.zeros(N)
    i0, i1 = int(a * SR), min(N, int(b * SR))
    seg = np.ones(i1 - i0)
    nf = min(int(fade * SR), len(seg) // 2)
    if nf > 1:
        r = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, nf))
        seg[:nf] = r
        seg[-nf:] = r[::-1]
    e[i0:i1] = seg
    return e


def pad():
    out = np.zeros((N, 2))
    for a, b, notes in CHORDS:
        e = env_win(a, min(DUR, b + 0.6), fade=0.85)
        for k, f0 in enumerate(notes):
            for j, det in enumerate((-0.0016, 0.0016)):
                f = f0 * (1 + det)
                ph = 2 * np.pi * f * t + k * 0.7 + j * 1.3
                amp = 0.085 / (1 + k * 0.55)
                sig = np.sin(ph) + 0.16 * np.sin(2 * ph) + 0.05 * np.sin(3 * ph)
                out[:, j] += sig * amp * e
        # sub root, mono-ish
        sub = np.sin(2 * np.pi * notes[0] / 2 * t) * 0.055 * e
        out[:, 0] += sub
        out[:, 1] += sub
    return out


def air():
    rng = np.random.default_rng(7)
    n = rng.standard_normal((N, 2))
    # gentle low-pass shaping in the frequency domain (fast, no IIR loop)
    freqs = np.fft.rfftfreq(N, 1 / SR)
    shape = 1.0 / (1.0 + (freqs / 1100.0) ** 2)
    for ch in range(2):
        spec = np.fft.rfft(n[:, ch])
        n[:, ch] = np.fft.irfft(spec * shape, N)
    trem = 0.6 + 0.4 * np.sin(2 * np.pi * 0.09 * t)
    gain = np.interp(t, [0, 1.5, 27.2, 30.0], [0.0, 1.0, 1.0, 0.15])
    return n * 0.9 * trem[:, None] * gain[:, None]


def impact(at, strength=1.0):
    """Soft low thump plus a filtered click, decaying in ~0.35 s."""
    n = int(0.45 * SR)
    tt = np.arange(n) / SR
    body = np.sin(2 * np.pi * (58 + 40 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 9.0)
    click = np.random.default_rng(int(at * 100)).standard_normal(n) * np.exp(-tt * 42)
    # crude lowpass on the click
    k = np.exp(-2 * np.pi * 1800 / SR)
    click = np.convolve(click, [(1 - k)], mode="same")
    s = (body * 0.20 + click * 0.05) * strength
    buf = np.zeros((N, 2))
    i = int(at * SR)
    m = min(n, N - i)
    buf[i:i + m, 0] = s[:m]
    buf[i:i + m, 1] = s[:m] * 0.94
    return buf


def riser():
    a, b = 26.0, 27.25
    i0, i1 = int(a * SR), int(b * SR)
    n = i1 - i0
    tt = np.arange(n) / SR
    u = tt / tt[-1]
    f = 180 * (1 + 3.4 * u ** 2)
    ph = 2 * np.pi * np.cumsum(f) / SR
    tone = 0.5 * np.sin(ph) * u ** 2
    rng = np.random.default_rng(3)
    ns = rng.standard_normal(n)
    k = 0.55
    ns = ns - k * np.concatenate([[0], ns[:-1]])
    air_s = ns * 0.30 * u ** 2.4
    buf = np.zeros((N, 2))
    s = (tone * 0.05 + air_s * 0.16)
    buf[i0:i1, 0] = s
    buf[i0:i1, 1] = s * 0.9
    return buf


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "soundtrack.wav"
    mix = pad() + air()
    for i, c in enumerate(CUTS):
        mix += impact(c + (0.06 if i else 0.0), 1.0 if i else 0.7)
    mix += riser()

    # gentle saturation + master fades
    mix = np.tanh(mix * 1.15) * 0.92
    fi = int(0.25 * SR)
    mix[:fi] *= np.linspace(0, 1, fi)[:, None]
    fo = int(1.4 * SR)
    mix[-fo:] *= np.linspace(1, 0, fo)[:, None] ** 1.5
    mix *= 0.72 / max(1e-9, np.abs(mix).max())

    pcm = (np.clip(mix, -1, 1) * 32767).astype("<i2")
    with wave.open(out_path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"wrote {out_path} {N/SR:.2f}s rms={np.sqrt((mix**2).mean()):.3f} "
          f"peak={np.abs(mix).max():.3f}")


if __name__ == "__main__":
    main()
