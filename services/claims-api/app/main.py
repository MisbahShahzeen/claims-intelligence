from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import engine
from prometheus_fastapi_instrumentator import Instrumentator

from app.events.consumer import consumer
from app.routers import assessments, auth, claims, documents, stream, users

settings = get_settings()

@asynccontextmanager
async def lifespan(_app: FastAPI):
    await consumer.start()
    try:
        yield
    finally:
        await consumer.stop()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health probes and /metrics are excluded: Kubernetes hits the probes
# every few seconds, and including them would make latency percentiles
# mostly measure probe traffic.
Instrumentator(
    excluded_handlers=["/metrics", "/health/live", "/health/ready"],
).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(claims.router)
app.include_router(assessments.router)
app.include_router(documents.router)
app.include_router(stream.router)


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready")
async def ready(response: Response) -> dict[str, str]:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unready", "database": "unreachable"}
    return {"status": "ready", "database": "reachable"}
