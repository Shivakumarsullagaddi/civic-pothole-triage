"""Staff login: argon2 password hashes + a signed, httpOnly session cookie.

Roles: officer (sees and acts on all issues) and admin (also manages accounts, runs escalation).
Citizens never log in. A legacy shared token (X-Authority-Token) still works for scripts and
tests when AUTHORITY_TOKEN is set; it is empty (disabled) by default.
"""

import secrets
import time
from collections import defaultdict, deque

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Cookie, Depends, Header, HTTPException, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User

COOKIE = "pt_session"
ROLES = ("officer", "admin")
_hasher = PasswordHasher()
_attempts: dict[str, deque] = defaultdict(deque)  # failed logins per email (this process)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def check_password_rules(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(422, "Password must be at least 8 characters")


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="pothole-session")


def set_session(response: Response, user: User) -> None:
    s = get_settings()
    response.set_cookie(COOKIE, _serializer().dumps({"uid": user.id}), max_age=s.session_hours * 3600,
                        httponly=True, secure=s.cookie_secure, samesite="lax", path="/")


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def too_many_attempts(email: str) -> bool:
    window, now = _attempts[email.lower()], time.monotonic()
    while window and now - window[0] > 300:
        window.popleft()
    return len(window) >= 5  # 5 failures per 5 minutes


def record_failure(email: str) -> None:
    _attempts[email.lower()].append(time.monotonic())


def current_user(pt_session: str | None = Cookie(default=None), db: Session = Depends(get_db)) -> User | None:
    if not pt_session:
        return None
    try:
        data = _serializer().loads(pt_session, max_age=get_settings().session_hours * 3600)
    except (BadSignature, SignatureExpired):
        return None
    user = db.get(User, data.get("uid"))
    return user if user and user.active else None


def require_authority(user: User | None = Depends(current_user),
                      x_authority_token: str = Header(default="")) -> str:
    """Officer or admin. Returns the actor name recorded in issue history."""
    if user is not None:
        return user.email
    token = get_settings().authority_token
    if token and x_authority_token and secrets.compare_digest(x_authority_token, token):
        return "authority"
    raise HTTPException(401, "Sign in as an authority officer")


def require_admin(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(401, "Sign in as an admin")
    if user.role != "admin":
        raise HTTPException(403, "Admins only")
    return user
