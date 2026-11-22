"""Step 11 of the report pipeline: find the ward containing a point and its responsible office."""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Authority, Ward


@dataclass
class Route:
    ward: Ward | None
    authority: Authority | None

    @property
    def covered(self) -> bool:
        return self.ward is not None


def find_ward(db: Session, lat: float, lng: float) -> Ward | None:
    pt = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
    # ST_Intersects (not ST_Contains) so a point exactly on a shared edge still matches;
    # order by corporation and ward_no to make that edge case deterministic.
    return db.scalar(select(Ward).where(func.ST_Intersects(Ward.geom, pt)).order_by(Ward.corporation, Ward.ward_no).limit(1))


def route(db: Session, lat: float, lng: float) -> Route:
    ward = find_ward(db, lat, lng)
    authority = db.get(Authority, ward.authority_id) if ward and ward.authority_id else None
    return Route(ward, authority)
