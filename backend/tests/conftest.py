"""Test setup.

API tests need a PostGIS database. Point TEST_DATABASE_URL at a throwaway database; its
tables are dropped and recreated on every run. Without it, those tests are skipped.
"""

import os
import tempfile
from pathlib import Path

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL")
if TEST_DB:
    os.environ["DATABASE_URL"] = TEST_DB
os.environ["PHOTO_DIR"] = tempfile.mkdtemp(prefix="pothole-photos-")
os.environ["IP_HOURLY_LIMIT"] = "100000"  # tests share one client address
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["DETECTION_MODE"] = "advisory"  # enforce paths are tested explicitly
os.environ["AUTHORITY_TOKEN"] = "test-authority"
os.environ["INTERNAL_TOKEN"] = "test-internal"

import itertools  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

_seeds = itertools.count(1)


def scene(seed: int, w: int = 640, h: int = 480) -> np.ndarray:
    """A synthetic road-like scene: textured asphalt with random blobs, unique per seed."""
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), rng.integers(70, 130), np.float32)
    img += cv2.GaussianBlur(rng.normal(0, 30, (h, w, 1)).astype(np.float32), (0, 0), 0.7)[..., None]
    for _ in range(12):
        center = (int(rng.integers(0, w)), int(rng.integers(0, h)))
        axes = (int(rng.integers(10, 90)), int(rng.integers(8, 60)))
        cv2.ellipse(img, center, axes, float(rng.integers(0, 180)), 0, 360,
                    [float(v) for v in rng.integers(20, 200, 3)], -1)
    img = cv2.GaussianBlur(img, (0, 0), 0.6)
    return np.clip(img + rng.normal(0, 4, img.shape), 0, 255).astype(np.uint8)


def encode(img: np.ndarray) -> bytes:
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()


def jpeg_bytes(w: int = 640, h: int = 480, seed: int | None = None) -> bytes:
    """A unique realistic frame per call (so duplicate-photo checks do not fire by accident)."""
    return encode(scene(next(_seeds) if seed is None else seed, w, h))


def burst(n: int = 3, seed: int | None = None) -> list[bytes]:
    """n live-camera-like frames of one scene: small hand shake and fresh sensor noise each."""
    base = scene(next(_seeds) if seed is None else seed, 700, 520)
    rng = np.random.default_rng(seed or 0)
    out = []
    for i in range(n):
        dx, dy = 20 + 3 * i, 20 + 2 * i
        frame = base[dy:dy + 480, dx:dx + 640].astype(np.float32) + rng.normal(0, 3, (480, 640, 3))
        out.append(encode(np.clip(frame, 0, 255).astype(np.uint8)))
    return out


class FakeDetector:
    """Stands in for the ONNX model: returns the boxes the test sets, scaled to the frame."""

    def __init__(self):
        self.path = Path("fake.onnx")
        self.boxes = []  # list of (x1, y1, x2, y2, score) as fractions of width/height
        self.per_frame = None  # optional list of box lists, used frame by frame (cycling)
        self._calls = 0

    def detect(self, image):
        from app.pipeline.detect import Box, Detection

        h, w = image.shape[:2]
        spec = self.boxes
        if self.per_frame:
            spec = self.per_frame[self._calls % len(self.per_frame)]
            self._calls += 1
        boxes = [Box(x1 * w, y1 * h, x2 * w, y2 * h, s) for x1, y1, x2, y2, s in spec]
        return Detection(boxes, w, h, 1.0)


@pytest.fixture
def fake_detector():
    return FakeDetector()


@pytest.fixture
def db_client(fake_detector):
    if not TEST_DB:
        pytest.skip("TEST_DATABASE_URL not set")
    from fastapi.testclient import TestClient

    from app import models  # noqa: F401
    from app.db import Base, engine
    from app.main import app

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    from app.pipeline.detect import get_detector

    app.dependency_overrides[get_detector] = lambda: fake_detector
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
