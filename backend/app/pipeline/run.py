"""Runs the report pipeline end to end (PLAN.md section 4)."""

import statistics

from sqlalchemy.orm import Session

from app.config import get_settings
from app.integrity.quality import measure
from app.models import Device, Report
from app.lifecycle.repair import find_claimed_fixed, verify_repair
from app.pipeline.cluster import attach_to_issue, point
from app.pipeline.detect import Detection, Detector, decode_image
from app.pipeline.ingest import ReportInput
from app.pipeline.severity import score_severity
from app.pipeline.trust import assess
from app.states import ReportState
from app.storage import Storage

EXT = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


def detect_frames(detector: Detector, frames) -> tuple[list[Detection], int]:
    """Detect on every full frame. Returns results and the index of the best frame."""
    results = [detector.detect(f) for f in frames]
    best = max(range(len(results)), key=lambda i: (len(results[i].boxes) > 0, results[i].best_score))
    return results, best


def run_report(db: Session, storage: Storage, inp: ReportInput, detector: Detector | None) -> Report:
    settings = get_settings()

    # 4. Prepare: decode once (EXIF orientation fixed, full frame) for every later step.
    frames = [decode_image(f.data) for f in inp.frames]

    # 5, 8, 9. Integrity checks and trust, judged against history before this report exists.
    device = db.get(Device, inp.device_id)
    trust = assess(db, inp, frames, device)

    if device is None:
        device = Device(id=inp.device_id, report_count=0, rejected_count=0)
        db.add(device)
    device.report_count += 1

    report = Report(
        device_id=inp.device_id,
        location=point(inp.lat, inp.lng),
        gps_accuracy_m=inp.accuracy_m,
        capture_source=inp.capture_source,
        captured_at=inp.captured_at,
        phash=trust.phash,
        trust_score=trust.score,
        trust_signals=trust.as_dict(),
        state=trust.state,
        reject_reason=trust.reject_reason,
    )
    db.add(report)
    db.flush()  # assigns report.id

    # 3. Store originals (full frames, untouched), including rejected ones for audit.
    report.photo_uris = [
        storage.save(f"reports/{report.id}/frame_{i}.{EXT[f.format]}", f.data)
        for i, f in enumerate(inp.frames)
    ]

    if report.state == ReportState.REJECTED:
        device.rejected_count += 1
        db.commit()
        db.refresh(report)
        return report

    # 6, 7. Detect and score severity.
    found: bool | None = None
    confident = False
    best = 0
    if detector is None:
        report.detections = {"available": False}
    else:
        results, best = detect_frames(detector, frames)
        sev = score_severity(results[best])
        report.severity = sev.level
        report.detections = {
            "available": True,
            "model": detector.path.name,
            "mode": settings.detection_mode,
            "best_frame": best,
            "severity_reasons": sev.reasons,
            "frames": [
                {"frame": i, "ms": round(r.ms), "width": r.width, "height": r.height,
                 "boxes": [b.as_dict() for b in r.boxes]}
                for i, r in enumerate(results)
            ],
        }
        found = bool(results[best].boxes)
        # A real pothole shows up in every frame of the burst; a lane dash or glare flickers.
        # Judge confidence on the median frame, not the luckiest one.
        burst_score = statistics.median(r.best_score for r in results)
        confident = burst_score >= settings.accept_conf
        report.detections["burst_score"] = round(burst_score, 4)
        report.detections["confident"] = confident
        if settings.detection_mode == "enforce":
            if not found:
                report.state = ReportState.NO_DAMAGE
            elif not confident and report.state == ReportState.ACCEPTED:
                # Something pothole-like but the model is unsure (lane markings, patches, shadows):
                # hold it until another person reports the same spot.
                report.state = ReportState.NEEDS_REVIEW
                signals = dict(report.trust_signals or {})
                signals["signals"] = [*signals.get("signals", []), {
                    "name": "uncertain_detection", "penalty": 0, "hard": False,
                    "detail": f"pothole not clearly visible (model confidence {burst_score:.0%} across the frames, "
                              f"needs {settings.accept_conf:.0%})"}]
                report.trust_signals = signals

    # Repair verification: a photo at an issue the authority marked fixed (PLAN.md 5.3).
    if fixed := find_claimed_fixed(db, inp.lat, inp.lng, inp.accuracy_m):
        quality = measure(frames[best])
        sure = None if found is None else (found and confident)
        check = verify_repair(db, fixed, report, found, quality, settings.detection_mode == "enforce", sure)
        report.detections = {**(report.detections or {}), "repair_check": check.as_dict(),
                             "quality": {"brightness": round(quality.brightness, 1),
                                         "sharpness": round(quality.sharpness, 1)}}
        db.commit()
        db.refresh(report)
        return report

    # 10-11. Merge into a nearby issue or create one and route it; corroboration upgrades.
    if report.state in (ReportState.ACCEPTED, ReportState.NEEDS_REVIEW):
        attach_to_issue(db, report, inp.lat, inp.lng, inp.accuracy_m)

    db.commit()
    db.refresh(report)
    return report
