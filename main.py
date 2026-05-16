import uuid
from agents.intake import run_intake
from db.repositories import IntakeRepo
from db.db import SessionLocal, init_db

async def main():
    await init_db()

    async with SessionLocal() as session:
        intake_repo = IntakeRepo(session)

        intake_session = await intake_repo.create_session(uuid.uuid4())

        profile, transcript = run_intake()

        await intake_repo.update_session(session_id=intake_session.id, profile=profile, transcript=transcript)

        await intake_repo.complete_session(intake_session.id)

        intake_session = await intake_repo.get_session(intake_session.id)

        # Switch to inference agent        
    
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
