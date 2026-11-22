"""Repair verification (PLAN.md section 5.3): a citizen photo at an issue marked "claimed fixed".

- Pothole still detected            -> reopened ("falsely closed"), fresh deadline.
- No pothole, and the photo is trusted (accepted), sharp, well lit, and the detector is in
  `enforce` mode (i.e. trusted to see potholes)   -> verified_fixed.
- Anything else                     -> no status change; the report is kept as "inconclusive".
A false "fixed" is worse than none, so every doubt leaves the issue as it is.
"""

from dataclasses import dataclass

from geoalchemy2 import Geography
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.integrity.quality import Quality
from app.lifecycle.transitions import sla, utcnow
from app.models import Issue, IssueEvent, Report
from app.pipeline.cluster import merge_radius, point
from app.pipeline.trust import ACCEPT_AT
from app.states import EventType, IssueStatus


@dataclass
class RepairCheck:
    outcome: str  # verified_fixed | reopened | inconclusive
    detail: str

    def as_dict(self) -> dict:
        return {"outcome": self.outcome, "detail": self.detail}


def find_claimed_fixed(db: Session, lat: float, lng: float, accuracy_m: float | None) -> Issue | None:
    here = cast(point(lat, lng), Geography)
    there = cast(Issue.location, Geography)
    return db.scalar(
        select(Issue)
        .where(Issue.status == IssueStatus.CLAIMED_FIXED,
               func.ST_DWithin(there, here, merge_radius(accuracy_m)))
        .order_by(func.ST_Distance(there, here)).limit(1))


def verify_repair(db: Session, issue: Issue, report: Report, pothole_found: bool | None,
                  quality: Quality, enforce: bool, confident: bool | None = None) -> RepairCheck:
    """pothole_found: any box at all. confident: a box at or above the accept threshold
    (None = treat any box as confident, e.g. when no threshold applies)."""
    report.issue_id = issue.id
    issue.report_count += 1
    if confident is None:
        confident = bool(pothole_found)

    if pothole_found and not confident:
        check = RepairCheck("inconclusive", "cannot confirm the repair: something pothole-like is visible "
                                            "but the model is not sure; needs a clearer photo")
        db.add(IssueEvent(issue_id=issue.id, type=EventType.REPORT_ADDED,
                          note=f"Repair check from report {report.id} inconclusive: uncertain detection"))
        return check

    if pothole_found:
        issue.status = IssueStatus.REOPENED
        issue.due_at = utcnow() + sla(issue.severity)
        check = RepairCheck("reopened", "falsely closed: a citizen photo after the repair still shows a pothole")
        db.add(IssueEvent(issue_id=issue.id, type=EventType.STATUS_CHANGED, from_status=IssueStatus.CLAIMED_FIXED,
                          to_status=IssueStatus.REOPENED, note=f"{check.detail} (report {report.id})"))
        return check

    reasons = []
    if pothole_found is None:
        reasons.append("no detector available")
    # Judge the photo's trust score, not its final state (a fix photo is often "no_damage").
    if (report.trust_score or 0.0) < ACCEPT_AT:
        reasons.append(f"photo trust too low ({round((report.trust_score or 0) * 100)}%)")
    if quality.problem:
        reasons.append(quality.problem)
    if not enforce:
        reasons.append("detector is in advisory mode, so 'no pothole found' is not trusted yet")

    if reasons:
        check = RepairCheck("inconclusive", "cannot confirm the repair: " + "; ".join(reasons))
        db.add(IssueEvent(issue_id=issue.id, type=EventType.REPORT_ADDED,
                          note=f"Repair check from report {report.id} inconclusive: {'; '.join(reasons)}"))
        return check

    issue.status = IssueStatus.VERIFIED_FIXED
    check = RepairCheck("verified_fixed", "a trusted, clear citizen photo shows no pothole after the repair")
    db.add(IssueEvent(issue_id=issue.id, type=EventType.STATUS_CHANGED, from_status=IssueStatus.CLAIMED_FIXED,
                      to_status=IssueStatus.VERIFIED_FIXED, note=f"{check.detail} (report {report.id})"))
    return check
