"""Official City of Fairfax development-project directory + impact evaluations.

Evaluations are computed by the local impact-* CLI stages (councilhound.impact)
and persisted whole on project_evaluations rows — this router only reshapes
stored JSON, so it adds no dependencies and no per-request compute.

Meeting-derived project entities are deduplicated against official records
(distinctive-token containment) and classified into built-environment
"development" items vs. other "civic" topics (plans, contracts, studies) so
the directory never conflates the three sources.
"""
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from councilhound.db.models import CityProject, Entity, ProjectEvaluation

from app.db import db_session

router = APIRouter()

# words too generic to distinguish one project name from another
_GENERIC_TOKENS = {
    "project", "projects", "improvement", "improvements", "development",
    "redevelopment", "application", "proposal", "amendment", "meeting",
    "phase", "i", "ii", "the", "of", "and", "at", "to", "city", "fairfax",
    "aka", "va", "llc", "lp",
}

# built-environment vocabulary: private development + physical city works
_DEVELOPMENT_PATTERNS = re.compile(
    r"\b(redevelopments?|developments?|mixed.use|townhomes?|townhouses?|"
    r"apartments?|multifamily|residential|subdivisions?|rezoning|rezone|"
    r"zoning|special use|site plan|gdp|shopping centers?|hotels?|storage|"
    r"drive.through|drive.thru|carwash|car wash|restaurants?|retail|"
    r"office building|sidewalks?|trails?|intersections?|roadway|road diet|"
    r"streetscape|pump stations?|sewer|stormwater|outfall|bus stops?|"
    r"pedestrian|bicycle|bike|multimodal|paving|dredging|landscape|"
    r"park renovation|undergrounding|extension|connector)\b",
    re.IGNORECASE,
)
# a leading street number reads as an address — but not a leading year
_ADDRESS_PATTERN = re.compile(r"^(?!(?:19|20)\d{2}\s)\d{3,5}\s")


def _tokens(name: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", name.lower())
    return {w for w in words if w not in _GENERIC_TOKENS}


def _is_duplicate(entity_tokens: set[str], official_token_sets: list[set[str]]) -> bool:
    """A meeting-derived name duplicates an official record when either
    distinctive-token set contains the other ('Davies proposal' <-> 'Davies
    Property'; 'Blenheim Boulevard Multimodal project' <-> the official
    Blenheim record)."""
    if not entity_tokens:
        return True  # nothing distinctive left — never worth a second row
    for official in official_token_sets:
        if official and (official <= entity_tokens or entity_tokens <= official):
            return True
    return False


def _category(name: str) -> str:
    if _ADDRESS_PATTERN.match(name) or _DEVELOPMENT_PATTERNS.search(name):
        return "development"
    return "civic"


def _serialize(row: CityProject, entity: Entity | None, has_evaluation: bool) -> dict:
    return {
        "source": "official",
        "category": "development",
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
    items = [
        _serialize(row, entity, eval_status == "synthesized")
        for row, entity, eval_status in session.execute(query).all()
    ]

    # project entities surfaced from MEETING context (agendas/minutes/
    # discussion) that the city's official directory doesn't list — shown
    # separately so official records and meeting-derived mentions are never
    # conflated. Deduplicated against official names; tagged with category
    # "development" (built environment) or "civic" (plans, contracts,
    # studies, programs). Official-only filters suppress this section.
    if not (project_type or division or status):
        official_token_sets = [
            _tokens(name) for (name,) in session.execute(select(CityProject.name))
        ]
        linked = select(CityProject.entity_id).where(CityProject.entity_id.isnot(None))
        eq = (select(Entity)
              .where(Entity.entity_type == "project", Entity.id.not_in(linked))
              .order_by(Entity.name))
        if q:
            eq = eq.where(Entity.name.ilike(f"%{q}%"))
        seen_tokens: list[set[str]] = []
        for entity in session.scalars(eq).all():
            tokens = _tokens(entity.name)
            if _is_duplicate(tokens, official_token_sets):
                continue
            if _is_duplicate(tokens, seen_tokens):  # collapse near-identical mentions
                continue
            seen_tokens.append(tokens)
            items.append({
                "source": "meetings",
                "category": _category(entity.name),
                "slug": None,
                "name": entity.name,
                "project_type": None,
                "division": None,
                "official_status": None,
                "description": None,
                "address": None,
                "applicant": None,
                "detail_url": None,
                "image_url": None,
                "entity_slug": entity.canonical_slug,
                "entity_status": entity.current_status,
                "lat": None,
                "lng": None,
                "synced_at": None,
                "has_evaluation": False,
            })
    return items


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
