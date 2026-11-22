"""Screen-recapture (moire) score from the frequency spectrum of the whole frame.

Photographing a screen with a phone camera overlays two pixel grids. Their interference
(moire) and the screen's own pixel grid show up as sharp, isolated peaks in the 2D Fourier
spectrum. Natural road photos have smooth spectra. The score is how far the strongest
mid/high-frequency peaks rise above the locally smoothed spectrum.

The frame is only downscaled as a whole (never cropped), so the full field of view counts.
Thresholds are calibrated on real road photos (tools/calibrate_screen.py) and must be
re-checked with real screen photos; treat the score as a penalty, never a hard reject.
"""

import cv2
import numpy as np

ANALYSIS_SIDE = 512
BAND = (0.12, 0.95)  # fraction of the Nyquist radius: skip the low-frequency image content
TOP_K = 24


def screen_score(image_bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY) if image_bgr.ndim == 3 else image_bgr
    h, w = gray.shape
    scale = ANALYSIS_SIDE / max(h, w)
    if scale < 1:
        gray = cv2.resize(gray, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    g = gray.astype(np.float32)
    g -= g.mean()
    g *= np.outer(np.hanning(g.shape[0]), np.hanning(g.shape[1])).astype(np.float32)

    spec = np.log1p(np.abs(np.fft.fftshift(np.fft.fft2(g)))).astype(np.float32)
    background = cv2.blur(spec, (15, 15))
    residual = spec - background

    hh, ww = spec.shape
    yy, xx = np.ogrid[:hh, :ww]
    r = np.sqrt(((yy - hh / 2) / (hh / 2)) ** 2 + ((xx - ww / 2) / (ww / 2)) ** 2)
    band = residual[(r > BAND[0]) & (r < BAND[1])]
    if band.size < TOP_K:
        return 0.0
    return float(np.mean(np.partition(band, -TOP_K)[-TOP_K:]))
