"""Step 1-2 of the report pipeline: receive and validate input (PLAN.md section 4)."""

import io
import re
from dataclasses import dataclass
from datetime import datetime

from PIL import Image, UnidentifiedImageError

MAX_FRAMES = 3
MAX_FRAME_BYTES = 8 * 1024 * 1024
MIN_SIDE_PX = 240
MAX_SIDE_PX = 8000
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
CAPTURE_SOURCES = {"camera", "upload"}
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class InputError(ValueError):
    """The submission is malformed; maps to HTTP 422."""


@dataclass
class Frame:
    data: bytes
    format: str
    width: int
    height: int


@dataclass
class ReportInput:
    frames: list[Frame]
    lat: float
    lng: float
    accuracy_m: float | None
    captured_at: datetime | None
    device_id: str
    capture_source: str = "camera"


def check_frame(data: bytes, index: int) -> Frame:
    if not data:
        raise InputError(f"Frame {index} is empty")
    if len(data) > MAX_FRAME_BYTES:
        raise InputError(f"Frame {index} is larger than {MAX_FRAME_BYTES // (1024 * 1024)} MB")
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt, (w, h) = img.format, img.size
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise InputError(f"Frame {index} is not a readable image") from exc
    if fmt not in ALLOWED_FORMATS:
        raise InputError(f"Frame {index} format {fmt} is not allowed")
    if min(w, h) < MIN_SIDE_PX or max(w, h) > MAX_SIDE_PX:
        raise InputError(f"Frame {index} size {w}x{h} is out of range")
    return Frame(data=data, format=fmt, width=w, height=h)


def build_input(
    frames: list[bytes],
    lat: float,
    lng: float,
    accuracy_m: float | None,
    captured_at: datetime | None,
    device_id: str,
    capture_source: str = "camera",
) -> ReportInput:
    if not 1 <= len(frames) <= MAX_FRAMES:
        raise InputError(f"Send between 1 and {MAX_FRAMES} frames, got {len(frames)}")
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise InputError("Latitude or longitude out of range")
    if accuracy_m is not None and not 0 <= accuracy_m <= 100_000:
        raise InputError("GPS accuracy out of range")
    if not DEVICE_ID_RE.match(device_id):
        raise InputError("device_id must be 8-64 characters of letters, digits, _ or -")
    if capture_source not in CAPTURE_SOURCES:
        raise InputError(f"capture_source must be one of {sorted(CAPTURE_SOURCES)}")
    checked = [check_frame(data, i) for i, data in enumerate(frames)]
    return ReportInput(checked, lat, lng, accuracy_m, captured_at, device_id, capture_source)
