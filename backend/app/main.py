import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import router as v1_router
from app.config.env import load_dotenv
from app.config.environment import app_env, is_development
from app.db.session import get_engine, init_db
from app.jobs.scheduler import shutdown_scheduler, start_scheduler
from app.services.news_search import BACKEND_LIKE, backend_label, ensure_index

logger = logging.getLogger(__name__)

load_dotenv()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    # Existing articles have to become searchable the first time this phase runs,
    # which happens here rather than in init_db so the (potentially large) fill
    # is explicit. Without FTS5 this just reports the fallback and moves on.
    stats = ensure_index(get_engine())
    logger.info("Search backend: %s", backend_label(stats.backend))
    if stats.backend != BACKEND_LIKE:
        logger.info("search index: articles=%s indexed=%s", stats.articles, stats.indexed)
    # Startup must stay fast: the catch-up run is queued as a background job so
    # the API can serve the already persisted digest immediately.
    start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()


app = FastAPI(title="AI Daily API", version="0.1.0", lifespan=lifespan)

logger.info("APP_ENV=%s", app_env())

# Development-only CORS. Do not use wildcard origins in production.
if is_development():
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

app.include_router(v1_router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
