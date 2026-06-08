from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import diagnosis, intake, research, user

app = FastAPI()

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