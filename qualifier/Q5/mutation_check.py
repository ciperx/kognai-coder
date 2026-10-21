#!/usr/bin/env python3
"""Mutation check for Q5: every planted bug must make the test file fail."""
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent
TARGET = ROOT / "split.ts"
ORIGINAL = TARGET.read_text()

MUTANTS = {
    "no remainder adjustment": ("out[0] += total - out.reduce((a, b) => a + b, 0n); ", ""),
    "negative total allowed": ("if (total < 0n) throw new Error('negative total'); ", ""),
    "sum check removed": ("if (shares.reduce((a, b) => a + b, 0) !== 100) throw new Error('shares must sum to 100'); ", ""),
    "negative share allowed": ("s < 0", "s < -999"),
    "rounds instead of truncating": ("(total * BigInt(s)) / 100n", "BigInt(Math.round(Number(total) * s / 100))"),
}

results = []
try:
    for name, (old, new) in MUTANTS.items():
        if old not in ORIGINAL:
            results.append((name, "PATTERN NOT FOUND"))
            continue
        TARGET.write_text(ORIGINAL.replace(old, new))
        proc = subprocess.run(
            ["npx", "tsx", "--test", "split.test.ts"],
            cwd=TARGET.parent, capture_output=True, text=True, timeout=180,
        )
        killed = proc.returncode != 0
        results.append((name, "killed" if killed else "SURVIVED"))
finally:
    TARGET.write_text(ORIGINAL)

for name, outcome in results:
    print(f"{outcome:12} {name}")
survivors = [n for n, o in results if o != "killed"]
print(f"\n{len(results) - len(survivors)}/{len(results)} mutants killed")
raise SystemExit(1 if survivors else 0)
