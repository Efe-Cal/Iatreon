import unittest
import os
import uuid
from types import SimpleNamespace
from unittest.mock import patch


class FakeResearchGraph:
    def __init__(self):
        self.messages = None

    async def astream_events(self, payload, config, version):
        self.messages = payload["messages"]
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": SimpleNamespace(content="research report")},
        }


class ResearchAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_with_user_id_and_no_profile_skips_inference_guidance(self):
        from agents.research import EFFORT_SETTINGS, ResearchAgent

        graph = FakeResearchGraph()
        agent = ResearchAgent.__new__(ResearchAgent)
        agent.agent = graph
        agent.config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        agent.effort = "standard"
        agent.effort_settings = EFFORT_SETTINGS["standard"]
        agent._citation_lookup = {}

        async def fake_get_user_info(user_id):
            return f"# Patient Profile\nUser: {user_id}"

        with patch("agents.research.get_user_info", fake_get_user_info):
            chunks = [
                chunk
                async for chunk in agent.run(
                    None,
                    research_question="What should we check?",
                    user_id="user-1",
                )
            ]

        self.assertEqual(chunks[-1], ("research report", {}))
        prompt = graph.messages[0]["content"]
        self.assertIn("# Patient Profile\nUser: user-1", prompt)
        self.assertIn("# Research Request\nWhat should we check?", prompt)
        self.assertNotIn("Inference Guidance For Search Focus", prompt)

    async def test_doctor_research_uses_linked_local_intake(self):
        from agents.doctor import DoctorAgent
        from db.schemas import IntakeSessionData
        from local_worker import store

        user_id = uuid.uuid4()
        chat_session_id = uuid.uuid4()
        intake_id = uuid.uuid4()

        class FakeResearchAgent:
            seen_profile = None
            seen_user_id = None

            def __init__(self, *args, **kwargs):
                pass

            async def run(self, profile, research_question=None, user_id=None):
                FakeResearchAgent.seen_profile = profile
                FakeResearchAgent.seen_user_id = user_id
                yield ("doctor research", {})

        intake_record = {
            "id": str(intake_id),
            "user_id": str(user_id),
            "profile": {
                "chief_complaint": "Chest pain",
                "symptoms": [{"name": "chest pain"}],
                "red_flags": ["shortness of breath"],
                "medical_summary": "Chest pain with dyspnea.",
            },
            "transcript": "transcript",
            "completed_at": None,
        }
        agent = DoctorAgent.__new__(DoctorAgent)
        agent.user_id = str(user_id)
        agent.chat_session_id = chat_session_id

        with (
            patch.dict(os.environ, {"IATREON_LOCAL_WORKER": "1"}),
            patch.object(store, "get_intake_by_chat_session", return_value=intake_record),
            patch.object(store, "save_research"),
            patch("agents.doctor.ResearchAgent", FakeResearchAgent),
        ):
            result = await agent._call_research_agent("what now?", "fast")

        self.assertEqual(result, "doctor research")
        self.assertIsInstance(FakeResearchAgent.seen_profile, IntakeSessionData)
        self.assertEqual(FakeResearchAgent.seen_profile.chief_complaint, "Chest pain")
        self.assertEqual(FakeResearchAgent.seen_user_id, str(user_id))


if __name__ == "__main__":
    unittest.main()
