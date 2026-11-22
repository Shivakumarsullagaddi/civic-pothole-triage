"""Fill the app with a realistic demo through the REAL pipeline (detector, trust checks,
merging, routing, authority actions, escalation). Only timestamps are back-dated afterwards,
spreading activity over the last 30 days.

Photos: real pothole photos from the held-out close-up test split (never used for training).
Every demo device id starts with "demo-", so --reset removes demo data only.

Usage (from backend/, with the wards seeded):
    python tools/seed_demo.py            # add demo data
    python tools/seed_demo.py --reset    # remove all demo data (and its photos)
"""

from __future__ import annotations

import argparse
import random
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, func, select, text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.lifecycle.transitions import sla  # noqa: E402
from app.models import Device, Issue, IssueEvent, Report, Ward  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PHOTOS = ROOT / "data" / "datasets" / "pothole_mix" / "images" / "test_closeup"
DEMO = "demo-"
MYSURU = (12.2958, 76.6394)


def shake(img: np.ndarray, seed: int, n: int = 3) -> list[bytes]:
    """n live-camera-like frames: whole-frame sub-pixel shifts (edges mirrored, no crop) + noise."""
    rng = np.random.default_rng(seed)
    h, w = img.shape[:2]
    out = []
    for i in range(n):
        m = np.float32([[1, 0, 2.5 * i + rng.uniform(-0.5, 0.5)], [0, 1, 1.5 * i + rng.uniform(-0.5, 0.5)]])
        f = cv2.warpAffine(img, m, (w, h), borderMode=cv2.BORDER_REFLECT)
        f = np.clip(f.astype(np.float32) + rng.normal(0, 2.5, f.shape), 0, 255).astype(np.uint8)
        out.append(cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes())
    return out


def jpeg(img: np.ndarray) -> bytes:
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()


def nudge(lat: float, lng: float, metres_n: float, metres_e: float = 0.0) -> tuple[float, float]:
    return lat + metres_n / 110_600, lng + metres_e / (110_600 * np.cos(np.radians(lat)))


def reset() -> None:
    settings = get_settings()
    photo_root = settings.resolve(settings.photo_dir)
    with SessionLocal() as db:
        demo_reports = db.scalars(select(Report).where(Report.device_id.like(f"{DEMO}%"))).all()
        issue_ids = {r.issue_id for r in demo_reports if r.issue_id}
        # Only remove issues whose reports are ALL demo reports.
        mixed = {iid for (iid,) in db.execute(
            select(Report.issue_id).where(Report.issue_id.in_(issue_ids), ~Report.device_id.like(f"{DEMO}%")))}
        removable = issue_ids - mixed
        for r in demo_reports:
            shutil.rmtree(photo_root / "reports" / r.id, ignore_errors=True)
        db.execute(delete(Report).where(Report.device_id.like(f"{DEMO}%")))
        db.execute(delete(IssueEvent).where(IssueEvent.issue_id.in_(removable)))
        db.execute(delete(Issue).where(Issue.id.in_(removable)))
        db.execute(delete(Device).where(Device.id.like(f"{DEMO}%")))
        db.commit()
    print(f"Removed {len(demo_reports)} demo reports and {len(removable)} demo issues.")


def seed(n_sites: int, seed_value: int) -> None:
    settings = get_settings()
    settings.ip_hourly_limit = 10**6        # one in-process client sends everything
    settings.scheduler_enabled = False
    from fastapi.testclient import TestClient

    from app.main import app

    rng = random.Random(seed_value)
    photos = sorted(PHOTOS.glob("*.jpg"))
    rng.shuffle(photos)
    if len(photos) < n_sites + 20:
        sys.exit(f"Need at least {n_sites + 20} photos in {PHOTOS}")
    images = iter(cv2.imread(str(p)) for p in photos)

    with SessionLocal() as db:
        if not db.scalar(select(func.count()).select_from(Ward)):
            sys.exit("Seed the wards first: python tools/seed_wards.py --download")
        sites = db.execute(text(
            "SELECT ST_Y(p), ST_X(p) FROM (SELECT ST_PointOnSurface(geom) AS p FROM ward "
            "ORDER BY md5(corporation || ward_no::text || :s) LIMIT :n) q"), {"s": str(seed_value), "n": n_sites}).all()

    auth = {"X-Authority-Token": settings.authority_token}
    counter = iter(range(10**6))
    created: list[dict] = []

    def send(client, frames, lat, lng, source="camera", acc=6.0, device=None) -> dict:
        r = client.post("/api/reports",
                        data={"lat": lat, "lng": lng, "accuracy_m": acc, "capture_source": source,
                              "device_id": device or f"{DEMO}{next(counter):05d}"},
                        files=[("frames", (f"f{i}.jpg", b, "image/jpeg")) for i, b in enumerate(frames)])
        r.raise_for_status()
        return r.json()

    with TestClient(app) as client:
        # 1. One live report per site.
        for i, (lat, lng) in enumerate(sites):
            created.append(send(client, shake(next(images), i), lat, lng, acc=rng.uniform(4, 14)))
        issue_ids = [c["issue_id"] for c in created if c["issue_id"]]

        # 2. Second citizens report some of the same potholes (merged into one issue).
        for lat, lng in sites[:8]:
            la, ln = nudge(lat, lng, rng.uniform(-6, 6), rng.uniform(-6, 6))
            send(client, shake(next(images), 1000 + next(counter)), la, ln)

        # 3. Low-trust reports held as unverified (gallery uploads without camera data).
        held = []
        for lat, lng in sites[-4:]:
            la, ln = nudge(lat, lng, 80)
            held.append(send(client, [jpeg(next(images))], la, ln, source="upload"))

        # 4. Fakes: a reused photo, a photo of a screen, and a report from outside Bengaluru.
        from tools.calibrate_screen import simulate_screen_photo

        reused = shake(next(images), 5000)
        la, ln = nudge(*sites[1], 300)
        send(client, reused, la, ln)
        la, ln = nudge(*sites[2], 300)
        send(client, reused, la, ln)                                       # same photo, other device
        la, ln = nudge(*sites[3], 300)
        send(client, [jpeg(simulate_screen_photo(next(images), rng))], la, ln)
        send(client, shake(next(images), 5001), *MYSURU)                   # outside the pilot area

        # 5. Authority work: acknowledge some, mark some fixed.
        for iid in issue_ids[8:14]:
            client.post(f"/api/issues/{iid}/status", json={"action": "acknowledge", "note": "crew scheduled"}, headers=auth)
        claimed = issue_ids[14:19]
        for iid in claimed:
            client.post(f"/api/issues/{iid}/status", json={"action": "claim_fixed", "note": "patched"}, headers=auth)

        # 6. A citizen re-photographs two "fixed" potholes with the same pothole photo as before.
        #    The detector decides: pothole found -> reopened; otherwise the check stays inconclusive.
        for iid in claimed[:2]:
            first = client.get(f"/api/issues/{iid}").json()
            idx = next(k for k, c in enumerate(created) if c["issue_id"] == iid)
            src = cv2.imread(str(photos[idx]))
            send(client, shake(cv2.flip(src, 1), 7000 + idx), first["lat"], first["lng"])

    # 7. Spread activity over the last 30 days, recompute deadlines, then escalate overdue ones.
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        demo_issue_ids = select(Report.issue_id).where(Report.device_id.like(f"{DEMO}%"), Report.issue_id.is_not(None))
        for issue in db.scalars(select(Issue).where(Issue.id.in_(demo_issue_ids))):
            age = timedelta(days=rng.uniform(0.5, 30), hours=rng.uniform(0, 23))
            shift = (now - age) - issue.opened_at
            issue.opened_at += shift
            for e in issue.events:
                e.at += shift
            for r in issue.reports:
                r.received_at += shift
            if issue.due_at is not None:
                issue.due_at = issue.opened_at + sla(issue.severity)
        db.commit()
        from app.lifecycle.escalation import escalate_overdue

        escalated = escalate_overdue(db)
        stats = dict(db.execute(select(Issue.status, func.count()).where(Issue.id.in_(demo_issue_ids))
                                .group_by(Issue.status)).all())
        states = dict(db.execute(select(Report.state, func.count()).where(Report.device_id.like(f"{DEMO}%"))
                                 .group_by(Report.state)).all())
    print(f"Seeded {len(sites)} sites. Overdue issues escalated: {escalated['moved_up']}.")
    print(f"Demo reports by state: {states}")
    print(f"Demo issues by status: {stats}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="remove all demo data")
    ap.add_argument("--sites", type=int, default=30)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    if args.reset:
        reset()
    else:
        seed(args.sites, args.seed)


if __name__ == "__main__":
    main()
