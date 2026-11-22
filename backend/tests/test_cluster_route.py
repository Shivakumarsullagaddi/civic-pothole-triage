"""M3: duplicate merging within a GPS-aware radius, and routing to the ward office."""

import pytest

from tests.conftest import jpeg_bytes

M_PER_DEG_LAT = 110_600  # close enough at Bengaluru's latitude for test offsets
BASE = (12.975, 77.595)  # inside synthetic ward 1


def square(lng0, lat0, lng1, lat1):
    return {"type": "Polygon", "coordinates": [[[lng0, lat0], [lng1, lat0], [lng1, lat1], [lng0, lat1], [lng0, lat0]]]}


def ward(no, name, corp, zone, geom):
    return {"type": "Feature", "geometry": geom,
            "properties": {"ward_no": no, "ward_name": name, "ward_name_kn": None, "corporation": corp,
                           "corporation_kn": None, "zone": "Zone1", "zone_name": zone}}


TEST_WARDS = {"type": "FeatureCollection", "features": [
    ward(1, "Alpha", "Central", "Gandhinagara", square(77.590, 12.970, 77.600, 12.980)),
    ward(2, "Beta", "East", "Mahadevapura", square(77.600, 12.970, 77.610, 12.980)),
    # Ward numbers restart per corporation: East also has a ward 1.
    ward(1, "Gamma", "East", "Mahadevapura", square(77.610, 12.970, 77.620, 12.980)),
]}


@pytest.fixture
def seeded(db_client):
    from app.db import SessionLocal
    from app.seed import seed_gba

    with SessionLocal() as db:
        seed_gba(db, TEST_WARDS)
        seed_gba(db, TEST_WARDS)  # re-running must not duplicate anything
    return db_client


def north_of(base, metres):
    return base[0] + metres / M_PER_DEG_LAT, base[1]


def report(client, lat, lng, accuracy=5.0):
    r = client.post("/api/reports",
                    data={"lat": str(lat), "lng": str(lng), "accuracy_m": str(accuracy), "device_id": "device-12345"},
                    files=[("frames", ("f.jpg", jpeg_bytes(), "image/jpeg"))])
    assert r.status_code == 201, r.text
    return r.json()


def issue(client, issue_id):
    return client.get(f"/api/issues/{issue_id}").json()


def test_seed_is_idempotent(seeded):
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import Authority, Ward

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Ward)) == 3
        # 1 GBA + 2 corporations + 2 zones + 3 ward offices
        assert db.scalar(select(func.count()).select_from(Authority)) == 8


def test_new_issue_is_routed_to_ward_office(seeded):
    r = report(seeded, *BASE)
    i = issue(seeded, r["issue_id"])
    assert (i["ward_no"], i["ward_name"], i["corporation"]) == (1, "Alpha", "Central")
    assert i["authority_name"] == "Ward 1 Alpha office (Central)"
    assert "routed to Ward 1 Alpha office (Central)" in i["events"][0]["note"]


def test_same_ward_number_in_two_corporations(seeded):
    central = seeded.get("/api/wards/lookup", params={"lat": BASE[0], "lng": 77.595}).json()
    east = seeded.get("/api/wards/lookup", params={"lat": BASE[0], "lng": 77.615}).json()
    assert (central["ward_no"], central["name"], central["corporation"]) == (1, "Alpha", "Central")
    assert (east["ward_no"], east["name"], east["corporation"]) == (1, "Gamma", "East")


def test_nearby_report_merges_and_far_report_does_not(seeded, fake_detector):
    fake_detector.boxes = [(0.4, 0.4, 0.5, 0.5, 0.9)]  # 1% -> low
    first = report(seeded, *BASE)
    fake_detector.boxes = [(0.1, 0.1, 0.6, 0.6, 0.9)]  # 25% -> critical
    near = report(seeded, *north_of(BASE, 10))
    far = report(seeded, *north_of(BASE, 40))

    assert near["issue_id"] == first["issue_id"]
    assert far["issue_id"] != first["issue_id"]
    merged = issue(seeded, first["issue_id"])
    assert merged["report_count"] == 2
    assert merged["severity"] == "critical"  # worst severity wins
    assert [e["type"] for e in merged["events"]] == ["created", "report_added"]


def test_radius_follows_gps_accuracy(seeded):
    first = report(seeded, *BASE)
    precise = report(seeded, *north_of(BASE, 22), accuracy=5)    # radius 15 m -> separate
    vague = report(seeded, *north_of(BASE, -22), accuracy=25)    # radius 25 m -> merges
    assert precise["issue_id"] != first["issue_id"]
    assert vague["issue_id"] == first["issue_id"]


def test_closed_issue_is_not_reused(seeded):
    from app.db import SessionLocal
    from app.models import Issue

    first = report(seeded, *BASE)
    with SessionLocal() as db:
        db.get(Issue, first["issue_id"]).status = "verified_fixed"
        db.commit()
    again = report(seeded, *BASE)
    assert again["issue_id"] != first["issue_id"]


def test_unrouted_issue_is_routed_when_next_report_arrives(db_client):
    from app.db import SessionLocal
    from app.seed import seed_gba

    first = report(db_client, *BASE)  # no wards loaded yet
    assert issue(db_client, first["issue_id"])["authority_name"] is None
    with SessionLocal() as db:
        seed_gba(db, TEST_WARDS)
    second = report(db_client, *north_of(BASE, 5))
    assert second["issue_id"] == first["issue_id"]
    assert second["authority_name"] == "Ward 1 Alpha office (Central)"
    assert [e["type"] for e in issue(db_client, first["issue_id"])["events"]] == ["created", "report_added", "routed"]


def test_outside_pilot_area_is_rejected_once_wards_exist(seeded):
    r = report(seeded, 13.5, 77.0)
    assert r["state"] == "rejected"
    assert r["issue_id"] is None
    assert "outside the GBA pilot area" in r["reject_reason"]


def test_ward_lookup_and_boundaries(seeded):
    found = seeded.get("/api/wards/lookup", params={"lat": BASE[0], "lng": 77.605}).json()
    assert found["ward_no"] == 2 and found["corporation"] == "East"
    assert found["escalation_chain"] == [
        "Ward 2 Beta office (East)", "Mahadevapura Zone (East Corporation)",
        "Bengaluru East City Corporation", "Greater Bengaluru Authority"]
    assert seeded.get("/api/wards/lookup", params={"lat": 13.5, "lng": 77.0}).status_code == 404

    fc = seeded.get("/api/wards.geojson").json()
    assert [(f["properties"]["corporation"], f["properties"]["ward_no"]) for f in fc["features"]] == [
        ("Central", 1), ("East", 1), ("East", 2)]
    assert fc["features"][0]["geometry"]["type"] in {"Polygon", "MultiPolygon"}
