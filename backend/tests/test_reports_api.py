from pathlib import Path

from app.config import get_settings
from tests.conftest import burst

BENGALURU = {"lat": "12.9716", "lng": "77.5946"}


def post_report(client, n_frames=3, **fields):
    data = {**BENGALURU, "device_id": "device-12345", "accuracy_m": "6.5", **fields}
    files = [("frames", (f"f{i}.jpg", data, "image/jpeg")) for i, data in enumerate(burst(n_frames))]
    return client.post("/api/reports", data=data, files=files)


def test_report_creates_issue_and_appears_on_map(db_client):
    r = post_report(db_client)
    assert r.status_code == 201, r.text
    report = r.json()
    assert report["state"] == "accepted"
    assert report["frame_count"] == 3
    assert report["capture_source"] == "camera"
    assert report["issue_status"] == "open"
    assert abs(report["lat"] - 12.9716) < 1e-9 and abs(report["lng"] - 77.5946) < 1e-9

    settings = get_settings()
    photo_root = settings.resolve(settings.photo_dir)
    assert len(list(Path(photo_root, "reports", report["id"]).glob("frame_*.jpg"))) == 3

    fc = db_client.get("/api/issues.geojson").json()
    assert fc["type"] == "FeatureCollection"
    [feature] = fc["features"]
    assert feature["id"] == report["issue_id"]
    assert feature["geometry"]["coordinates"] == [77.5946, 12.9716]
    assert feature["properties"]["status"] == "open"

    issue = db_client.get(f"/api/issues/{report['issue_id']}").json()
    assert issue["report_count"] == 1
    assert [e["type"] for e in issue["events"]] == ["created"]

    again = db_client.get(f"/api/reports/{report['id']}").json()
    assert again["issue_id"] == report["issue_id"]


def test_bbox_and_status_filters(db_client):
    post_report(db_client)
    inside = db_client.get("/api/issues.geojson", params={"bbox": "77.5,12.9,77.7,13.0"}).json()
    outside = db_client.get("/api/issues.geojson", params={"bbox": "72.8,18.9,72.9,19.1"}).json()
    fixed = db_client.get("/api/issues.geojson", params={"status": "verified_fixed"}).json()
    assert len(inside["features"]) == 1
    assert outside["features"] == []
    assert fixed["features"] == []
    assert db_client.get("/api/issues.geojson", params={"bbox": "1,2,3"}).status_code == 422


def test_bad_input_returns_422_and_unknown_ids_404(db_client):
    bad = db_client.post(
        "/api/reports",
        data={**BENGALURU, "device_id": "device-12345"},
        files=[("frames", ("x.jpg", b"not an image", "image/jpeg"))],
    )
    assert bad.status_code == 422
    assert "not a readable image" in bad.json()["detail"]
    assert db_client.get("/api/reports/nope").status_code == 404
    assert db_client.get("/api/issues/nope").status_code == 404


def test_detection_sets_severity_and_is_stored(db_client, fake_detector):
    fake_detector.boxes = [(0.2, 0.5, 0.6, 0.9, 0.85)]  # 16% of the frame -> critical
    report = post_report(db_client).json()
    assert report["state"] == "accepted"
    assert report["severity"] == "critical"
    det = report["detections"]
    assert det["available"] and det["model"] == "fake.onnx"
    assert len(det["frames"]) == 3 and det["frames"][0]["boxes"][0]["score"] == 0.85
    issue = db_client.get(f"/api/issues/{report['issue_id']}").json()
    assert issue["severity"] == "critical"


def test_no_pothole_in_enforce_mode_creates_no_issue(db_client, fake_detector, monkeypatch):
    monkeypatch.setattr(get_settings(), "detection_mode", "enforce")
    fake_detector.boxes = []
    report = post_report(db_client).json()
    assert report["state"] == "no_damage"
    assert report["issue_id"] is None
    assert db_client.get("/api/issues.geojson").json()["features"] == []


def test_no_pothole_in_advisory_mode_still_creates_issue(db_client, fake_detector):
    fake_detector.boxes = []
    report = post_report(db_client).json()
    assert report["state"] == "accepted"
    assert report["severity"] is None
    assert report["issue_id"] is not None
