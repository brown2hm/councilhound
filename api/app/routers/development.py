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
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from councilhound.config import JURISDICTION
from councilhound.db.models import CityProject, Entity, ProjectEvaluation, WikiPage

from app.db import db_session
from app.wiki import entity_has_wiki, wiki_payload

router = APIRouter()

# The naive per-capita cost method billed every new resident for fixed
# citywide costs and always landed the net low; retired 2026-09-14 along
# with the range that leaned on it. Older stored evaluations still carry
# these rows.
_RETIRED_NOTE = re.compile(r"naive per-capita|both cost framings")
RETIRED_METRICS = {
    "Annual service cost — naive per-capita method",
    "Net annual fiscal impact — naive per-capita method",
    "Net annual fiscal impact (range across both cost methods)",
}

# words too generic to distinguish one project name from another; the
# jurisdiction adds its own name tokens (projects.generic_name_tokens)
_GENERIC_TOKENS = {
    "project", "projects", "improvement", "improvements", "development",
    "redevelopment", "application", "proposal", "amendment", "meeting",
    "phase", "i", "ii", "the", "of", "and", "at", "to",
    "aka", "llc", "lp",
} | {t.lower() for t in JURISDICTION.projects.generic_name_tokens}

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


# Signals that the project's program includes housing the resident-driven
# impact model can work with. Deliberately loose keyword matching over the
# city's own description/requests text — hotel rooms don't count, a remaining
# single-family home doesn't count as a program.
_RESIDENTIAL_HINTS = (
    "dwelling", "residential", "apartment", "townhome", "townhouse",
    "condominium", "multifamily", "multi-family", "senior living",
)

# Corridor/trail projects are analyzable by the bike_lane/trail modules even
# with no housing program — don't label them "no residential program".
_CORRIDOR_HINTS = (
    "bike lane", "bicycle lane", "cycle track", "shared use path",
    "shared-use path", "trail", "greenway", "multimodal", "multi-modal",
    "streetscape",
)


# impact analysis is a per-jurisdiction feature (the County has none yet):
# when off, no project has an evaluation and no gap needs an explanation
_IMPACT = JURISDICTION.features.impact


def _no_analysis_reason(row: CityProject, eval_status: str | None) -> str | None:
    """Why this official project has no published impact analysis — turns a
    silent gap into a legible editorial state. None when one is published
    (or when the jurisdiction has no impact analysis at all)."""
    if not _IMPACT or eval_status == "synthesized":
        return None
    if eval_status is not None:
        return "analysis in preparation"
    text = " ".join(filter(None, [row.description, row.requests])).lower()
    if any(hint in text for hint in _CORRIDOR_HINTS):
        return "not yet evaluated"
    if not any(hint in text for hint in _RESIDENTIAL_HINTS):
        return "no residential program to model"
    if (row.official_status or "").lower().startswith("pre-app") or "potential" in text:
        return "awaiting submitted plans"
    return "not yet evaluated"


def _serialize(row: CityProject, entity: Entity | None, has_evaluation: bool,
               no_analysis_reason: str | None = None,
               has_wiki: bool = False, wiki_pushed_at=None) -> dict:
    return {
        "source": "official",
        "category": "development",
        "no_analysis_reason": no_analysis_reason,
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
        "has_wiki": has_wiki,
        "wiki_pushed_at": wiki_pushed_at.isoformat() if wiki_pushed_at else None,
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
    # one grouped query for wiki presence/freshness across every row
    wiki_by_entity: dict[int, object] = dict(session.execute(
        select(WikiPage.entity_id, func.max(WikiPage.pushed_at))
        .where(WikiPage.kind == "concept")
        .group_by(WikiPage.entity_id)).all())
    items = [
        _serialize(row, entity, _IMPACT and eval_status == "synthesized",
                   no_analysis_reason=_no_analysis_reason(row, eval_status),
                   has_wiki=row.entity_id in wiki_by_entity,
                   wiki_pushed_at=wiki_by_entity.get(row.entity_id))
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
            wiki_pushed = wiki_by_entity.get(entity.id)
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
                "has_wiki": entity.id in wiki_by_entity,
                "wiki_pushed_at": wiki_pushed.isoformat() if wiki_pushed else None,
            })
    return items


@router.get("/{slug}/wiki")
def get_wiki(slug: str, session: Session = Depends(db_session)):
    """The project's OKF wiki (mirrored from the knowledge bundle)."""
    project = session.scalar(
        select(CityProject).where(CityProject.external_slug == slug))
    if project is None or project.entity_id is None:
        raise HTTPException(status_code=404, detail="no wiki for this project")
    entity = session.get(Entity, project.entity_id)
    payload = wiki_payload(session, entity) if entity else None
    if payload is None:
        raise HTTPException(status_code=404, detail="no wiki for this project")
    payload["official_slug"] = project.external_slug
    return payload


@router.get("/{slug}/evaluation")
def get_evaluation(slug: str, session: Session = Depends(db_session)):
    if not _IMPACT:
        raise HTTPException(status_code=404, detail="impact analysis is not available for this jurisdiction")
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

    # flatten module results into one metric list tagged by module; metrics
    # retired from the pipeline are dropped from evaluations stored before
    # the retirement so the site never shows them again
    metrics = []
    for module_result in evaluation.module_results or []:
        for m in module_result.get("metrics", []):
            if m.get("name") in RETIRED_METRICS:
                continue
            metrics.append({**m, "module": module_result.get("module")})
    narrative_notes = [
        note for module_result in evaluation.module_results or []
        for note in module_result.get("narrative_notes", [])
        if not _RETIRED_NOTE.search(note)
    ]
    entity = (session.get(Entity, project.entity_id) if project.entity_id else None)
    has_wiki = entity_has_wiki(session, project.entity_id)
    return {
        "slug": project.external_slug,
        "name": project.name,
        "entity_slug": entity.canonical_slug if entity else None,
        "has_wiki": has_wiki,
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


@router.get("/{slug}")
def get_project(slug: str, session: Session = Depends(db_session)):
    """The full official project record plus which views exist for it — the
    light shell payload behind every tab of the development page. Heavy
    payloads (wiki bodies, evaluation GeoJSON) stay on the sub-endpoints."""
    row = session.scalar(
        select(CityProject).where(CityProject.external_slug == slug))
    if row is None:
        raise HTTPException(status_code=404, detail="unknown project")
    entity = session.get(Entity, row.entity_id) if row.entity_id else None
    eval_row = session.execute(
        select(ProjectEvaluation.status,
               ProjectEvaluation.report_markdown.isnot(None))
        .where(ProjectEvaluation.city_project_id == row.id)).first()
    eval_status, has_report = eval_row if eval_row else (None, False)
    wiki_pushed_at = None
    if entity is not None:
        wiki_pushed_at = session.scalar(
            select(func.max(WikiPage.pushed_at))
            .where(WikiPage.entity_id == entity.id,
                   WikiPage.kind == "concept"))
    return {
        "slug": row.external_slug,
        "name": row.name,
        "entity_slug": entity.canonical_slug if entity else None,
        "entity_status": entity.current_status if entity else None,
        "project_type": row.project_type,
        "division": row.division,
        "official_status": row.official_status,
        "description": row.description,
        "requests": row.requests,
        "address": row.address,
        "applicant": row.applicant,
        "planner_name": row.planner_name,
        "planner_phone": row.planner_phone,
        "planner_email": row.planner_email,
        "detail_url": row.detail_url,
        "image_url": row.image_url,
        "documents": row.documents or [],
        "official_timeline": row.official_timeline or [],
        "lat": float(row.lat) if row.lat is not None else None,
        "lng": float(row.lng) if row.lng is not None else None,
        "synced_at": row.synced_at.isoformat() if row.synced_at else None,
        "has_wiki": entity_has_wiki(session, row.entity_id),
        "wiki_pushed_at": wiki_pushed_at.isoformat() if wiki_pushed_at else None,
        "evaluation_status": eval_status,
        "has_evaluation": _IMPACT and eval_status == "synthesized" and bool(has_report),
        "no_analysis_reason": _no_analysis_reason(row, eval_status),
    }
