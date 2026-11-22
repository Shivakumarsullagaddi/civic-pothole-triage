"""Public dashboard numbers (no photos, no device ids, no personal data)."""

from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.lifecycle.transitions import ACTIVE
from app.models import Issue, IssueEvent, Report, Ward
from app.states import IssueStatus, ReportState

router = APIRouter(prefix="/api", tags=["stats"])


class CountRow(BaseModel):
    key: str
    count: int


class CorporationRow(BaseModel):
    corporation: str
    open: int
    overdue: int


class WardRow(BaseModel):
    corporation: str
    ward_no: int
    ward_name: str
    open: int
    overdue: int


class Stats(BaseModel):
    generated_at: datetime
    reports_total: int
    reports_by_state: list[CountRow]
    issues_total: int
    issues_by_status: list[CountRow]
    open_issues: int
    overdue_issues: int
    escalated_issues: int
    verified_fixed: int
    falsely_closed: int
    fakes_blocked: int
    held_for_confirmation: int
    blocked_reasons: list[CountRow]
    by_corporation: list[CorporationRow]
    top_wards: list[WardRow]
    median_days_to_verified_fix: float | None


SIGNAL_LABELS = {
    "reused_photo": "Photo reused from another report",
    "duplicate_submission": "Same photo submitted twice",
    "outside_area": "Outside the GBA pilot area",
    "screen_recapture": "Photo of a screen",
    "burst_identical": "Live frames identical",
    "burst_mismatch": "Live frames from different scenes",
    "gallery_upload": "Gallery upload (unverified capture)",
    "no_exif": "Upload without camera metadata",
    "old_photo": "Old photo",
    "exif_gps_mismatch": "Photo GPS does not match location",
    "gps_accuracy": "Poor GPS accuracy",
    "impossible_travel": "Impossible travel",
    "device_history": "Device with many rejected reports",
}


@router.get("/stats", response_model=Stats)
def stats(db: Session = Depends(get_db)) -> Stats:
    now = datetime.now(timezone.utc)
    by_state = dict(db.execute(select(Report.state, func.count()).group_by(Report.state)).all())
    by_status = dict(db.execute(select(Issue.status, func.count()).group_by(Issue.status)).all())
    active = list(ACTIVE)
    overdue_cond = (Issue.status.in_(active)) & (Issue.due_at < now)

    # Why reports were blocked or held: count each trust signal once per report.
    reasons: Counter = Counter()
    for (signals,) in db.execute(select(Report.trust_signals).where(
            Report.state.in_([ReportState.REJECTED, ReportState.NEEDS_REVIEW]))):
        for name in {s["name"] for s in (signals or {}).get("signals", []) if s.get("penalty", 0) > 0}:
            reasons[SIGNAL_LABELS.get(name, name)] += 1

    corp_rows = db.execute(
        select(Ward.corporation,
               func.count(Issue.id).filter(Issue.status.in_(active)),
               func.count(Issue.id).filter(overdue_cond))
        .select_from(Ward).join(Issue, Issue.ward_id == Ward.id, isouter=True)
        .group_by(Ward.corporation).order_by(Ward.corporation)).all()

    ward_rows = db.execute(
        select(Ward.corporation, Ward.ward_no, Ward.name,
               func.count(Issue.id).filter(Issue.status.in_(active)).label("open"),
               func.count(Issue.id).filter(overdue_cond))
        .join(Issue, Issue.ward_id == Ward.id)
        .group_by(Ward.id).having(func.count(Issue.id).filter(Issue.status.in_(active)) > 0)
        .order_by(func.count(Issue.id).filter(Issue.status.in_(active)).desc(), Ward.corporation, Ward.ward_no)
        .limit(10)).all()

    fixed_at = (select(IssueEvent.issue_id, func.min(IssueEvent.at).label("at"))
                .where(IssueEvent.to_status == IssueStatus.VERIFIED_FIXED)
                .group_by(IssueEvent.issue_id).subquery())
    median_days = db.scalar(
        select(func.percentile_cont(0.5).within_group(
            func.extract("epoch", fixed_at.c.at - Issue.opened_at) / 86400))
        .join(fixed_at, fixed_at.c.issue_id == Issue.id))

    falsely_closed = db.scalar(select(func.count(func.distinct(IssueEvent.issue_id)))
                               .where(IssueEvent.to_status == IssueStatus.REOPENED)) or 0

    return Stats(
        generated_at=now,
        reports_total=sum(by_state.values()),
        reports_by_state=[CountRow(key=k, count=v) for k, v in sorted(by_state.items())],
        issues_total=sum(by_status.values()),
        issues_by_status=[CountRow(key=k, count=v) for k, v in sorted(by_status.items())],
        open_issues=sum(by_status.get(s, 0) for s in active),
        overdue_issues=db.scalar(select(func.count()).select_from(Issue).where(overdue_cond)) or 0,
        escalated_issues=db.scalar(select(func.count()).select_from(Issue).where(
            Issue.status.in_(active), Issue.escalation_level > 0)) or 0,
        verified_fixed=by_status.get(IssueStatus.VERIFIED_FIXED, 0),
        falsely_closed=falsely_closed,
        fakes_blocked=by_state.get(ReportState.REJECTED, 0),
        held_for_confirmation=by_state.get(ReportState.NEEDS_REVIEW, 0),
        blocked_reasons=[CountRow(key=k, count=v) for k, v in reasons.most_common()],
        by_corporation=[CorporationRow(corporation=c, open=o, overdue=d) for c, o, d in corp_rows],
        top_wards=[WardRow(corporation=c, ward_no=n, ward_name=w, open=o, overdue=d) for c, n, w, o, d in ward_rows],
        median_days_to_verified_fix=round(median_days, 1) if median_days is not None else None,
    )
