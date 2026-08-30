"""Storage Service — HTTP API.

Local (with compose `web` on :8000):

    uvicorn main:app --reload --host 0.0.0.0 --port 8001

The static frontend is served by the `web` nginx container, which proxies
/api to this process so the browser still talks to one origin.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from storage.service import StorageService

# Local page is nginx :8000 while uvicorn is :8001 (see frontend/app.js API_BASE).
_LOCAL_PAGE_ORIGINS = (
    "http://127.0.0.1:8000",
    "http://localhost:8000",
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Chat Storage Service",
        description="Three-layer session storage: Redis / PostgreSQL / pgvector.",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(_LOCAL_PAGE_ORIGINS),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.storage = StorageService()
    app.include_router(router)
    return app


app = create_app()
