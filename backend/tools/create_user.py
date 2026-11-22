"""Create (or reset) a staff account from the command line. Use it once for the first admin;
the admin then adds officers from the Admin page.

Usage (from backend/):
    python tools/create_user.py --email admin@example.org --name "GBA Admin" --role admin
    python tools/create_user.py --demo        # admin + 2 officers for local demos (prints passwords)
The password is asked for interactively unless --password is given.
"""

import argparse
import getpass
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.db import SessionLocal, init_schema  # noqa: E402
from app.models import Authority, User  # noqa: E402


def upsert(db, email: str, name: str, password: str, role: str, office_key: str | None = None) -> None:
    office = db.scalar(select(Authority).where(Authority.key == office_key)) if office_key else None
    user = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
    if user is None:
        user = User(email=email.lower(), name=name, role=role)
        db.add(user)
    user.name, user.role, user.active = name, role, True
    user.password_hash = hash_password(password)
    user.authority_id = office.id if office else None
    db.commit()
    print(f"{role:8} {email:32} {password if role else ''}  {office.name if office else ''}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email")
    ap.add_argument("--name", default="")
    ap.add_argument("--role", choices=["officer", "admin"], default="officer")
    ap.add_argument("--password")
    ap.add_argument("--demo", action="store_true", help="create demo admin + officers with random passwords")
    args = ap.parse_args()
    init_schema()
    with SessionLocal() as db:
        if args.demo:
            print("Demo accounts (save these passwords; run again to reset them):")
            upsert(db, "admin@pothole.local", "GBA Admin", secrets.token_urlsafe(9), "admin", "gba")
            upsert(db, "west.officer@pothole.local", "West Corporation Officer", secrets.token_urlsafe(9),
                   "officer", "corp:West")
            upsert(db, "south.officer@pothole.local", "South Corporation Officer", secrets.token_urlsafe(9),
                   "officer", "corp:South")
            return
        if not args.email:
            sys.exit("--email is required (or use --demo)")
        password = args.password or getpass.getpass("Password (min 8 characters): ")
        if len(password) < 8:
            sys.exit("Password must be at least 8 characters")
        upsert(db, args.email, args.name or args.email, password, args.role)


if __name__ == "__main__":
    main()
