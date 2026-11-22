"""Escalation: an active issue past its due date moves up one level of the authority chain
(ward office -> zone -> city corporation -> GBA) and gets a fresh SLA window there.

Run hourly by APScheduler inside the backend (local) and on demand via POST /internal/escalate.
In the cloud phase, Cloud Scheduler calls the same endpoint.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.lifecycle.transitions import ACTIVE, sla, utcnow
from app.models import Authority, Issue, IssueEvent
from app.states import EventType, IssueStatus


def _overdue_text(now: datetime, due: datetime) -> str:
    hours = (now - due).total_seconds() / 3600
    return f"{hours / 24:.1f} days" if hours >= 48 else f"{hours:.0f} h"


def escalate_overdue(db: Session, now: datetime | None = None) -> dict:
    now = now or utcnow()
    overdue = db.scalars(
        select(Issue).options(joinedload(Issue.authority))
        .where(Issue.status.in_(ACTIVE), Issue.due_at.is_not(None), Issue.due_at < now)
    ).all()
    moved = at_top = 0
    for issue in overdue:
        late = _overdue_text(now, issue.due_at)
        current = issue.authority
        parent = db.get(Authority, current.parent_id) if current and current.parent_id else None
        previous = issue.status
        issue.status = IssueStatus.ESCALATED
        issue.due_at = now + sla(issue.severity)
        if parent is not None:
            issue.authority_id = parent.id
            issue.escalation_level += 1
            note = f"overdue by {late}: moved from {current.name} to {parent.name}"
            moved += 1
        else:
            where = current.name if current else "no responsible office"
            note = f"overdue by {late}: already at the top ({where}); new deadline set"
            at_top += 1
        db.add(IssueEvent(issue_id=issue.id, type=EventType.ESCALATED, from_status=previous,
                          to_status=IssueStatus.ESCALATED, note=note))
    db.commit()
    return {"checked_at": now.isoformat(), "overdue": len(overdue), "moved_up": moved, "at_top": at_top}
