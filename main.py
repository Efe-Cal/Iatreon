from uuid import UUID

from agents.intake import run_intake
from db.repositories import IntakeRepo, ResearchRepo
from db.db import SessionLocal, init_db
from agents.research import ResearchAgent

DEV_USER_ID = UUID('12d6bef5-3a91-4ffc-8044-17758ad8e4d2')

async def main():
    await init_db()
    async with SessionLocal() as session:
        intake_repo = IntakeRepo(session)
        research_repo = ResearchRepo(session)

        intake_session = await intake_repo.create_session(DEV_USER_ID)

        profile, transcript = run_intake()

        await intake_repo.update_session(session_id=intake_session.id, profile=profile, transcript=transcript)

        await intake_repo.complete_session(intake_session.id)
        
        # Get the profile from the database to pass to the research agent
        intake_session = await intake_repo.get_session(intake_session.id)
        
        research_session = await research_repo.create_research_session(
            user_id=DEV_USER_ID,
            intake_session_id=intake_session.id,
        )
        research_agent = ResearchAgent(session, research_repo=research_repo, research_session=research_session)

        research_results = await research_agent.run(intake_session)

        print("Research Agent Results:")
        print(research_results)
        
        citations = await research_agent.find_citation(research_results)
        print("Citation Check:")
        print(citations)

    
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
