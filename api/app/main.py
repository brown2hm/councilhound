"""
Phase 4-5 API: serves meeting/entity data to the front end and exposes the
RAG "ask a question" endpoint.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import meetings, entities, ask

app = FastAPI(title="CouncilHound API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before any public deployment
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(meetings.router, prefix="/meetings", tags=["meetings"])
app.include_router(entities.router, prefix="/entities", tags=["entities"])
app.include_router(ask.router, prefix="/ask", tags=["ask"])


@app.get("/health")
def health():
    return {"status": "ok"}
