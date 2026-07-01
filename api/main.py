from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import diagnosis, intake, research, user, session, doctor, history
from db.db import checkpointer_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    await checkpointer_manager.init_pool()
    try:
        yield
    finally:
        await checkpointer_manager.close_pool()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(intake.router)
app.include_router(research.router)
app.include_router(diagnosis.router)
app.include_router(user.router)
app.include_router(session.router)
app.include_router(doctor.router)
app.include_router(history.router)
