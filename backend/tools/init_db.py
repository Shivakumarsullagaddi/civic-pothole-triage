"""Create the app database and enable PostGIS (one-time, local PostgreSQL).

Reads DATABASE_URL from backend/.env. Connects to the `postgres` maintenance database with
the same credentials to create the app database if it is missing.

Usage (from backend/):
    python tools/init_db.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.config import get_settings  # noqa: E402


def main() -> None:
    url = make_url(get_settings().database_url)
    dbname = url.database
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": dbname}).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{dbname}"'))
            print(f"Created database {dbname}")
        else:
            print(f"Database {dbname} already exists")

    app_engine = create_engine(url, isolation_level="AUTOCOMMIT")
    with app_engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        version = conn.execute(text("SELECT postgis_full_version()")).scalar()
        print(f"PostGIS enabled: {version.split(' ')[1]}")


if __name__ == "__main__":
    main()
