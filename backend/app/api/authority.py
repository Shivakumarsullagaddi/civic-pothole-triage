"""Authority endpoints: signed-in officers and admins (see app/auth.py). Photos are only ever
served here, never publicly. /internal/escalate is for Cloud Scheduler (X-Internal-Token)."""

import secrets
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel
from geoalchemy2.shape import to_shape
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.api.issues import issue_out
from app.auth import require_authority
from app.config import get_settings
from app.db import get_db
from app.lifecycle.escalation import escalate_overdue
from app.lifecycle.transitions import ACTIVE, TransitionError, apply_authority_action
from app.models import Issue, IssueEvent, Report
from app.schemas import IssueDetail, IssueEventOut, IssueOut
from app.states import IssueStatus
from app.storage import get_storage

router = APIRouter(tags=["authority"])


def require_internal(x_internal_token: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_internal_token, get_settings().internal_token):
        raise HTTPException(401, "Missing or wrong internal token")


class StatusChange(BaseModel):
    action: Literal["acknowledge", "claim_fixed", "dismiss"]
    note: str | None = None


class Box(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float
    score: float


class FrameDetections(BaseModel):
    """Detected pothole boxes for one photo, in that photo's own pixel coordinates."""

    frame: int
    width: int
    height: int
    boxes: list[Box]


class ReportSummary(BaseModel):
    id: str
    state: str
    device_hint: str  # last 4 characters only
    capture_source: str
    received_at: str
    severity: str | None
    trust_score: float | None
    reasons: list[str]
    frame_count: int
    frames: list[FrameDetections]
    best_frame: int | None


class AuthorityIssue(IssueDetail):
    reports: list[ReportSummary]


class AuthorityIssueRow(IssueOut):
    """One row of the authority issue table: issue fields + latest report for the thumbnail."""

    latest_report_id: str | None
    latest_report_at: datetime | None
    last_activity_at: datetime | None


class ReportRow(BaseModel):
    id: str
    received_at: datetime
    state: str
    trust_score: float | None
    capture_source: str
    severity: str | None
    boxes: int
    frame_count: int
    reasons: list[str]
    issue_id: str | None
    issue_status: str | None
    ward_no: int | None
    ward_name: str | None
    corporation: str | None


class ReportDetail(ReportSummary):
    issue_id: str | None
    issue_status: str | None
    ward_name: str | None
    corporation: str | None
    authority_name: str | None
    lat: float
    lng: float
    reject_reason: str | None
    severity_reasons: list[str]
    repair_check: dict | None


def reasons_of(r: Report) -> list[str]:
    return [s["detail"] for s in (r.trust_signals or {}).get("signals", [])]


def summarise(r: Report) -> ReportSummary:
    det = r.detections or {}
    return ReportSummary(
        id=r.id, state=r.state, device_hint=r.device_id[-4:], capture_source=r.capture_source,
        received_at=r.received_at.isoformat(), severity=r.severity, trust_score=r.trust_score,
        reasons=reasons_of(r), frame_count=len(r.photo_uris or []),
        frames=[FrameDetections(**{k: f[k] for k in ("frame", "width", "height", "boxes")})
                for f in det.get("frames", [])],
        best_frame=det.get("best_frame"))


@router.get("/api/authority/reports", response_model=list[ReportRow], summary="Most recent reports, newest first")
def recent_reports(limit: int = Query(100, ge=1, le=500), state: str | None = Query(None),
                   _: str = Depends(require_authority), db: Session = Depends(get_db)) -> list[ReportRow]:
    q = (select(Report).options(joinedload(Report.issue).joinedload(Issue.ward))
         .order_by(Report.received_at.desc()).limit(limit))
    if state:
        q = q.where(Report.state.in_([s.strip() for s in state.split(",")]))
    rows = []
    for r in db.scalars(q).unique():
        det, issue = r.detections or {}, r.issue
        frames = det.get("frames") or []
        best = frames[det.get("best_frame") or 0] if frames else None
        rows.append(ReportRow(
            id=r.id, received_at=r.received_at, state=r.state, trust_score=r.trust_score,
            capture_source=r.capture_source, severity=r.severity, boxes=len(best["boxes"]) if best else 0,
            frame_count=len(r.photo_uris or []), reasons=reasons_of(r),
            issue_id=r.issue_id, issue_status=issue.status if issue else None,
            ward_no=issue.ward.ward_no if issue and issue.ward else None,
            ward_name=issue.ward.name if issue and issue.ward else None,
            corporation=issue.ward.corporation if issue and issue.ward else None))
    return rows


@router.get("/api/authority/reports/{report_id}", response_model=ReportDetail, summary="One report in full")
def report_detail(report_id: str, _: str = Depends(require_authority), db: Session = Depends(get_db)) -> ReportDetail:
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "Report not found")
    p, issue, det = to_shape(r.location), r.issue, r.detections or {}
    return ReportDetail(
        **summarise(r).model_dump(), issue_id=r.issue_id, issue_status=issue.status if issue else None,
        ward_name=f"Ward {issue.ward.ward_no} {issue.ward.name}" if issue and issue.ward else None,
        corporation=issue.ward.corporation if issue and issue.ward else None,
        authority_name=issue.authority.name if issue and issue.authority else None,
        lat=p.y, lng=p.x, reject_reason=r.reject_reason,
        severity_reasons=det.get("severity_reasons", []), repair_check=det.get("repair_check"))


@router.get("/api/authority/issues", response_model=list[AuthorityIssueRow], summary="Issues for the authority work list")
def work_list(
    status: str | None = Query(None, description="Comma-separated; default: everything still open"),
    _: str = Depends(require_authority),
    db: Session = Depends(get_db),
) -> list[dict]:
    wanted = [s.strip() for s in status.split(",")] if status else [
        *ACTIVE, IssueStatus.UNVERIFIED, IssueStatus.CLAIMED_FIXED]
    q = (select(Issue).options(joinedload(Issue.ward), joinedload(Issue.authority))
         .where(Issue.status.in_(wanted)).order_by(Issue.due_at.asc().nulls_last(), Issue.opened_at))
    issues = db.scalars(q).all()
    ids = [i.id for i in issues]
    latest: dict[str, tuple[str, datetime]] = {}
    for rid, iid, at in db.execute(
            select(Report.id, Report.issue_id, Report.received_at)
            .where(Report.issue_id.in_(ids)).order_by(Report.received_at)):
        latest[iid] = (rid, at)  # ascending order, so the newest report wins
    activity = dict(db.execute(select(IssueEvent.issue_id, func.max(IssueEvent.at))
                               .where(IssueEvent.issue_id.in_(ids)).group_by(IssueEvent.issue_id)).all())
    return [{**issue_out(i), "latest_report_id": latest.get(i.id, (None, None))[0],
             "latest_report_at": latest.get(i.id, (None, None))[1], "last_activity_at": activity.get(i.id)}
            for i in issues]


@router.get("/api/authority/issues/{issue_id}", response_model=AuthorityIssue)
def work_item(issue_id: str, _: str = Depends(require_authority), db: Session = Depends(get_db)) -> AuthorityIssue:
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(404, "Issue not found")
    reports = [summarise(r) for r in sorted(issue.reports, key=lambda r: r.received_at)]
    return AuthorityIssue(
        **issue_out(issue),
        events=[IssueEventOut(type=e.type, from_status=e.from_status, to_status=e.to_status,
                              actor=e.actor, note=e.note, at=e.at) for e in issue.events],
        reports=reports)


@router.get("/api/authority/reports/{report_id}/frames/{index}", summary="A report photo (authority only)")
def report_frame(report_id: str, index: int, _: str = Depends(require_authority),
                 db: Session = Depends(get_db)) -> Response:
    report = db.get(Report, report_id)
    if report is None or not 0 <= index < len(report.photo_uris or []):
        raise HTTPException(404, "Photo not found")
    key = report.photo_uris[index]
    media = "image/png" if key.endswith(".png") else "image/webp" if key.endswith(".webp") else "image/jpeg"
    return Response(get_storage().load(key), media_type=media, headers={"Cache-Control": "private, max-age=600"})


@router.post("/api/issues/{issue_id}/status", response_model=IssueDetail)
def change_status(issue_id: str, body: StatusChange, actor: str = Depends(require_authority),
                  db: Session = Depends(get_db)) -> IssueDetail:
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(404, "Issue not found")
    try:
        apply_authority_action(db, issue, body.action, actor, body.note)
    except TransitionError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    db.refresh(issue)
    return IssueDetail(
        **issue_out(issue),
        events=[IssueEventOut(type=e.type, from_status=e.from_status, to_status=e.to_status,
                              actor=e.actor, note=e.note, at=e.at) for e in issue.events])


@router.post("/internal/escalate", summary="Escalate overdue issues now (also runs hourly)")
def escalate_now(_: None = Depends(require_internal), db: Session = Depends(get_db)) -> dict:
    return escalate_overdue(db)
