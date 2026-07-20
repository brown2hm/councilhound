"""
Phase 4-5 API: serves meeting/entity data to the front end and exposes the
RAG "ask a question" endpoint.
"""
import os
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import (
    meetings, entities, ask, development, members, search, subscriptions,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Load the embedding model before serving traffic — torch import +
    # model load costs ~20s on shared CPU, which must never land on a
    # user's first /ask (it stampedes with health checks and looks hung).
    from councilhound.embeddings.embed import embed_query

    await anyio.to_thread.run_sync(embed_query, "warmup")
    yield


app = FastAPI(title="CouncilHound API", lifespan=lifespan)

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
app.include_router(development.router, prefix="/development", tags=["development"])
app.include_router(ask.router, prefix="/ask", tags=["ask"])
app.include_router(members.router, prefix="/members", tags=["members"])
app.include_router(search.router, prefix="/search", tags=["search"])
app.include_router(subscriptions.router, prefix="/subscriptions", tags=["subscriptions"])


@app.get("/health")
def health():
    return {"status": "ok"}
