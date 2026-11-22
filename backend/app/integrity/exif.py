"""EXIF facts for gallery uploads. Live browser captures carry no EXIF, so this is only used
for uploads. EXIF is easy to forge: it can lower trust, never prove a photo genuine."""

import io
from dataclasses import dataclass
from datetime import datetime

from PIL import Image

EXIF_IFD = 0x8769
GPS_IFD = 0x8825
DATETIME_ORIGINAL = 36867


@dataclass
class ExifFacts:
    present: bool
    taken_at: datetime | None
    lat: float | None
    lng: float | None


def _deg(values, ref) -> float | None:
    try:
        d, m, s = (float(v) for v in values)
    except (TypeError, ValueError):
        return None
    out = d + m / 60 + s / 3600
    return -out if ref in ("S", "W") else out


def read_exif(data: bytes) -> ExifFacts:
    try:
        with Image.open(io.BytesIO(data)) as im:
            exif = im.getexif()
    except Exception:  # noqa: BLE001 - unreadable EXIF is simply "absent"
        return ExifFacts(False, None, None, None)
    if not exif:
        return ExifFacts(False, None, None, None)

    taken = None
    raw = exif.get_ifd(EXIF_IFD).get(DATETIME_ORIGINAL)
    if isinstance(raw, str):
        try:
            taken = datetime.strptime(raw.strip(), "%Y:%m:%d %H:%M:%S")
        except ValueError:
            taken = None

    gps = exif.get_ifd(GPS_IFD)
    lat = _deg(gps.get(2), gps.get(1)) if gps.get(2) else None
    lng = _deg(gps.get(4), gps.get(3)) if gps.get(4) else None
    return ExifFacts(True, taken, lat, lng)
