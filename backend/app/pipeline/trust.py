"""Steps 5, 8, 9 of the report pipeline: integrity checks, trust score and decision.

trust = 1.0 - sum(penalties), clamped to [0, 1]. A hard failure sets trust to 0.
    trust >= 0.7          -> accepted
    0.4 <= trust < 0.7    -> needs_review (held until another device corroborates)
    trust < 0.4           -> rejected
Every signal is stored with its penalty and a plain-language reason, so decisions are auditable.
These checks reduce abuse; they do not make the system unspoofable.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import imagehash
import numpy as np
from PIL import Image
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.integrity.burst import check_burst
from app.integrity.exif import read_exif
from app.integrity.screen import screen_score
from app.models import Device, Report, Ward
from app.pipeline.ingest import ReportInput
from app.pipeline.route import find_ward
from app.states import ReportState

ACCEPT_AT = 0.7
REVIEW_AT = 0.4

PHASH_MATCH = 6            # Hamming distance (of 64 bits) for "same photo"
SAME_PLACE_M = 30          # a matching photo within this distance, same device = resubmission
SCREEN_STRONG, SCREEN_MILD = 2.5, 2.0   # calibrated by tools/calibrate_screen.py
TRAVEL_MIN_DIST_M = 1000   # only judge speed over real distances
TRAVEL_MAX_MPS = 50        # 180 km/h
UPLOAD_MAX_AGE = timedelta(days=7)
EXIF_GPS_MISMATCH_M = 500


@dataclass
class Signal:
    name: str
    penalty: float
    detail: str
    hard: bool = False

    def as_dict(self) -> dict:
        return {"name": self.name, "penalty": round(self.penalty, 2), "detail": self.detail, "hard": self.hard}


@dataclass
class TrustResult:
    score: float
    state: str
    signals: list[Signal] = field(default_factory=list)
    phash: str | None = None
    screen: float | None = None

    @property
    def reject_reason(self) -> str | None:
        if self.state != ReportState.REJECTED:
            return None
        hard = [s.detail for s in self.signals if s.hard]
        return "; ".join(hard or [s.detail for s in self.signals if s.penalty > 0])

    def as_dict(self) -> dict:
        return {"score": round(self.score, 2), "signals": [s.as_dict() for s in self.signals],
                "screen_score": None if self.screen is None else round(self.screen, 2)}


def phash_hex(data: bytes) -> str:
    with Image.open(io.BytesIO(data)) as im:
        return str(imagehash.phash(im.convert("RGB")))


def distance_m(db: Session, a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(db.execute(text(
        "SELECT ST_Distance(ST_MakePoint(:alng, :alat)::geography, ST_MakePoint(:blng, :blat)::geography)"),
        {"alat": a[0], "alng": a[1], "blat": b[0], "blng": b[1]}).scalar())


def reuse_signal(db: Session, inp: ReportInput, hashes: list[str]) -> Signal | None:
    """Has any of these frames been submitted before? Compares 64-bit pHashes in SQL."""
    for h in hashes:
        row = db.execute(text("""
            SELECT r.device_id,
                   ST_Distance(r.location::geography, ST_MakePoint(:lng, :lat)::geography) AS dist,
                   bit_count(('x' || r.phash)::bit(64) # ('x' || :h)::bit(64)) AS ham
            FROM report r
            WHERE r.phash IS NOT NULL
              AND bit_count(('x' || r.phash)::bit(64) # ('x' || :h)::bit(64)) <= :max
            ORDER BY ham, r.received_at DESC LIMIT 1"""),
            {"h": h, "max": PHASH_MATCH, "lat": inp.lat, "lng": inp.lng}).first()
        if row is None:
            continue
        device, dist, ham = row
        if device == inp.device_id and dist <= SAME_PLACE_M:
            return Signal("duplicate_submission", 1.0, "this photo was already submitted from this device", hard=True)
        where = "another device" if device != inp.device_id else f"{dist:.0f} m away"
        return Signal("reused_photo", 1.0, f"same photo already used in a report from {where}", hard=True)
    return None


def gps_signals(db: Session, inp: ReportInput, now: datetime) -> list[Signal]:
    out = []
    if db.scalar(select(func.count()).select_from(Ward)) and find_ward(db, inp.lat, inp.lng) is None:
        out.append(Signal("outside_area", 1.0, "location is outside the GBA pilot area", hard=True))
    if inp.accuracy_m is None:
        out.append(Signal("gps_accuracy", 0.15, "GPS accuracy not reported"))
    elif inp.accuracy_m > 200:
        out.append(Signal("gps_accuracy", 0.5, f"very poor GPS accuracy (±{inp.accuracy_m:.0f} m)"))
    elif inp.accuracy_m > 50:
        out.append(Signal("gps_accuracy", 0.3, f"poor GPS accuracy (±{inp.accuracy_m:.0f} m)"))

    last = db.execute(
        select(Report.received_at, func.ST_Y(Report.location), func.ST_X(Report.location))
        .where(Report.device_id == inp.device_id).order_by(Report.received_at.desc()).limit(1)).first()
    if last:
        dist = distance_m(db, (last[1], last[2]), (inp.lat, inp.lng))
        seconds = max((now - last[0]).total_seconds(), 1.0)
        if dist > TRAVEL_MIN_DIST_M and dist / seconds > TRAVEL_MAX_MPS:
            out.append(Signal("impossible_travel", 0.5,
                              f"{dist / 1000:.1f} km from this device's last report {seconds:.0f} s ago"))
    return out


def capture_signals(inp: ReportInput, frames: list[np.ndarray], now: datetime) -> tuple[list[Signal], float]:
    out = []
    scores = [screen_score(f) for f in frames]
    screen = max(scores)
    if screen >= SCREEN_STRONG:
        out.append(Signal("screen_recapture", 0.5, f"looks like a photo of a screen (moire score {screen:.2f})"))
    elif screen >= SCREEN_MILD:
        out.append(Signal("screen_recapture", 0.25, f"possible photo of a screen (moire score {screen:.2f})"))

    if inp.capture_source == "camera":
        burst = check_burst(frames)
        if burst.identical:
            out.append(Signal("burst_identical", 0.35, "the live frames are identical (no camera motion or noise)"))
        elif burst.same_scene is False:
            out.append(Signal("burst_mismatch", 0.4, "the live frames do not show the same scene"))
    else:
        out.append(Signal("gallery_upload", 0.25, "uploaded photo: live capture cannot be verified"))
        exif = read_exif(inp.frames[0].data)
        if not exif.present:
            out.append(Signal("no_exif", 0.1, "uploaded photo has no camera metadata"))
        else:
            if exif.taken_at and now.replace(tzinfo=None) - exif.taken_at > UPLOAD_MAX_AGE:
                out.append(Signal("old_photo", 0.3, f"photo was taken on {exif.taken_at:%d %b %Y}"))
            if exif.lat is not None and exif.lng is not None:
                d = _haversine_m(exif.lat, exif.lng, inp.lat, inp.lng)
                if d > EXIF_GPS_MISMATCH_M:
                    out.append(Signal("exif_gps_mismatch", 0.5,
                                      f"photo's own GPS is {d / 1000:.1f} km from the reported location"))
    return out, screen


def device_signal(device: Device | None) -> Signal | None:
    if device and device.report_count >= 5 and device.rejected_count / device.report_count > 0.5:
        return Signal("device_history", 0.2, f"{device.rejected_count} of {device.report_count} earlier reports rejected")
    return None


def _haversine_m(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lng2 - lng1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return float(6_371_000 * 2 * np.arcsin(np.sqrt(a)))


def assess(db: Session, inp: ReportInput, frames: list[np.ndarray], device: Device | None,
           now: datetime | None = None) -> TrustResult:
    """Run every check. Call before this report is added to the session (history excludes it)."""
    now = now or datetime.now(timezone.utc)
    hashes = [phash_hex(f.data) for f in inp.frames]
    signals: list[Signal] = []
    if s := reuse_signal(db, inp, hashes):
        signals.append(s)
    signals += gps_signals(db, inp, now)
    cap, screen = capture_signals(inp, frames, now)
    signals += cap
    if s := device_signal(device):
        signals.append(s)

    if any(s.hard for s in signals):
        score = 0.0
    else:
        score = max(0.0, 1.0 - sum(s.penalty for s in signals))
    state = (ReportState.ACCEPTED if score >= ACCEPT_AT
             else ReportState.NEEDS_REVIEW if score >= REVIEW_AT else ReportState.REJECTED)
    return TrustResult(score, state, signals, hashes[0], screen)
