"""M5: SLA deadlines, authority actions, token protection, photos, escalation up the chain."""

from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import burst, jpeg_bytes
from tests.test_cluster_route import BASE, seeded  # noqa: F401 - fixture re-used

AUTH = {"X-Authority-Token": "test-authority"}
INTERNAL = {"X-Internal-Token": "test-internal"}


def report(client, frames=None, device="device-life1", lat=BASE[0], lng=BASE[1]):
    frames = frames or burst()
    r = client.post("/api/reports", data={"lat": str(lat), "lng": str(lng), "accuracy_m": "5", "device_id": device},
                    files=[("frames", (f"f{i}.jpg", b, "image/jpeg")) for i, b in enumerate(frames)])
    assert r.status_code == 201, r.text
    return r.json()


def issue(client, issue_id):
    return client.get(f"/api/issues/{issue_id}").json()


def act(client, issue_id, action, note=None, headers=AUTH):
    return client.post(f"/api/issues/{issue_id}/status", json={"action": action, "note": note}, headers=headers)


def make_overdue(issue_id, days=1):
    from app.db import SessionLocal
    from app.models import Issue

    with SessionLocal() as db:
        db.get(Issue, issue_id).due_at = datetime.now(timezone.utc) - timedelta(days=days)
        db.commit()


def hours_until(ts: str) -> float:
    return (datetime.fromisoformat(ts) - datetime.now(timezone.utc)).total_seconds() / 3600


def test_due_date_follows_severity(seeded, fake_detector):  # noqa: F811
    fake_detector.boxes = [(0.1, 0.1, 0.6, 0.6, 0.9)]  # critical -> 2 days
    i = issue(seeded, report(seeded)["issue_id"])
    assert i["severity"] == "critical"
    assert 47 < hours_until(i["due_at"]) <= 48
    assert i["overdue"] is False


def test_unverified_issue_has_no_deadline_until_corroborated(seeded):  # noqa: F811
    one = jpeg_bytes()
    held = report(seeded, [one, one, one], device="device-held2")
    assert issue(seeded, held["issue_id"])["due_at"] is None
    report(seeded, [jpeg_bytes(), jpeg_bytes(), jpeg_bytes()], device="device-other2")
    i = issue(seeded, held["issue_id"])
    assert i["status"] == "open" and i["due_at"] is not None


def test_worse_severity_brings_deadline_forward(seeded, fake_detector):  # noqa: F811
    fake_detector.boxes = [(0.4, 0.4, 0.5, 0.5, 0.9)]  # low -> 30 days
    first = report(seeded)
    assert hours_until(issue(seeded, first["issue_id"])["due_at"]) > 24 * 29
    fake_detector.boxes = [(0.1, 0.1, 0.6, 0.6, 0.9)]  # critical -> 2 days
    report(seeded, device="device-life2")
    assert hours_until(issue(seeded, first["issue_id"])["due_at"]) <= 48


def test_authority_endpoints_need_the_token(seeded):  # noqa: F811
    r = report(seeded)
    assert act(seeded, r["issue_id"], "acknowledge", headers={}).status_code == 401
    assert act(seeded, r["issue_id"], "acknowledge", headers={"X-Authority-Token": "wrong"}).status_code == 401
    assert seeded.get("/api/authority/issues").status_code == 401
    assert seeded.post("/internal/escalate").status_code == 401


def test_authority_actions_follow_the_lifecycle(seeded):  # noqa: F811
    iid = report(seeded)["issue_id"]
    ok = act(seeded, iid, "acknowledge", "crew assigned")
    assert ok.status_code == 200 and ok.json()["status"] == "acknowledged"
    assert act(seeded, iid, "acknowledge").status_code == 409  # already acknowledged
    fixed = act(seeded, iid, "claim_fixed", "patched")
    assert fixed.json()["status"] == "claimed_fixed"
    assert act(seeded, iid, "claim_fixed").status_code == 409
    events = issue(seeded, iid)["events"]
    assert [(e["from_status"], e["to_status"], e["note"]) for e in events if e["type"] == "status_changed"] == [
        ("open", "acknowledged", "crew assigned"), ("acknowledged", "claimed_fixed", "patched")]
    assert issue(seeded, iid)["overdue"] is False  # clock stops once claimed fixed


def test_dismiss_needs_a_note(seeded):  # noqa: F811
    one = jpeg_bytes()
    iid = report(seeded, [one, one, one], device="device-fake1")["issue_id"]  # unverified
    bad = act(seeded, iid, "dismiss")
    assert bad.status_code == 409 and "note" in bad.json()["detail"]
    assert act(seeded, iid, "dismiss", "photo of a poster").json()["status"] == "dismissed"


def test_work_list_and_private_photos(seeded):  # noqa: F811
    r = report(seeded)
    listed = seeded.get("/api/authority/issues", headers=AUTH).json()
    assert [i["id"] for i in listed] == [r["issue_id"]]
    item = seeded.get(f"/api/authority/issues/{r['issue_id']}", headers=AUTH).json()
    [rep] = item["reports"]
    assert rep["frame_count"] == 3 and len(rep["device_hint"]) == 4
    assert [f["frame"] for f in rep["frames"]] == [0, 1, 2]  # per-photo boxes for the overlay
    assert rep["frames"][0]["width"] == 640 and rep["best_frame"] in (0, 1, 2)
    photo = seeded.get(f"/api/authority/reports/{rep['id']}/frames/0", headers=AUTH)
    assert photo.status_code == 200 and photo.headers["content-type"] == "image/jpeg"
    assert photo.content[:2] == b"\xff\xd8"
    assert seeded.get(f"/api/authority/reports/{rep['id']}/frames/0").status_code == 401
    assert seeded.get(f"/api/authority/reports/{rep['id']}/frames/9", headers=AUTH).status_code == 404


def test_escalation_climbs_the_chain_then_stops_at_gba(seeded):  # noqa: F811
    iid = report(seeded)["issue_id"]
    chain = ["Gandhinagara Zone (Central Corporation)", "Bengaluru Central City Corporation",
             "Greater Bengaluru Authority"]
    for level, expected in enumerate(chain, start=1):
        make_overdue(iid)
        result = seeded.post("/internal/escalate", headers=INTERNAL).json()
        assert result["moved_up"] == 1
        i = issue(seeded, iid)
        assert (i["status"], i["escalation_level"], i["authority_name"]) == ("escalated", level, expected)
        assert i["overdue"] is False and hours_until(i["due_at"]) > 24
    make_overdue(iid)
    top = seeded.post("/internal/escalate", headers=INTERNAL).json()
    assert top["at_top"] == 1 and top["moved_up"] == 0
    notes = [e["note"] for e in issue(seeded, iid)["events"] if e["type"] == "escalated"]
    assert len(notes) == 4
    assert "moved from Ward 1 Alpha office (Central) to Gandhinagara Zone" in notes[0]
    assert "already at the top" in notes[-1]


def test_overdue_flag_and_no_escalation_when_on_time(seeded):  # noqa: F811
    iid = report(seeded)["issue_id"]
    assert seeded.post("/internal/escalate", headers=INTERNAL).json()["overdue"] == 0
    make_overdue(iid, days=2)
    assert issue(seeded, iid)["overdue"] is True


@pytest.mark.parametrize("status", ["claimed_fixed", "dismissed", "verified_fixed"])
def test_closed_or_claimed_issues_do_not_escalate(seeded, status):  # noqa: F811
    from app.db import SessionLocal
    from app.models import Issue

    iid = report(seeded)["issue_id"]
    with SessionLocal() as db:
        i = db.get(Issue, iid)
        i.status, i.due_at = status, datetime.now(timezone.utc) - timedelta(days=3)
        db.commit()
    assert seeded.post("/internal/escalate", headers=INTERNAL).json()["overdue"] == 0


def test_issue_rows_carry_latest_report_and_activity(seeded):  # noqa: F811
    first = report(seeded, device="device-row01")
    second = report(seeded, device="device-row02", lat=BASE[0] + 0.00005)  # merges
    [row] = seeded.get("/api/authority/issues", headers=AUTH).json()
    assert row["id"] == first["issue_id"] == second["issue_id"]
    assert row["latest_report_id"] == second["id"]
    assert row["last_activity_at"] is not None


def test_recent_reports_newest_first_and_detail(seeded):  # noqa: F811
    a = report(seeded, device="device-rec01")
    one = jpeg_bytes()
    b = report(seeded, [one, one, one], device="device-rec02", lat=BASE[0] + 0.001)  # held
    rows = seeded.get("/api/authority/reports", headers=AUTH).json()
    assert [r["id"] for r in rows[:2]] == [b["id"], a["id"]]
    assert rows[0]["state"] == "needs_review" and rows[0]["ward_name"] == "Alpha"
    held = seeded.get("/api/authority/reports", params={"state": "needs_review"}, headers=AUTH).json()
    assert [r["id"] for r in held] == [b["id"]]
    detail = seeded.get(f"/api/authority/reports/{a['id']}", headers=AUTH).json()
    assert detail["issue_id"] == a["issue_id"] and detail["authority_name"].startswith("Ward 1 Alpha")
    assert len(detail["frames"]) == 3 and detail["lat"] == pytest.approx(BASE[0])
    assert seeded.get("/api/authority/reports", headers={}).status_code == 401
    assert seeded.get("/api/authority/reports/nope", headers=AUTH).status_code == 404
