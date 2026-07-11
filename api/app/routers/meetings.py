"""Phase 5 support: list/filter meetings, get a single meeting's detail
(agenda items, votes, linked documents) for the timeline/dashboard view."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_meetings():
    """TODO: query meetings table, support filters by date range/type."""
    return {"todo": "implement once ingestion (Phase 1-3) has real data"}
