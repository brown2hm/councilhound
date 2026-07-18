"""Official City of Fairfax development-project directory + impact evaluations.

Evaluations are computed by the local impact-* CLI stages (councilhound.impact)
and persisted whole on project_evaluations rows — this router only reshapes
stored JSON, so it adds no dependencies and no per-request compute.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from councilhound.db.models import CityProject, Entity, ProjectEvaluation

from app.db import db_session

router = APIRouter()


def _serialize(row: CityProject, entity: Entity | None, has_evaluation: bool) -> dict:
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
        "has_evaluation": has_evaluation,
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
        select(CityProject, Entity, ProjectEvaluation.status)
        .outerjoin(Entity, CityProject.entity_id == Entity.id)
        .outerjoin(ProjectEvaluation, ProjectEvaluation.city_project_id == CityProject.id)
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
    return [
        _serialize(row, entity, eval_status == "synthesized")
        for row, entity, eval_status in session.execute(query).all()
    ]


@router.get("/{slug}/evaluation")
def get_evaluation(slug: str, session: Session = Depends(db_session)):
    result = session.execute(
        select(CityProject, ProjectEvaluation)
        .join(ProjectEvaluation, ProjectEvaluation.city_project_id == CityProject.id)
        .where(CityProject.external_slug == slug)
    ).first()
    if result is None:
        raise HTTPException(status_code=404, detail="no evaluation for this project")
    project, evaluation = result
    if evaluation.status != "synthesized" or not evaluation.report_markdown:
        raise HTTPException(status_code=404, detail="evaluation not yet synthesized")

    # flatten module results into one metric list tagged by module
    metrics = []
    for module_result in evaluation.module_results or []:
        for m in module_result.get("metrics", []):
            metrics.append({**m, "module": module_result.get("module")})
    narrative_notes = [
        note for module_result in evaluation.module_results or []
        for note in module_result.get("narrative_notes", [])
    ]
    entity = (session.get(Entity, project.entity_id) if project.entity_id else None)
    return {
        "slug": project.external_slug,
        "name": project.name,
        "entity_slug": entity.canonical_slug if entity else None,
        "official_status": project.official_status,
        "detail_url": project.detail_url,
        "status": evaluation.status,
        "spec": evaluation.spec,
        "report_markdown": evaluation.report_markdown,
        "metrics": metrics,
        "narrative_notes": narrative_notes,
        "assumptions": evaluation.assumptions or [],
        "sources": evaluation.sources or [],
        "map_layers": evaluation.map_layers or {},
        "report_model": evaluation.report_model,
        "report_prompt_version": evaluation.report_prompt_version,
        "synthesized_at": evaluation.synthesized_at.isoformat() if evaluation.synthesized_at else None,
    }
