"""Is the photo good enough to say "no pothole here"? Brightness and sharpness on the whole frame.

Calibrated on 691 real road photos (2026-11-22): brightness p1 66.7 / p99 175.3, sharpness
(Laplacian variance at 640 px) p1 37.6; a Gaussian blur of sigma 2 drops sharpness to ~5.
"""

from dataclasses import dataclass

import cv2
import numpy as np

MIN_BRIGHTNESS, MAX_BRIGHTNESS = 35.0, 235.0
MIN_SHARPNESS = 30.0


@dataclass
class Quality:
    brightness: float
    sharpness: float

    @property
    def problem(self) -> str | None:
        if self.brightness < MIN_BRIGHTNESS:
            return "photo too dark"
        if self.brightness > MAX_BRIGHTNESS:
            return "photo overexposed"
        if self.sharpness < MIN_SHARPNESS:
            return "photo too blurry"
        return None


def measure(image_bgr: np.ndarray) -> Quality:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    k = 640 / max(h, w)
    if k < 1:  # whole-frame downscale only
        gray = cv2.resize(gray, (round(w * k), round(h * k)), interpolation=cv2.INTER_AREA)
    return Quality(float(gray.mean()), float(cv2.Laplacian(gray, cv2.CV_64F).var()))
