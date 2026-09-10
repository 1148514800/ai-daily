import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import router as v1_router

APP_ENV = os.getenv("APP_ENV", "development")

app = FastAPI(title="AI Daily API", version="0.1.0")

# Development-only CORS. Do not use wildcard origins in production.
if APP_ENV == "development":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

app.include_router(v1_router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
