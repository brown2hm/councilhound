"""Official City of Fairfax development-project directory."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from councilhound.db.models import CityProject, Entity

from app.db import db_session

router = APIRouter()


def _serialize(row: CityProject, entity: Entity | None) -> dict:
    return {
        "slug": row.external_slug,
        "name": row.name,
        "project_type": row.project_type,
        "division": row.division,
        "official_status": row.official_status,
        "description": row.description,
        "address": row.address,
        "applicant": row.applicant,
        "detail_url": row.detail_url,
        "image_url": row.image_url,
        "entity_slug": entity.canonical_slug if entity else None,
        "entity_status": entity.current_status if entity else None,
        "lat": float(row.lat) if row.lat is not None else None,
        "lng": float(row.lng) if row.lng is not None else None,
        "synced_at": row.synced_at.isoformat() if row.synced_at else None,
    }


@router.get("/")
def list_development_projects(
    project_type: str | None = Query(None),
    division: str | None = Query(None),
    status: str | None = Query(None),
    q: str | None = Query(None),
    session: Session = Depends(db_session),
):
    query = (
        select(CityProject, Entity)
        .outerjoin(Entity, CityProject.entity_id == Entity.id)
        .order_by(CityProject.name)
    )
    if project_type:
        query = query.where(CityProject.project_type == project_type)
    if division:
        query = query.where(CityProject.division == division)
    if status:
        query = query.where(CityProject.official_status == status)
    if q:
        query = query.where(CityProject.name.ilike(f"%{q}%"))
    return [_serialize(row, entity) for row, entity in session.execute(query).all()]
