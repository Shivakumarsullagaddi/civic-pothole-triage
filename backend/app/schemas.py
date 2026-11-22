from datetime import datetime

from pydantic import BaseModel


class IssueEventOut(BaseModel):
    type: str
    from_status: str | None
    to_status: str | None
    actor: str
    note: str | None
    at: datetime


class IssueOut(BaseModel):
    id: str
    lat: float
    lng: float
    status: str
    severity: str | None
    report_count: int
    escalation_level: int
    opened_at: datetime
    due_at: datetime | None
    overdue: bool
    authority_id: int | None
    authority_name: str | None
    ward_id: int | None
    ward_no: int | None
    ward_name: str | None
    corporation: str | None


class IssueDetail(IssueOut):
    events: list[IssueEventOut]


class WardOut(BaseModel):
    ward_no: int
    name: str
    name_kn: str | None
    corporation: str
    zone_name: str | None
    authority: str | None
    escalation_chain: list[str]


class ReportOut(BaseModel):
    id: str
    state: str
    issue_id: str | None
    lat: float
    lng: float
    gps_accuracy_m: float | None
    capture_source: str
    received_at: datetime
    frame_count: int
    severity: str | None
    detections: dict | None
    trust_score: float | None
    trust_signals: dict | None
    reject_reason: str | None
    issue_status: str | None
    issue_report_count: int | None
    repair_check: dict | None
    ward_name: str | None
    corporation: str | None
    authority_name: str | None
