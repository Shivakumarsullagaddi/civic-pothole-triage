"""Burst consistency: the 3 live frames should be the same scene, but not pixel-identical.

- Identical frames: a real handheld camera always has sensor noise and slight motion, so
  byte-for-byte or near-identical frames suggest a static image was submitted three times.
- Different scenes: frames ~300 ms apart must share most features. Few feature matches
  suggest frames stitched together from different photos.
Inconclusive cases (too few features, e.g. a blank wall) are not penalised.
"""

from dataclasses import dataclass

import cv2
import numpy as np

SIDE = 480
IDENTICAL_MEAN_DIFF = 0.6  # mean absolute grey-level difference (0-255)
MIN_KEYPOINTS = 40
MIN_MATCH_RATIO = 0.15


@dataclass
class BurstResult:
    frames: int
    identical: bool
    same_scene: bool | None  # None = inconclusive
    mean_diff: float
    match_ratio: float | None


def _small_gray(img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    s = SIDE / max(h, w)
    return cv2.resize(gray, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else gray


def check_burst(frames: list[np.ndarray]) -> BurstResult:
    if len(frames) < 2:
        return BurstResult(len(frames), False, None, 0.0, None)
    grays = [_small_gray(f) for f in frames]
    if any(g.shape != grays[0].shape for g in grays):
        return BurstResult(len(frames), False, False, 255.0, 0.0)

    diffs = [float(np.mean(cv2.absdiff(a, b))) for a, b in zip(grays, grays[1:])]
    identical = max(diffs) < IDENTICAL_MEAN_DIFF

    orb = cv2.ORB_create(nfeatures=800)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    ratios = []
    for a, b in zip(grays, grays[1:]):
        ka, da = orb.detectAndCompute(a, None)
        kb, db = orb.detectAndCompute(b, None)
        if da is None or db is None or len(ka) < MIN_KEYPOINTS or len(kb) < MIN_KEYPOINTS:
            continue
        pairs = matcher.knnMatch(da, db, k=2)
        good = [m for m, *rest in pairs if rest and m.distance < 0.75 * rest[0].distance]
        ratios.append(len(good) / min(len(ka), len(kb)))
    if not ratios:
        return BurstResult(len(frames), identical, None, max(diffs), None)
    worst = min(ratios)
    return BurstResult(len(frames), identical, worst >= MIN_MATCH_RATIO, max(diffs), worst)
