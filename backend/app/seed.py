"""Load ward boundaries and the authority chain (ward -> zone -> corporation -> GBA).

Input is the GBA 369-ward GeoJSON (December 2025), public boundary data of the Greater
Bengaluru Authority.
Re-running is safe: rows are matched by stable keys and updated in place.
No contact emails are invented; `email` stays empty until an official one is added.
"""

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Authority, Ward


def _authority(db: Session, key: str, name: str, level: str, parent: Authority | None,
               name_kn: str | None = None) -> Authority:
    a = db.scalar(select(Authority).where(Authority.key == key))
    if a is None:
        a = Authority(key=key, name=name, level=level)
        db.add(a)
    a.name, a.name_kn, a.level = name, name_kn, level
    a.parent_id = parent.id if parent else None
    db.flush()
    return a


def seed_gba(db: Session, geojson: dict) -> dict:
    gba = _authority(db, "gba", "Greater Bengaluru Authority", "gba", None, "ಗ್ರೇಟರ್ ಬೆಂಗಳೂರು ಪ್ರಾಧಿಕಾರ")
    corps: dict[str, Authority] = {}
    zones: dict[tuple[str, str], Authority] = {}
    wards = 0
    for f in geojson["features"]:
        p = f["properties"]
        corp_name = p["corporation"]
        if corp_name not in corps:
            corps[corp_name] = _authority(
                db, f"corp:{corp_name}", f"Bengaluru {corp_name} City Corporation", "corporation",
                gba, p.get("corporation_kn"))
        zkey = (corp_name, p.get("zone_name") or p.get("zone") or "Zone")
        if zkey not in zones:
            zones[zkey] = _authority(
                db, f"zone:{corp_name}:{zkey[1]}", f"{zkey[1]} Zone ({corp_name} Corporation)", "zone",
                corps[corp_name])
        office = _authority(
            db, f"ward:{corp_name}:{p['ward_no']}",
            f"Ward {p['ward_no']} {p['ward_name']} office ({corp_name})", "ward",
            zones[zkey], p.get("ward_name_kn"))

        geom = func.ST_Multi(func.ST_MakeValid(func.ST_SetSRID(
            func.ST_GeomFromGeoJSON(json.dumps(f["geometry"])), 4326)))
        ward = db.scalar(select(Ward).where(Ward.corporation == corp_name, Ward.ward_no == p["ward_no"]))
        if ward is None:
            ward = Ward(ward_no=p["ward_no"], corporation=corp_name)
            db.add(ward)
        ward.name, ward.name_kn = p["ward_name"], p.get("ward_name_kn")
        ward.corporation, ward.zone_name = corp_name, zkey[1]
        ward.geom = func.ST_CollectionExtract(geom, 3)  # keep polygon parts only
        ward.authority_id = office.id
        wards += 1
    db.commit()
    return {"wards": wards, "zones": len(zones), "corporations": len(corps)}
