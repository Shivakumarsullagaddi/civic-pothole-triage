"""Login/logout/me for staff, and admin-only account management + escalation."""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import (check_password_rules, clear_session, current_user, hash_password,
                      record_failure, require_admin, set_session, too_many_attempts, verify_password)
from app.db import get_db
from app.lifecycle.escalation import escalate_overdue
from app.models import Authority, User

router = APIRouter(tags=["accounts"])


class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str
    active: bool
    authority_id: int | None
    authority_name: str | None
    created_at: datetime
    last_login: datetime | None


class UserCreate(BaseModel):
    email: str
    name: str
    password: str
    role: Literal["officer", "admin"] = "officer"
    authority_id: int | None = None

    @field_validator("email")
    @classmethod
    def email_shape(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or "." not in v.split("@")[-1] or len(v) > 200:
            raise ValueError("Enter a valid email address")
        return v


class UserUpdate(BaseModel):
    name: str | None = None
    role: Literal["officer", "admin"] | None = None
    active: bool | None = None
    password: str | None = None
    authority_id: int | None = None


class AuthorityOut(BaseModel):
    id: int
    name: str
    level: str


def user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, name=u.name, role=u.role, active=u.active,
                   authority_id=u.authority_id, authority_name=u.authority.name if u.authority else None,
                   created_at=u.created_at, last_login=u.last_login)


@router.post("/api/auth/login", response_model=UserOut)
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)) -> UserOut:
    email = body.email.strip().lower()
    if too_many_attempts(email):
        raise HTTPException(429, "Too many failed attempts. Wait 5 minutes and try again.")
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or not user.active or not verify_password(user.password_hash, body.password):
        record_failure(email)
        raise HTTPException(401, "Wrong email or password")
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    set_session(response, user)
    return user_out(user)


@router.post("/api/auth/logout", status_code=204)
def logout(response: Response) -> Response:
    clear_session(response)
    response.status_code = 204
    return response


@router.get("/api/auth/me", response_model=UserOut | None)
def me(user: User | None = Depends(current_user)) -> UserOut | None:
    return user_out(user) if user else None


@router.get("/api/admin/users", response_model=list[UserOut])
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[UserOut]:
    return [user_out(u) for u in db.scalars(select(User).order_by(User.role, User.name))]


@router.post("/api/admin/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> UserOut:
    check_password_rules(body.password)
    if db.scalar(select(User).where(func.lower(User.email) == body.email)):
        raise HTTPException(409, "An account with this email already exists")
    if body.authority_id is not None and db.get(Authority, body.authority_id) is None:
        raise HTTPException(422, "Unknown office")
    user = User(email=body.email, name=body.name.strip() or body.email, password_hash=hash_password(body.password),
                role=body.role, authority_id=body.authority_id, active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user_out(user)


@router.patch("/api/admin/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, admin: User = Depends(require_admin),
                db: Session = Depends(get_db)) -> UserOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if user.id == admin.id and (body.active is False or body.role == "officer"):
        raise HTTPException(409, "You cannot deactivate or demote your own account")
    if body.name is not None:
        user.name = body.name.strip() or user.name
    if body.role is not None:
        user.role = body.role
    if body.active is not None:
        user.active = body.active
    if body.password:
        check_password_rules(body.password)
        user.password_hash = hash_password(body.password)
    if "authority_id" in body.model_fields_set:
        if body.authority_id is not None and db.get(Authority, body.authority_id) is None:
            raise HTTPException(422, "Unknown office")
        user.authority_id = body.authority_id
    db.commit()
    db.refresh(user)
    return user_out(user)


@router.get("/api/admin/authorities", response_model=list[AuthorityOut])
def search_authorities(q: str = Query("", max_length=100), _: User = Depends(require_admin),
                       db: Session = Depends(get_db)) -> list[AuthorityOut]:
    stmt = select(Authority).order_by(Authority.level, Authority.name).limit(30)
    if q.strip():
        stmt = stmt.where(Authority.name.ilike(f"%{q.strip()}%"))
    return [AuthorityOut(id=a.id, name=a.name, level=a.level) for a in db.scalars(stmt)]


@router.post("/api/admin/escalate", summary="Escalate overdue issues now (admin)")
def admin_escalate(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    return escalate_overdue(db)



# ---- Admin clean-up: delete one photo or a whole report (frees storage) ----

from app.models import Issue, IssueEvent, Report  # noqa: E402
from app.states import EventType  # noqa: E402
from app.storage import get_storage  # noqa: E402


class DeleteResult(BaseModel):
    deleted: str
    report_id: str
    remaining_photos: int
    issue_id: str | None
    issue_deleted: bool


def _detach_from_issue(db: Session, report: Report, admin: User) -> tuple[str | None, bool]:
    """Lower the issue's report count; remove the issue if this was its last report."""
    issue = db.get(Issue, report.issue_id) if report.issue_id else None
    if issue is None:
        return None, False
    report.issue_id = None
    issue.report_count = max(0, issue.report_count - 1)
    db.flush()
    if db.scalar(select(func.count()).select_from(Report).where(Report.issue_id == issue.id)) == 0:
        for e in list(issue.events):
            db.delete(e)
        db.delete(issue)
        return issue.id, True
    db.add(IssueEvent(issue_id=issue.id, type=EventType.REPORT_ADDED, actor=admin.email,
                      note=f"Report {report.id} deleted by admin"))
    return issue.id, False


@router.delete("/api/admin/reports/{report_id}", response_model=DeleteResult)
def delete_report(report_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> DeleteResult:
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(404, "Report not found")
    storage = get_storage()
    for key in report.photo_uris or []:
        storage.delete(key)
    issue_id, issue_deleted = _detach_from_issue(db, report, admin)
    db.delete(report)
    db.commit()
    return DeleteResult(deleted="report", report_id=report_id, remaining_photos=0,
                        issue_id=issue_id, issue_deleted=issue_deleted)


@router.delete("/api/admin/reports/{report_id}/frames/{index}", response_model=DeleteResult)
def delete_photo(report_id: str, index: int, admin: User = Depends(require_admin),
                 db: Session = Depends(get_db)) -> DeleteResult:
    report = db.get(Report, report_id)
    if report is None or not 0 <= index < len(report.photo_uris or []):
        raise HTTPException(404, "Photo not found")
    get_storage().delete(report.photo_uris[index])
    report.photo_uris = [k for i, k in enumerate(report.photo_uris) if i != index]
    det = dict(report.detections or {})
    if det.get("frames"):  # keep detection boxes aligned with the remaining photos
        frames = [f for i, f in enumerate(det["frames"]) if i != index]
        det["frames"] = [{**f, "frame": i} for i, f in enumerate(frames)]
        best = det.get("best_frame") or 0
        det["best_frame"] = 0 if best == index or not frames else best - (best > index)
        report.detections = det
    if report.issue_id:
        db.add(IssueEvent(issue_id=report.issue_id, type=EventType.REPORT_ADDED, actor=admin.email,
                          note=f"Photo {index + 1} of report {report.id} deleted by admin"))
    db.commit()
    return DeleteResult(deleted="photo", report_id=report_id, remaining_photos=len(report.photo_uris),
                        issue_id=report.issue_id, issue_deleted=False)
