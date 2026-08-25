"""Storage Service — HTTP API + static frontend hosting.

Run from the backend/ directory:

    uvicorn main:app --reload --port 8000

The static frontend (frontend/) is served at "/" by this same process,
so the browser talks to one origin: /api/... for storage, everything else is the
static site. API routes are registered before the static catch-all mount.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routes import router
from storage.service import StorageService

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def create_app() -> FastAPI:
    app = FastAPI(
        title="Chat Storage Service",
        description="Three-layer session storage: Redis / PostgreSQL / pgvector.",
        version="0.1.0",
    )
    app.state.storage = StorageService()

    # API routes first so /api/... is handled before the static catch-all.
    app.include_router(router)

    # Serve the existing static frontend (index.html / app.css / app.js / vendor).
    if FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

    return app


app = create_app()
