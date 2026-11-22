"""Step 10 of the report pipeline: attach a report to an existing issue or create one.

A report joins the nearest still-active issue within a GPS-aware radius:
    radius = clamp(reported GPS accuracy, 15 m, 30 m)
Distances use the geography type (metres on the earth's surface). New issues are routed to
the ward office that contains them (step 11).
"""

from geoalchemy2 import Geography
from geoalchemy2.elements import WKTElement
from sqlalchemy import cast, func, select, text
from sqlalchemy.orm import Session

from app.models import Issue, IssueEvent, Report
from app.states import ReportState
from app.lifecycle.transitions import start_clock, tighten_clock
from app.pipeline.route import route
from app.pipeline.severity import LEVELS
from app.states import EventType, IssueStatus

MIN_RADIUS_M = 15.0
MAX_RADIUS_M = 30.0
CLOSED = (IssueStatus.VERIFIED_FIXED, IssueStatus.DISMISSED)
# Serialises clustering so two simultaneous reports of one pothole cannot both create issues.
CLUSTER_LOCK = 724_001


def point(lat: float, lng: float) -> WKTElement:
    return WKTElement(f"POINT({lng} {lat})", srid=4326)


def merge_radius(accuracy_m: float | None) -> float:
    if accuracy_m is None:
        return MIN_RADIUS_M
    return min(max(accuracy_m, MIN_RADIUS_M), MAX_RADIUS_M)


def worse(a: str | None, b: str | None) -> str | None:
    if a is None or b is None:
        return a or b
    return a if LEVELS.index(a) >= LEVELS.index(b) else b


def find_nearby_issue(db: Session, lat: float, lng: float, radius_m: float) -> Issue | None:
    here = cast(point(lat, lng), Geography)
    there = cast(Issue.location, Geography)
    return db.scalar(
        select(Issue)
        .where(Issue.status.notin_(CLOSED), func.ST_DWithin(there, here, radius_m))
        .order_by(func.ST_Distance(there, here))
        .limit(1)
    )


def corroborate(db: Session, issue: Issue, report: Report) -> None:
    """An independent device reporting the same pothole confirms both reports.

    needs_review reports from other devices on this issue (and this one) become accepted,
    and an unverified issue opens. A trusted (accepted) report also opens it on its own.
    """
    others = [r for r in issue.reports if r.id != report.id
              and r.state in (ReportState.ACCEPTED, ReportState.NEEDS_REVIEW)]
    independent = [r for r in others if r.device_id != report.device_id]
    if independent:
        for r in [report, *independent]:
            if r.state == ReportState.NEEDS_REVIEW:
                r.state = ReportState.ACCEPTED
                signals = dict(r.trust_signals or {})
                signals["corroborated"] = "confirmed by a report from another device"
                r.trust_signals = signals
    if issue.status == IssueStatus.UNVERIFIED and report.state == ReportState.ACCEPTED:
        why = "corroborated by another device" if independent else "trusted report received"
        db.add(IssueEvent(issue_id=issue.id, type=EventType.STATUS_CHANGED,
                          from_status=IssueStatus.UNVERIFIED, to_status=IssueStatus.OPEN, note=why))
        issue.status = IssueStatus.OPEN


def attach_to_issue(db: Session, report: Report, lat: float, lng: float,
                    accuracy_m: float | None = None) -> Issue:
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": CLUSTER_LOCK})
    radius = merge_radius(accuracy_m)
    issue = find_nearby_issue(db, lat, lng, radius)

    if issue is not None:
        issue.report_count += 1
        issue.severity = worse(issue.severity, report.severity)
        db.add(IssueEvent(issue_id=issue.id, type=EventType.REPORT_ADDED,
                          note=f"Report {report.id} merged (within {radius:.0f} m)"))
        db.flush()  # keep the merge event before any corroboration event
        corroborate(db, issue, report)
        start_clock(issue)
        tighten_clock(issue)
        if issue.authority_id is None:
            # Created before wards were loaded, or on a boundary gap: try routing again.
            r = route(db, lat, lng)
            if r.authority is not None:
                issue.ward_id, issue.authority_id = r.ward.id, r.authority.id
                db.add(IssueEvent(issue_id=issue.id, type=EventType.ROUTED,
                                  note=f"routed to {r.authority.name}"))
    else:
        r = route(db, lat, lng)
        status = IssueStatus.OPEN if report.state == ReportState.ACCEPTED else IssueStatus.UNVERIFIED
        issue = Issue(location=point(lat, lng), status=status, report_count=1,
                      severity=report.severity,
                      ward_id=r.ward.id if r.ward else None,
                      authority_id=r.authority.id if r.authority else None)
        start_clock(issue)
        db.add(issue)
        db.flush()
        where = (f"routed to {r.authority.name}" if r.authority
                 else "outside GBA wards: no authority assigned")
        db.add(IssueEvent(issue_id=issue.id, type=EventType.CREATED, to_status=issue.status,
                          note=f"First report {report.id}; {where}"))
    report.issue_id = issue.id
    return issue
