"""Phase 5 support: entity/topic tracker - given a canonical_slug, return the
entity's running summary plus every meeting it was mentioned in, in order,
for the "progress over time" view."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/{slug}")
def get_entity(slug: str):
    """TODO: query entities + entity_mentions, ordered by meeting_date."""
    return {"todo": "implement once ingestion (Phase 1-3) has real data"}
