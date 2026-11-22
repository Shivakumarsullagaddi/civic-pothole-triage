"""Calibrate the screen-recapture score.

Prints the score distribution for folders of real road photos and for simulated screen
recaptures (each road photo rendered on an RGB sub-pixel grid, then re-photographed with
slight rotation, non-integer scaling, blur and noise). Use it again with REAL phone photos of
a laptop/phone screen: put them in a folder and pass --screens <folder>.

Usage (from backend/):
    python tools/calibrate_screen.py ../data/datasets/pothole_mix/images/test
    python tools/calibrate_screen.py <road folder> --screens <real screen photo folder>
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.integrity.screen import screen_score  # noqa: E402


def simulate_screen_photo(img: np.ndarray, rng: random.Random) -> np.ndarray:
    """Render img on a sub-pixel grid (like an LCD) and photograph it with a phone."""
    h, w = img.shape[:2]
    base = cv2.resize(img, (min(w, 480), round(h * min(w, 480) / w)), interpolation=cv2.INTER_AREA)
    bh, bw = base.shape[:2]
    screen = np.zeros((bh * 3, bw * 3, 3), np.uint8)
    for c, col in enumerate((2, 1, 0)):  # BGR image: R, G, B stripes left to right
        screen[:, c::3, col] = np.repeat(np.repeat(base[:, :, col], 3, axis=0), 1, axis=1)
    screen[2::3, :, :] = (screen[2::3, :, :] * 0.35).astype(np.uint8)  # dark row gap
    angle = rng.uniform(-4, 4)
    scale = rng.uniform(0.33, 0.47)  # camera sees the screen at a non-integer scale
    M = cv2.getRotationMatrix2D((screen.shape[1] / 2, screen.shape[0] / 2), angle, scale)
    out_w, out_h = round(screen.shape[1] * scale), round(screen.shape[0] * scale)
    M[0, 2] += out_w / 2 - screen.shape[1] / 2
    M[1, 2] += out_h / 2 - screen.shape[0] / 2
    shot = cv2.warpAffine(screen, M, (out_w, out_h), flags=cv2.INTER_LINEAR)
    shot = cv2.GaussianBlur(shot, (0, 0), rng.uniform(0.3, 0.7))
    noise = np.random.default_rng(rng.randint(0, 10**6)).normal(0, 3, shot.shape)
    return np.clip(shot.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def summary(name: str, scores: list[float]) -> None:
    a = np.array(scores)
    print(f"{name:28} n={len(a):4}  min {a.min():.2f}  p50 {np.median(a):.2f}  p95 {np.percentile(a, 95):.2f}  "
          f"p99 {np.percentile(a, 99):.2f}  max {a.max():.2f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("roads", type=Path, nargs="+")
    ap.add_argument("--screens", type=Path, help="folder of real photos of screens")
    ap.add_argument("--limit", type=int, default=400)
    args = ap.parse_args()
    rng = random.Random(0)

    paths = [p for d in args.roads for p in sorted(d.glob("*.jpg"))]
    rng.shuffle(paths)
    paths = paths[: args.limit]
    real, fake = [], []
    for p in paths:
        img = cv2.imread(str(p))
        if img is None:
            continue
        real.append(screen_score(img))
        fake.append(screen_score(simulate_screen_photo(img, rng)))
    summary("real road photos", real)
    summary("simulated screen photos", fake)
    if args.screens:
        shots = [cv2.imread(str(p)) for p in sorted(args.screens.glob("*.jp*g"))]
        summary("REAL screen photos", [screen_score(s) for s in shots if s is not None])
    for t in (1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0):
        fp = np.mean(np.array(real) >= t)
        tp = np.mean(np.array(fake) >= t)
        print(f"threshold {t:.1f}: flags {tp:6.1%} of simulated screens, {fp:6.1%} of real roads")


if __name__ == "__main__":
    main()
