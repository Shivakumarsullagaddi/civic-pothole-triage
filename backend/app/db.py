from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def db_status() -> dict:
    """Report whether the database and PostGIS are reachable. Never raises."""
    try:
        with engine.connect() as conn:
            postgis = conn.execute(text("SELECT postgis_lib_version()")).scalar()
        return {"ok": True, "postgis": postgis}
    except Exception as exc:  # noqa: BLE001 - health must not crash
        return {"ok": False, "error": type(exc).__name__, "detail": str(exc).splitlines()[0]}


def init_schema() -> None:
    """Create tables. No migrations in the prototype."""
    from app import models  # noqa: F401 - registers tables on Base

    Base.metadata.create_all(engine)
