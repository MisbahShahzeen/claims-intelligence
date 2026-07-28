from fastapi import FastAPI, Response, status
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import engine

settings = get_settings()

app = FastAPI(title=settings.app_name)


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
