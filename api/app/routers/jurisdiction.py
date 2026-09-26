"""GET /jurisdiction/ — the display config the front end renders from."""
from fastapi import APIRouter, Response

from app.jurisdiction import public_payload

router = APIRouter()


@router.get("/")
def jurisdiction(response: Response):
    response.headers["Cache-Control"] = "public, max-age=3600"
    return public_payload()
