"""Simple abuse limits: reports per device per day (database) and per IP per hour (memory).

The per-IP window lives in this process only; with several workers each keeps its own count.
"""

import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Report

_ip_hits: dict[str, deque] = defaultdict(deque)


def check_limits(db: Session, device_id: str, ip: str | None) -> str | None:
    """Returns a reason string if a limit is exceeded, else None (and records the hit)."""
    s = get_settings()
    since = datetime.now(timezone.utc) - timedelta(days=1)
    today = db.scalar(select(func.count()).select_from(Report)
                      .where(Report.device_id == device_id, Report.received_at >= since))
    if today >= s.device_daily_limit:
        return f"limit of {s.device_daily_limit} reports per device per day reached"
    if ip:
        now, window = time.monotonic(), _ip_hits[ip]
        while window and now - window[0] > 3600:
            window.popleft()
        if len(window) >= s.ip_hourly_limit:
            return f"limit of {s.ip_hourly_limit} reports per network address per hour reached"
        window.append(now)
    return None
