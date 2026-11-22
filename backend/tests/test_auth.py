"""Staff accounts: login, session cookie, roles, admin account management."""

import pytest

from tests.conftest import burst


@pytest.fixture
def staff(db_client):
    from app import auth
    from app.auth import hash_password
    from app.db import SessionLocal

    auth._attempts.clear()  # failed-login throttle is per process
    from app.models import User

    with SessionLocal() as db:
        db.add_all([
            User(email="admin@test.org", name="Admin", password_hash=hash_password("admin-pass-1"), role="admin"),
            User(email="officer@test.org", name="Officer", password_hash=hash_password("officer-pass-1"), role="officer"),
            User(email="gone@test.org", name="Gone", password_hash=hash_password("gone-pass-12"), role="officer",
                 active=False),
        ])
        db.commit()
    return db_client


def login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_login_sets_cookie_and_me_returns_user(staff):
    r = login(staff, "Officer@Test.org", "officer-pass-1")
    assert r.status_code == 200 and r.json()["role"] == "officer"
    assert "pt_session" in r.cookies
    assert staff.get("/api/auth/me").json()["email"] == "officer@test.org"
    staff.post("/api/auth/logout")
    staff.cookies.clear()
    assert staff.get("/api/auth/me").json() is None


@pytest.mark.parametrize("email,password", [("officer@test.org", "wrong-pass"), ("nobody@test.org", "x" * 10),
                                            ("gone@test.org", "gone-pass-12")])
def test_bad_login_is_rejected(staff, email, password):
    assert login(staff, email, password).status_code == 401


def test_repeated_failures_are_throttled(staff):
    for _ in range(5):
        login(staff, "admin@test.org", "nope-nope")
    assert login(staff, "admin@test.org", "admin-pass-1").status_code == 429


def test_officer_can_act_but_not_admin(staff):
    assert staff.get("/api/authority/issues").status_code == 401
    login(staff, "officer@test.org", "officer-pass-1")
    r = staff.post("/api/reports", data={"lat": "12.97", "lng": "77.59", "accuracy_m": "5", "device_id": "device-auth1"},
                   files=[("frames", (f"f{i}.jpg", b, "image/jpeg")) for i, b in enumerate(burst())])
    iid = r.json()["issue_id"]
    assert staff.get("/api/authority/issues").status_code == 200
    act = staff.post(f"/api/issues/{iid}/status", json={"action": "acknowledge", "note": "on it"})
    assert act.status_code == 200
    assert act.json()["events"][-1]["actor"] == "officer@test.org"
    assert staff.get("/api/admin/users").status_code == 403
    assert staff.post("/api/admin/escalate").status_code == 403


def test_admin_manages_accounts(staff):
    login(staff, "admin@test.org", "admin-pass-1")
    r = staff.post("/api/admin/users", json={"email": "New@Test.org", "name": "New", "password": "new-pass-123"})
    assert r.status_code == 201 and r.json()["email"] == "new@test.org"
    assert staff.post("/api/admin/users", json={"email": "new@test.org", "name": "x", "password": "another-123"}).status_code == 409
    assert staff.post("/api/admin/users", json={"email": "short@test.org", "name": "x", "password": "short"}).status_code == 422
    uid = r.json()["id"]
    assert staff.patch(f"/api/admin/users/{uid}", json={"active": False}).json()["active"] is False
    me = staff.get("/api/auth/me").json()
    assert staff.patch(f"/api/admin/users/{me['id']}", json={"active": False}).status_code == 409
    assert staff.post("/api/admin/escalate").status_code == 200
    staff.cookies.clear()
    assert login(staff, "new@test.org", "new-pass-123").status_code == 401  # deactivated


def test_admin_deletes_photo_then_report(staff):
    from pathlib import Path

    from app.config import get_settings

    r = staff.post("/api/reports", data={"lat": "12.97", "lng": "77.59", "accuracy_m": "5", "device_id": "device-del01"},
                   files=[("frames", (f"f{i}.jpg", b, "image/jpeg")) for i, b in enumerate(burst())]).json()
    root = get_settings().resolve(get_settings().photo_dir)
    folder = Path(root, "reports", r["id"])
    assert len(list(folder.glob("frame_*"))) == 3

    login(staff, "officer@test.org", "officer-pass-1")
    assert staff.delete(f"/api/admin/reports/{r['id']}/frames/0").status_code == 403  # officers cannot delete
    staff.cookies.clear()
    login(staff, "admin@test.org", "admin-pass-1")

    one = staff.delete(f"/api/admin/reports/{r['id']}/frames/1").json()
    assert one["remaining_photos"] == 2 and len(list(folder.glob("frame_*"))) == 2
    detail = staff.get(f"/api/authority/reports/{r['id']}").json()
    assert detail["frame_count"] == 2 and [f["frame"] for f in detail["frames"]] == [0, 1]

    gone = staff.delete(f"/api/admin/reports/{r['id']}").json()
    assert gone["issue_deleted"] is True  # it was the issue's only report
    assert not folder.exists()
    assert staff.get(f"/api/authority/reports/{r['id']}").status_code == 404
    assert staff.get(f"/api/issues/{r['issue_id']}").status_code == 404
