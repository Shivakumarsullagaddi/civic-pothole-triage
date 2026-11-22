import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Authority, Ward
from app.pipeline.route import route
from app.schemas import WardOut

router = APIRouter(prefix="/api/wards", tags=["wards"])

# About 10 m tolerance: plenty for drawing boundaries, a fraction of the full file size.
SIMPLIFY_DEG = 0.0001


def chain(db: Session, authority: Authority | None) -> list[str]:
    names = []
    while authority is not None and len(names) < 10:
        names.append(authority.name)
        authority = db.get(Authority, authority.parent_id) if authority.parent_id else None
    return names


@router.get(".geojson", summary="Ward boundaries (simplified) for the map")
def wards_geojson(db: Session = Depends(get_db)) -> Response:
    rows = db.execute(
        select(Ward.ward_no, Ward.name, Ward.name_kn, Ward.corporation, Ward.zone_name,
               func.ST_AsGeoJSON(func.ST_SimplifyPreserveTopology(Ward.geom, SIMPLIFY_DEG), 5))
        .order_by(Ward.corporation, Ward.ward_no)
    ).all()
    features = [
        {"type": "Feature",
         "geometry": json.loads(geom),
         "properties": {"ward_no": no, "name": name, "name_kn": kn, "corporation": corp, "zone": zone}}
        for no, name, kn, corp, zone, geom in rows
    ]
    body = json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False)
    return Response(body, media_type="application/geo+json",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/lookup", response_model=WardOut, summary="Which ward and office handle this point?")
def lookup(lat: float = Query(..., ge=-90, le=90), lng: float = Query(..., ge=-180, le=180),
           db: Session = Depends(get_db)) -> WardOut:
    r = route(db, lat, lng)
    if r.ward is None:
        raise HTTPException(404, "Outside the Greater Bengaluru Authority wards")
    return WardOut(ward_no=r.ward.ward_no, name=r.ward.name, name_kn=r.ward.name_kn,
                   corporation=r.ward.corporation, zone_name=r.ward.zone_name,
                   authority=r.authority.name if r.authority else None,
                   escalation_chain=chain(db, r.authority))
