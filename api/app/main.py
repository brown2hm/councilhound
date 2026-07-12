"""
Phase 4-5 API: serves meeting/entity data to the front end and exposes the
RAG "ask a question" endpoint.
"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import meetings, entities, ask

app = FastAPI(title="CouncilHound API")

# Comma-separated origins; "*" only for local dev. Only the Ask page calls
# the API from the browser — everything else is server-to-server.
_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(meetings.router, prefix="/meetings", tags=["meetings"])
app.include_router(entities.router, prefix="/entities", tags=["entities"])
app.include_router(ask.router, prefix="/ask", tags=["ask"])


@app.get("/health")
def health():
    return {"status": "ok"}
