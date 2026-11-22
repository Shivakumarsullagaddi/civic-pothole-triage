"""M4: anti-spoofing checks, trust score, states and corroboration."""

import io
import random
from datetime import datetime, timedelta

import cv2
import numpy as np
import pytest
from PIL import Image

from tests.conftest import burst, encode, jpeg_bytes, scene

HERE = {"lat": "12.9716", "lng": "77.5946", "accuracy_m": "6"}


def send(client, frames, device="device-aaaa1", source="camera", **fields):
    data = {**HERE, "device_id": device, "capture_source": source, **fields}
    files = [("frames", (f"f{i}.jpg", b, "image/jpeg")) for i, b in enumerate(frames)]
    r = client.post("/api/reports", data=data, files=files)
    assert r.status_code == 201, r.text
    return r.json()


def signal_names(report):
    return [s["name"] for s in report["trust_signals"]["signals"]]


def dms(v: float) -> tuple[float, float, float]:
    v = abs(v)
    d = int(v)
    m = int((v - d) * 60)
    return (float(d), float(m), round((v - d - m / 60) * 3600, 2))


def with_exif(img: np.ndarray, taken: datetime | None = None, gps: tuple[float, float] | None = None) -> bytes:
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    exif = Image.Exif()
    exif[0x0110] = "TestPhone"  # camera model, so EXIF is present even without date or GPS
    if taken:
        exif.get_ifd(0x8769)[36867] = taken.strftime("%Y:%m:%d %H:%M:%S")
    if gps:
        g = exif.get_ifd(0x8825)
        g[1], g[2] = ("N" if gps[0] >= 0 else "S"), dms(gps[0])
        g[3], g[4] = ("E" if gps[1] >= 0 else "W"), dms(gps[1])
    buf = io.BytesIO()
    pil.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_clean_live_burst_is_accepted_with_full_trust(db_client):
    r = send(db_client, burst())
    assert r["state"] == "accepted"
    assert r["trust_score"] == 1.0
    assert signal_names(r) == []


def test_same_photo_from_another_device_is_rejected(db_client):
    frames = burst(seed=77)
    assert send(db_client, frames, device="device-first")["state"] == "accepted"
    again = send(db_client, frames, device="device-second")
    assert again["state"] == "rejected"
    assert "reused_photo" in signal_names(again)
    assert "another device" in again["reject_reason"]
    assert again["issue_id"] is None


def test_resubmitting_same_photo_from_same_device_is_rejected(db_client):
    frames = burst(seed=78)
    send(db_client, frames)
    again = send(db_client, frames)
    assert again["state"] == "rejected"
    assert "duplicate_submission" in signal_names(again)


def test_recompressed_smaller_copy_still_counts_as_reuse(db_client):
    img = scene(79)
    send(db_client, [encode(img)], device="device-first")
    smaller = cv2.resize(img, (480, 360))
    copy = cv2.imencode(".jpg", smaller, [cv2.IMWRITE_JPEG_QUALITY, 60])[1].tobytes()
    assert send(db_client, [copy], device="device-second")["state"] == "rejected"


def test_identical_live_frames_lower_trust_to_review(db_client):
    one = jpeg_bytes()
    r = send(db_client, [one, one, one])
    assert "burst_identical" in signal_names(r)
    assert r["state"] == "needs_review"
    assert r["issue_status"] == "unverified"


def test_frames_from_different_scenes_lower_trust(db_client):
    r = send(db_client, [jpeg_bytes(), jpeg_bytes(), jpeg_bytes()])
    assert "burst_mismatch" in signal_names(r)
    assert r["state"] == "needs_review"


def test_screen_recapture_is_penalised(db_client):
    from tools.calibrate_screen import simulate_screen_photo

    shot = simulate_screen_photo(scene(80), random.Random(1))
    r = send(db_client, [encode(shot)])
    assert "screen_recapture" in signal_names(r)
    assert r["trust_signals"]["screen_score"] >= 2.0
    assert r["trust_score"] <= 0.75


def test_gallery_upload_without_exif_needs_review(db_client):
    r = send(db_client, [jpeg_bytes()], source="upload")
    assert set(signal_names(r)) == {"gallery_upload", "no_exif"}
    assert r["trust_score"] == pytest.approx(0.65)
    assert r["state"] == "needs_review"


def test_old_upload_far_from_reported_place_is_rejected(db_client):
    photo = with_exif(scene(81), taken=datetime.now() - timedelta(days=60), gps=(28.61, 77.21))  # Delhi
    r = send(db_client, [photo], source="upload")
    assert {"gallery_upload", "old_photo", "exif_gps_mismatch"} <= set(signal_names(r))
    assert r["state"] == "rejected"


def test_recent_upload_with_matching_gps_is_accepted(db_client):
    photo = with_exif(scene(82), taken=datetime.now() - timedelta(hours=1), gps=(12.9716, 77.5946))
    r = send(db_client, [photo], source="upload")
    assert signal_names(r) == ["gallery_upload"]
    assert r["state"] == "accepted"


def test_poor_gps_accuracy_is_penalised(db_client):
    r = send(db_client, burst(), accuracy_m="120")
    assert "gps_accuracy" in signal_names(r)
    assert r["trust_score"] == pytest.approx(0.7)


def test_impossible_travel_is_penalised(db_client):
    send(db_client, burst(), device="device-fast1")
    r = send(db_client, burst(), device="device-fast1", lat="13.3409", lng="77.1010")  # ~65 km away
    assert "impossible_travel" in signal_names(r)
    assert r["trust_score"] == pytest.approx(0.5)


def test_another_device_corroborates_a_held_report(db_client):
    one = jpeg_bytes()
    held = send(db_client, [one, one, one], device="device-held1")
    assert held["state"] == "needs_review" and held["issue_status"] == "unverified"

    confirm = send(db_client, [jpeg_bytes(), jpeg_bytes(), jpeg_bytes()], device="device-other")
    assert confirm["state"] == "accepted"  # its own needs_review upgraded by corroboration
    assert confirm["issue_id"] == held["issue_id"]
    assert confirm["issue_status"] == "open"
    first = db_client.get(f"/api/reports/{held['id']}").json()
    assert first["state"] == "accepted"
    assert "corroborated" in first["trust_signals"]
    events = db_client.get(f"/api/issues/{held['issue_id']}").json()["events"]
    assert events[-1]["note"] == "corroborated by another device"


def test_same_device_cannot_corroborate_itself(db_client):
    one, two = jpeg_bytes(), jpeg_bytes()
    first = send(db_client, [one, one, one], device="device-solo1")
    second = send(db_client, [two, two, two], device="device-solo1")
    assert second["issue_id"] == first["issue_id"]
    assert second["state"] == "needs_review" and second["issue_status"] == "unverified"


def test_device_daily_limit_returns_429(db_client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "device_daily_limit", 2)
    send(db_client, burst(), device="device-limit")
    send(db_client, burst(), device="device-limit", lat="12.9800")
    r = db_client.post("/api/reports", data={**HERE, "device_id": "device-limit"},
                       files=[("frames", ("f.jpg", jpeg_bytes(), "image/jpeg"))])
    assert r.status_code == 429
    assert "per device per day" in r.json()["detail"]
