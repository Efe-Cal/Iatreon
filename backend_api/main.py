from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from .auth import router as auth_router
from .backup import router as backup_router
from .database import init_db
from .hcai import router as hcai_router
from .limits import close_redis, redis_ready
from .pdf import router as pdf_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    try:
        yield
    finally:
        await close_redis()


app = FastAPI(title="Iatreon Backend API", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(hcai_router)
app.include_router(pdf_router)
app.include_router(backup_router)


@app.get("/health")
async def health() -> dict[str, str]:
    if not await redis_ready():
        raise HTTPException(status_code=503, detail="Redis is unavailable")
    return {"status": "ok", "redis": "ok"}
