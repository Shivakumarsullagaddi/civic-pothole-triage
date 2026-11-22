from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2.shape import to_shape
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.lifecycle.transitions import ACTIVE
from app.models import Issue
from app.schemas import IssueDetail, IssueEventOut, IssueOut

router = APIRouter(prefix="/api/issues", tags=["issues"])


def issue_out(issue: Issue) -> dict:
    p = to_shape(issue.location)
    return IssueOut(
        id=issue.id, lat=p.y, lng=p.x, status=issue.status, severity=issue.severity,
        report_count=issue.report_count, escalation_level=issue.escalation_level,
        opened_at=issue.opened_at, due_at=issue.due_at,
        overdue=bool(issue.due_at and issue.status in ACTIVE and issue.due_at < datetime.now(timezone.utc)),
        authority_id=issue.authority_id,
        authority_name=issue.authority.name if issue.authority else None,
        ward_id=issue.ward_id,
        ward_no=issue.ward.ward_no if issue.ward else None,
        ward_name=issue.ward.name if issue.ward else None,
        corporation=issue.ward.corporation if issue.ward else None,
    ).model_dump()


def parse_bbox(bbox: str | None) -> tuple[float, float, float, float] | None:
    if not bbox:
        return None
    try:
        min_lng, min_lat, max_lng, max_lat = (float(v) for v in bbox.split(","))
    except ValueError as exc:
        raise HTTPException(422, "bbox must be minLng,minLat,maxLng,maxLat") from exc
    if min_lng >= max_lng or min_lat >= max_lat:
        raise HTTPException(422, "bbox min values must be less than max values")
    return min_lng, min_lat, max_lng, max_lat


@router.get(".geojson", summary="Issues as a GeoJSON FeatureCollection (public map)")
def issues_geojson(
    bbox: str | None = Query(None, description="minLng,minLat,maxLng,maxLat"),
    status: str | None = Query(None, description="Comma-separated statuses"),
    db: Session = Depends(get_db),
) -> dict:
    q = select(Issue).options(joinedload(Issue.ward), joinedload(Issue.authority))
    if box := parse_bbox(bbox):
        q = q.where(func.ST_Intersects(Issue.location, func.ST_MakeEnvelope(*box, 4326)))
    if status:
        q = q.where(Issue.status.in_([s.strip() for s in status.split(",") if s.strip()]))
    q = q.order_by(Issue.opened_at.desc()).limit(5000)

    features = []
    for issue in db.scalars(q):
        props = issue_out(issue)
        lat, lng = props.pop("lat"), props.pop("lng")
        props["opened_at"] = props["opened_at"].isoformat()
        props["due_at"] = props["due_at"].isoformat() if props["due_at"] else None
        features.append({"type": "Feature", "id": issue.id,
                         "geometry": {"type": "Point", "coordinates": [lng, lat]},
                         "properties": props})
    return {"type": "FeatureCollection", "features": features}


@router.get("/{issue_id}", response_model=IssueDetail)
def get_issue(issue_id: str, db: Session = Depends(get_db)) -> IssueDetail:
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(404, "Issue not found")
    return IssueDetail(
        **issue_out(issue),
        events=[IssueEventOut(type=e.type, from_status=e.from_status, to_status=e.to_status,
                              actor=e.actor, note=e.note, at=e.at) for e in issue.events],
    )
