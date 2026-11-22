"""M6: repair verification by a later citizen photo at an issue marked "claimed fixed"."""

import cv2
import numpy as np
import pytest

from tests.conftest import burst, encode, jpeg_bytes, scene
from tests.test_cluster_route import BASE, seeded  # noqa: F401 - fixture re-used

AUTH = {"X-Authority-Token": "test-authority"}
POTHOLE = [(0.3, 0.5, 0.6, 0.8, 0.9)]


def report(client, frames=None, device="device-fix01", lat=BASE[0], lng=BASE[1]):
    frames = frames or burst()
    r = client.post("/api/reports", data={"lat": str(lat), "lng": str(lng), "accuracy_m": "5", "device_id": device},
                    files=[("frames", (f"f{i}.jpg", b, "image/jpeg")) for i, b in enumerate(frames)])
    assert r.status_code == 201, r.text
    return r.json()


def issue(client, issue_id):
    return client.get(f"/api/issues/{issue_id}").json()


@pytest.fixture
def claimed(seeded, fake_detector):  # noqa: F811
    """An issue reported with a pothole, then marked fixed by the authority."""
    fake_detector.boxes = POTHOLE
    iid = report(seeded, device="device-orig1")["issue_id"]
    r = seeded.post(f"/api/issues/{iid}/status", json={"action": "claim_fixed", "note": "patched"}, headers=AUTH)
    assert r.json()["status"] == "claimed_fixed"
    return seeded, iid


@pytest.fixture
def enforce(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "detection_mode", "enforce")


def test_pothole_still_there_reopens_as_falsely_closed(claimed, fake_detector):
    client, iid = claimed
    fake_detector.boxes = POTHOLE
    r = report(client, device="device-check")
    assert r["repair_check"]["outcome"] == "reopened"
    assert r["issue_id"] == iid
    i = issue(client, iid)
    assert i["status"] == "reopened" and i["report_count"] == 2
    assert i["due_at"] is not None and i["overdue"] is False
    assert "falsely closed" in i["events"][-1]["note"]


def test_clear_trusted_photo_without_pothole_verifies_fix_in_enforce_mode(claimed, fake_detector, enforce):
    client, iid = claimed
    fake_detector.boxes = []
    r = report(client, device="device-check")
    assert r["state"] == "no_damage"
    assert r["repair_check"]["outcome"] == "verified_fixed"
    assert issue(client, iid)["status"] == "verified_fixed"
    # The pothole is closed: a later report at the same spot starts a new issue.
    fake_detector.boxes = POTHOLE
    assert report(client, device="device-later")["issue_id"] != iid


def test_advisory_mode_never_auto_verifies(claimed, fake_detector):
    client, iid = claimed
    fake_detector.boxes = []
    r = report(client, device="device-check")
    assert r["repair_check"]["outcome"] == "inconclusive"
    assert "advisory mode" in r["repair_check"]["detail"]
    assert issue(client, iid)["status"] == "claimed_fixed"


def test_low_trust_photo_cannot_verify(claimed, fake_detector, enforce):
    client, iid = claimed
    fake_detector.boxes = []
    one = jpeg_bytes()
    r = report(client, [one, one, one], device="device-check")  # identical frames -> needs_review
    assert r["repair_check"]["outcome"] == "inconclusive"
    assert "trust too low" in r["repair_check"]["detail"]
    assert issue(client, iid)["status"] == "claimed_fixed"


@pytest.mark.parametrize("problem,make", [
    ("too dark", lambda img: (img * 0.12).astype(np.uint8)),
    ("too blurry", lambda img: cv2.GaussianBlur(img, (0, 0), 4)),
])
def test_dark_or_blurry_photo_cannot_verify(claimed, fake_detector, enforce, problem, make):
    client, iid = claimed
    fake_detector.boxes = []
    r = report(client, [encode(make(scene(300)))], device="device-check")
    assert r["repair_check"]["outcome"] == "inconclusive"
    assert problem in r["repair_check"]["detail"]
    assert issue(client, iid)["status"] == "claimed_fixed"


def test_rejected_photo_does_not_touch_the_claim(claimed, fake_detector, enforce):
    client, iid = claimed
    fake_detector.boxes = []
    frames = burst(seed=301)
    report(client, frames, device="device-a1111", lat=BASE[0] + 0.003)  # elsewhere, first use
    reused = report(client, frames, device="device-b2222")  # same photo, other device -> rejected
    assert reused["state"] == "rejected" and reused["repair_check"] is None
    assert issue(client, iid)["status"] == "claimed_fixed"


def test_reopened_issue_escalates_again_when_overdue(claimed, fake_detector):
    from datetime import datetime, timedelta, timezone

    from app.db import SessionLocal
    from app.models import Issue

    client, iid = claimed
    fake_detector.boxes = POTHOLE
    report(client, device="device-check")
    with SessionLocal() as db:
        db.get(Issue, iid).due_at = datetime.now(timezone.utc) - timedelta(hours=5)
        db.commit()
    out = client.post("/internal/escalate", headers={"X-Internal-Token": "test-internal"}).json()
    assert out["moved_up"] == 1
    assert issue(client, iid)["status"] == "escalated"
