import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import router as v1_router
from app.config.env import load_dotenv
from app.db.session import init_db
from app.jobs.scheduler import shutdown_scheduler, start_scheduler

load_dotenv()

APP_ENV = os.getenv("APP_ENV", "development")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    # Startup must stay fast: the catch-up run is queued as a background job so
    # the API can serve the already persisted digest immediately.
    start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()


app = FastAPI(title="AI Daily API", version="0.1.0", lifespan=lifespan)

# Development-only CORS. Do not use wildcard origins in production.
if APP_ENV == "development":
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
