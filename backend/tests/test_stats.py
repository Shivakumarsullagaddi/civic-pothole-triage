"""M7: dashboard numbers."""

from datetime import datetime, timedelta, timezone

from tests.conftest import burst, jpeg_bytes
from tests.test_cluster_route import BASE, seeded  # noqa: F401 - fixture re-used

AUTH = {"X-Authority-Token": "test-authority"}


def report(client, frames, device, lat=BASE[0], lng=BASE[1]):
    r = client.post("/api/reports", data={"lat": str(lat), "lng": str(lng), "accuracy_m": "5", "device_id": device},
                    files=[("frames", (f"f{i}.jpg", b, "image/jpeg")) for i, b in enumerate(frames)])
    assert r.status_code == 201, r.text
    return r.json()


def test_empty_stats(db_client):
    s = db_client.get("/api/stats").json()
    assert s["reports_total"] == 0 and s["issues_total"] == 0
    assert s["median_days_to_verified_fix"] is None
    assert s["by_corporation"] == [] and s["top_wards"] == []


def test_stats_count_issues_fakes_and_overdue(seeded, monkeypatch):  # noqa: F811
    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import Issue

    a = report(seeded, burst(), "device-st001")                         # open, ward 1 Central
    report(seeded, burst(), "device-st002", lng=77.605)                 # open, ward 2 East
    frames = burst(seed=900)
    report(seeded, frames, "device-st003", lat=BASE[0] + 0.002)         # open, ward 1
    report(seeded, frames, "device-st004")                              # reused photo -> rejected
    one = jpeg_bytes()
    report(seeded, [one, one, one], "device-st005", lng=77.615)         # held -> unverified (East ward 1)

    with SessionLocal() as db:
        db.get(Issue, a["issue_id"]).due_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.commit()

    s = seeded.get("/api/stats").json()
    assert s["reports_total"] == 5
    assert s["fakes_blocked"] == 1 and s["held_for_confirmation"] == 1
    assert s["open_issues"] == 3 and s["overdue_issues"] == 1
    reasons = {r["key"]: r["count"] for r in s["blocked_reasons"]}
    assert reasons["Photo reused from another report"] == 1
    assert reasons["Live frames identical"] == 1
    corp = {c["corporation"]: c for c in s["by_corporation"]}
    assert (corp["Central"]["open"], corp["Central"]["overdue"]) == (2, 1)
    assert (corp["East"]["open"], corp["East"]["overdue"]) == (1, 0)
    top = s["top_wards"][0]
    assert (top["corporation"], top["ward_no"], top["open"], top["overdue"]) == ("Central", 1, 2, 1)
    assert "device" not in str(s)  # no device ids in public stats


def test_median_days_to_verified_fix(seeded, fake_detector, monkeypatch):  # noqa: F811
    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import Issue

    fake_detector.boxes = [(0.3, 0.5, 0.6, 0.8, 0.9)]
    iid = report(seeded, burst(), "device-md001")["issue_id"]
    with SessionLocal() as db:
        db.get(Issue, iid).opened_at = datetime.now(timezone.utc) - timedelta(days=4)
        db.commit()
    seeded.post(f"/api/issues/{iid}/status", json={"action": "claim_fixed"}, headers=AUTH)
    monkeypatch.setattr(get_settings(), "detection_mode", "enforce")
    fake_detector.boxes = []
    assert report(seeded, burst(), "device-md002")["repair_check"]["outcome"] == "verified_fixed"
    s = seeded.get("/api/stats").json()
    assert s["verified_fixed"] == 1
    assert 3.9 <= s["median_days_to_verified_fix"] <= 4.1
