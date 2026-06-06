from fastapi import FastAPI

from api.routes import diagnosis, intake, research

app = FastAPI()

app.include_router(intake.router)
app.include_router(research.router)
app.include_router(diagnosis.router)