"""Seed GBA ward boundaries and the authority chain into the app database.

Usage (from backend/):
    python tools/seed_wards.py                       # uses data/raw/gba/bengaluru-gba-369.geojson
    python tools/seed_wards.py --download            # fetch it first (MIT mirror of OpenCity KML)
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal, init_schema  # noqa: E402
from app.seed import seed_gba  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / "data" / "raw" / "gba" / "bengaluru-gba-369.geojson"
MIRROR = "https://raw.githubusercontent.com/kaun-city/kaun/HEAD/apps/web/public/bengaluru-gba-369.geojson"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=Path, default=DEFAULT)
    ap.add_argument("--download", action="store_true")
    args = ap.parse_args()
    if args.download:
        args.file.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(MIRROR, args.file)
    data = json.loads(args.file.read_text(encoding="utf-8"))
    init_schema()
    with SessionLocal() as db:
        print("Seeded:", seed_gba(db, data))


if __name__ == "__main__":
    main()
