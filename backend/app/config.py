from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres@localhost:5432/pothole_triage"
    photo_dir: Path = Path("../data/photos")
    # Set in the cloud: photos go to this private Cloud Storage bucket instead of photo_dir.
    storage_bucket: str = ""
    # Built frontend (npm run build) served by the backend in the cloud; empty = not served.
    static_dir: Path = Path("static")
    # YOLO11s trained on Kaggle (2x T4) on pothole_mix_v2 with lane-marking/manhole negatives.
    # Previous: models/pothole_y11n_640.onnx (5x more lane-marking false alarms).
    model_path: Path = Path("models/pothole_y11s_v2_640.onnx")
    # 0.15 keeps image-level recall at ~86% on held-out close-ups (0.25 gives ~78%).
    detector_conf: float = 0.15
    # enforce: no pothole detected -> report state no_damage, no issue created or merged.
    # advisory: record detections only, never reject for "no pothole" (used by the tests).
    detection_mode: Literal["advisory", "enforce"] = "enforce"
    # A pothole counts as confirmed only at this confidence (held-out close-ups: 99% image
    # precision, 1 of 103 pothole-free photos above it). Boxes between detector_conf and this
    # are "uncertain": the report is held for confirmation instead of accepted.
    accept_conf: float = 0.45
    device_daily_limit: int = 30
    ip_hourly_limit: int = 120
    scheduler_enabled: bool = True  # hourly escalation inside the backend process
    # Signs the login session cookie. MUST be a long random value outside local development.
    secret_key: str = "dev-only-insecure-secret-change-me"
    session_hours: int = 12
    cookie_secure: bool = False  # True behind HTTPS (cloud)
    # Legacy shared token for scripts/tests (X-Authority-Token). Empty = disabled (use logins).
    authority_token: str = ""
    # Cloud Scheduler / scripts call POST /internal/escalate with X-Internal-Token.
    internal_token: str = "change-me"
    cors_origins: list[str] = ["https://localhost:5173", "http://localhost:5173"]

    def resolve(self, p: Path) -> Path:
        return p if p.is_absolute() else (BACKEND_DIR / p).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
