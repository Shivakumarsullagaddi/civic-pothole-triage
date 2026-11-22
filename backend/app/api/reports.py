from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from geoalchemy2.shape import to_shape
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Report
from app.pipeline.detect import Detector, get_detector
from app.pipeline.ingest import MAX_FRAME_BYTES, InputError, build_input
from app.pipeline.run import run_report
from app.ratelimit import check_limits
from app.schemas import ReportOut
from app.storage import get_storage

router = APIRouter(prefix="/api/reports", tags=["reports"])


def report_out(report: Report) -> ReportOut:
    p = to_shape(report.location)
    issue = report.issue
    return ReportOut(
        id=report.id,
        state=report.state,
        issue_id=report.issue_id,
        lat=p.y,
        lng=p.x,
        gps_accuracy_m=report.gps_accuracy_m,
        capture_source=report.capture_source,
        received_at=report.received_at,
        frame_count=len(report.photo_uris or []),
        severity=report.severity,
        detections=report.detections,
        trust_score=report.trust_score,
        trust_signals=report.trust_signals,
        reject_reason=report.reject_reason,
        issue_status=issue.status if issue else None,
        issue_report_count=issue.report_count if issue else None,
        repair_check=(report.detections or {}).get("repair_check"),
        ward_name=f"Ward {issue.ward.ward_no} {issue.ward.name}" if issue and issue.ward else None,
        corporation=issue.ward.corporation if issue and issue.ward else None,
        authority_name=issue.authority.name if issue and issue.authority else None,
    )


@router.post("", response_model=ReportOut, status_code=201)
def create_report(
    request: Request,
    frames: Annotated[list[UploadFile], File(description="1 to 3 full camera frames")],
    lat: Annotated[float, Form()],
    lng: Annotated[float, Form()],
    device_id: Annotated[str, Form()],
    accuracy_m: Annotated[float | None, Form()] = None,
    captured_at: Annotated[datetime | None, Form()] = None,
    capture_source: Annotated[Literal["camera", "upload"], Form()] = "camera",
    db: Session = Depends(get_db),
    detector: Detector | None = Depends(get_detector),
) -> ReportOut:
    if reason := check_limits(db, device_id, request.client.host if request.client else None):
        raise HTTPException(status_code=429, detail=reason)
    # Read one byte past the limit so oversized frames are rejected without reading them whole.
    data = [f.file.read(MAX_FRAME_BYTES + 1) for f in frames]
    try:
        inp = build_input(data, lat, lng, accuracy_m, captured_at, device_id, capture_source)
    except InputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    report = run_report(db, get_storage(), inp, detector)
    return report_out(report)


@router.get("/{report_id}", response_model=ReportOut)
def get_report(report_id: str, db: Session = Depends(get_db)) -> ReportOut:
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report_out(report)
