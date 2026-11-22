import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import accounts, authority, issues, reports, stats, wards
from app.config import get_settings
from app.db import SessionLocal, db_status, init_schema
from app.pipeline.detect import detector_status

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if not settings.storage_bucket:
        settings.resolve(settings.photo_dir).mkdir(parents=True, exist_ok=True)
    detector_status()  # load the model at startup, not on the first report
    scheduler = None
    if db_status()["ok"]:
        init_schema()
        if settings.scheduler_enabled:
            scheduler = start_scheduler()
    else:
        log.warning("Database not reachable at startup; /health will show why.")
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


def run_escalation() -> None:
    from app.lifecycle.escalation import escalate_overdue

    with SessionLocal() as db:
        result = escalate_overdue(db)
    if result["overdue"]:
        log.info("Escalation: %s", result)


def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(run_escalation, "interval", hours=1, id="escalate", max_instances=1, coalesce=True)
    scheduler.start()
    return scheduler


app = FastAPI(title="Civic Pothole Triage", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(reports.router)
app.include_router(issues.router)
app.include_router(wards.router)
app.include_router(authority.router)
app.include_router(stats.router)
app.include_router(accounts.router)


@app.get("/health", tags=["system"])
def health() -> dict:
    settings = get_settings()
    db = db_status()
    return {
        "status": "ok" if db["ok"] else "degraded",
        "database": db,
        "model": {**detector_status(), "mode": settings.detection_mode},
    }


# ---- Built frontend (cloud): serve the single-page app from the same origin as the API ----
_static = get_settings().resolve(get_settings().static_dir)
if (_static / "index.html").exists():
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        """Static files when they exist, otherwise index.html so client-side routes work."""
        if path.startswith(("api/", "internal/", "health")):
            from fastapi import HTTPException

            raise HTTPException(404, "Not found")
        f = (_static / path).resolve()
        if path and f.is_file() and f.is_relative_to(_static):
            return FileResponse(f)
        return FileResponse(_static / "index.html", headers={"Cache-Control": "no-cache"})
