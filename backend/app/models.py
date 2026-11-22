"""Database tables (PLAN.md section 6). Points are WGS84 (SRID 4326), lon/lat order."""

import uuid
from datetime import datetime, timezone

from geoalchemy2 import Geometry
from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.states import IssueStatus, ReportState


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Authority(Base):
    """Escalation chain: ward office -> zone -> city corporation -> GBA."""

    __tablename__ = "authority"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)  # stable seed key, e.g. ward:25
    name: Mapped[str] = mapped_column(String(200))
    name_kn: Mapped[str | None] = mapped_column(String(200))
    level: Mapped[str] = mapped_column(String(20))  # ward | zone | corporation | gba
    email: Mapped[str | None] = mapped_column(String(200))  # only when officially published
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("authority.id"))

    parent: Mapped["Authority | None"] = relationship(remote_side="Authority.id")


class Ward(Base):
    """Ward numbers restart in each GBA corporation, so a ward is (corporation, ward_no)."""

    __tablename__ = "ward"
    __table_args__ = (UniqueConstraint("corporation", "ward_no"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ward_no: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    name_kn: Mapped[str | None] = mapped_column(String(200))
    corporation: Mapped[str] = mapped_column(String(50))
    zone_name: Mapped[str | None] = mapped_column(String(100))
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326, spatial_index=True), nullable=False)
    authority_id: Mapped[int | None] = mapped_column(ForeignKey("authority.id"))


class User(Base):
    """Authority staff. Citizens never log in. role: officer | admin."""

    __tablename__ = "app_user"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default="officer")
    authority_id: Mapped[int | None] = mapped_column(ForeignKey("authority.id"))  # their office, if any
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    authority: Mapped["Authority | None"] = relationship()


class Device(Base):
    __tablename__ = "device"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    report_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)


class Issue(Base):
    __tablename__ = "issue"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    location = mapped_column(Geometry("POINT", srid=4326, spatial_index=True), nullable=False)
    ward_id: Mapped[int | None] = mapped_column(ForeignKey("ward.id"))
    authority_id: Mapped[int | None] = mapped_column(ForeignKey("authority.id"))
    severity: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default=IssueStatus.OPEN)
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)
    report_count: Mapped[int] = mapped_column(Integer, default=0)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    ward: Mapped[Ward | None] = relationship()
    authority: Mapped[Authority | None] = relationship()
    reports: Mapped[list["Report"]] = relationship(back_populates="issue")
    events: Mapped[list["IssueEvent"]] = relationship(back_populates="issue", order_by="IssueEvent.id")


class Report(Base):
    __tablename__ = "report"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(ForeignKey("device.id"), index=True)
    issue_id: Mapped[str | None] = mapped_column(ForeignKey("issue.id"), index=True)
    location = mapped_column(Geometry("POINT", srid=4326, spatial_index=True), nullable=False)
    gps_accuracy_m: Mapped[float | None] = mapped_column(Float)
    capture_source: Mapped[str] = mapped_column(String(20), default="camera")  # camera | upload
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    photo_uris: Mapped[list] = mapped_column(JSON, default=list)
    phash: Mapped[str | None] = mapped_column(String(32), index=True)
    detections: Mapped[list | None] = mapped_column(JSON)
    severity: Mapped[str | None] = mapped_column(String(20))
    trust_score: Mapped[float | None] = mapped_column(Float)
    trust_signals: Mapped[dict | None] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(20), default=ReportState.RECEIVED)
    reject_reason: Mapped[str | None] = mapped_column(Text)

    issue: Mapped[Issue | None] = relationship(back_populates="reports")


class IssueEvent(Base):
    __tablename__ = "issue_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[str] = mapped_column(ForeignKey("issue.id"), index=True)
    type: Mapped[str] = mapped_column(String(30))
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str | None] = mapped_column(String(30))
    actor: Mapped[str] = mapped_column(String(50), default="system")
    note: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    issue: Mapped[Issue] = relationship(back_populates="events")
