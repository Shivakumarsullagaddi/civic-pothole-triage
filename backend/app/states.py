"""State names for reports and issues (see PLAN.md section 5)."""

from enum import StrEnum


class ReportState(StrEnum):
    RECEIVED = "received"
    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"
    NO_DAMAGE = "no_damage"


class IssueStatus(StrEnum):
    UNVERIFIED = "unverified"
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    ESCALATED = "escalated"
    CLAIMED_FIXED = "claimed_fixed"
    VERIFIED_FIXED = "verified_fixed"
    REOPENED = "reopened"
    DISMISSED = "dismissed"


class EventType(StrEnum):
    CREATED = "created"
    REPORT_ADDED = "report_added"
    STATUS_CHANGED = "status_changed"
    ROUTED = "routed"
    ESCALATED = "escalated"
