"""Three-way detection decision in enforce mode: confident / uncertain / none."""

import pytest

from tests.conftest import burst

HERE = {"lat": "12.9716", "lng": "77.5946", "accuracy_m": "6"}


@pytest.fixture
def enforce(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "detection_mode", "enforce")
    monkeypatch.setattr(get_settings(), "accept_conf", 0.45)


def send(client, device="device-conf1", **fields):
    r = client.post("/api/reports", data={**HERE, "device_id": device, **fields},
                    files=[("frames", (f"f{i}.jpg", b, "image/jpeg")) for i, b in enumerate(burst())])
    assert r.status_code == 201, r.text
    return r.json()


def names(report):
    return [s["name"] for s in report["trust_signals"]["signals"]]


def test_confident_pothole_is_accepted(db_client, fake_detector, enforce):
    fake_detector.boxes = [(0.3, 0.5, 0.6, 0.8, 0.77)]
    r = send(db_client)
    assert r["state"] == "accepted" and r["issue_status"] == "open"
    assert r["detections"]["confident"] is True


def test_uncertain_detection_is_held_not_accepted(db_client, fake_detector, enforce):
    fake_detector.boxes = [(0.45, 0.6, 0.5, 0.7, 0.40)]  # e.g. a lane-marking dash at 40%
    r = send(db_client)
    assert r["state"] == "needs_review"
    assert r["issue_status"] == "unverified"
    assert "uncertain_detection" in names(r)
    assert "not clearly visible" in r["trust_signals"]["signals"][-1]["detail"]


def test_no_box_is_not_accepted(db_client, fake_detector, enforce):
    fake_detector.boxes = []
    r = send(db_client)
    assert r["state"] == "no_damage" and r["issue_id"] is None


def test_two_independent_uncertain_reports_confirm_each_other(db_client, fake_detector, enforce):
    fake_detector.boxes = [(0.45, 0.6, 0.5, 0.7, 0.30)]
    first = send(db_client, device="device-unc01")
    second = send(db_client, device="device-unc02")
    assert second["issue_id"] == first["issue_id"]
    assert second["state"] == "accepted" and second["issue_status"] == "open"


def test_uncertain_box_cannot_reopen_a_fixed_pothole(db_client, fake_detector, enforce):
    fake_detector.boxes = [(0.3, 0.5, 0.6, 0.8, 0.9)]
    iid = send(db_client, device="device-fixa1")["issue_id"]
    db_client.post(f"/api/issues/{iid}/status", json={"action": "claim_fixed"},
                   headers={"X-Authority-Token": "test-authority"})
    fake_detector.boxes = [(0.45, 0.6, 0.5, 0.7, 0.25)]
    r = send(db_client, device="device-fixb1")
    assert r["repair_check"]["outcome"] == "inconclusive"
    assert db_client.get(f"/api/issues/{iid}").json()["status"] == "claimed_fixed"


def test_one_lucky_frame_is_not_enough(db_client, fake_detector, enforce):
    dash = (0.45, 0.6, 0.5, 0.7)
    fake_detector.per_frame = [[(*dash, 0.46)], [(*dash, 0.29)], [(*dash, 0.31)]]  # the lane-marking photo
    r = send(db_client)
    assert r["detections"]["burst_score"] == pytest.approx(0.31)
    assert r["state"] == "needs_review" and r["issue_status"] == "unverified"


def test_consistent_frames_are_confident(db_client, fake_detector, enforce):
    hole = (0.3, 0.5, 0.6, 0.8)
    fake_detector.per_frame = [[(*hole, 0.69)], [(*hole, 0.69)], [(*hole, 0.71)]]
    r = send(db_client)
    assert r["detections"]["burst_score"] == pytest.approx(0.69)
    assert r["state"] == "accepted"
