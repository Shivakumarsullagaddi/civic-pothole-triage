"""Issue lifecycle (PLAN.md section 5.2): who may move an issue from which status to which.

Authority actions come from the authority page; system moves come from escalation (M5) and
repair verification (M6). Every change writes an IssueEvent.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import Issue, IssueEvent
from app.states import EventType, IssueStatus as S

# Days the responsible office has, per severity, before the issue escalates one level.
SLA_DAYS = {"critical": 2, "high": 7, "medium": 14, "low": 30, None: 14}

AUTHORITY_ACTIONS: dict[str, tuple[set[str], str]] = {
    # action: (allowed from, goes to)
    "acknowledge": ({S.OPEN, S.ESCALATED, S.REOPENED}, S.ACKNOWLEDGED),
    "claim_fixed": ({S.OPEN, S.ACKNOWLEDGED, S.ESCALATED, S.REOPENED}, S.CLAIMED_FIXED),
    "dismiss": ({S.UNVERIFIED, S.OPEN}, S.DISMISSED),
}
ACTIVE = {S.OPEN, S.ACKNOWLEDGED, S.ESCALATED, S.REOPENED}  # SLA clock running


class TransitionError(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sla(severity: str | None) -> timedelta:
    return timedelta(days=SLA_DAYS.get(severity, SLA_DAYS[None]))


def start_clock(issue: Issue, now: datetime | None = None) -> None:
    """Set the due date when an issue becomes active (open)."""
    if issue.due_at is None and issue.status in ACTIVE:
        issue.due_at = (now or utcnow()) + sla(issue.severity)


def tighten_clock(issue: Issue) -> None:
    """A worse severity can only bring the due date earlier, never push it later."""
    if issue.due_at is not None and issue.status in ACTIVE:
        issue.due_at = min(issue.due_at, issue.opened_at + sla(issue.severity))


def apply_authority_action(db: Session, issue: Issue, action: str, actor: str, note: str | None) -> Issue:
    if action not in AUTHORITY_ACTIONS:
        raise TransitionError(f"Unknown action {action!r}")
    allowed, target = AUTHORITY_ACTIONS[action]
    if issue.status not in allowed:
        raise TransitionError(f"Cannot {action.replace('_', ' ')} an issue that is {issue.status}")
    if action == "dismiss" and not (note and note.strip()):
        raise TransitionError("Dismissing needs a note explaining why")
    previous = issue.status
    issue.status = target
    db.add(IssueEvent(issue_id=issue.id, type=EventType.STATUS_CHANGED, from_status=previous,
                      to_status=target, actor=actor, note=(note or "").strip() or None))
    return issue
