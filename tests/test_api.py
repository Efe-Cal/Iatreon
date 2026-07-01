import base64
import uuid
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException


SESSION_KEY = base64.b64encode(b"k" * 32).decode("ascii")


class FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


async def collect(source):
    return [event async for event in source]


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_app_imports_with_expected_routes(self):
        from api.main import app

        paths = {route.path for route in app.routes}
        self.assertIn("/chat/intake", paths)
        self.assertIn("/research", paths)
        self.assertIn("/diagnose", paths)
        self.assertIn("/chat/doctor", paths)
        self.assertIn("/create-session", paths)
        self.assertIn("/history", paths)

    async def test_shared_header_validation(self):
        from api.shared import get_user_id_or_400, require_encryption_context

        with self.assertRaises(HTTPException) as missing_user:
            get_user_id_or_400(FakeRequest())
        self.assertEqual(missing_user.exception.status_code, 400)

        with self.assertRaises(HTTPException) as missing_key:
            require_encryption_context(FakeRequest())
        self.assertEqual(missing_key.exception.status_code, 400)

        with self.assertRaises(HTTPException) as bad_key:
            require_encryption_context(FakeRequest({"X-Session-Key": "not-base64"}))
        self.assertEqual(bad_key.exception.status_code, 400)

    async def test_user_ssh_key_validation_rejects_junk(self):
        from api.routes.user import _validate_ssh_public_key

        with self.assertRaises(ValueError):
            _validate_ssh_public_key("not-a-key")

    async def test_create_session_uses_repo_and_clears_session_key(self):
        from api.routes import session as session_route
        from db.crypto import require_session_kek

        user_id = uuid.uuid4()
        session_id = uuid.uuid4()

        @asynccontextmanager
        async def fake_unit_of_work():
            yield object()

        test_case = self

        class FakeSessionRepo:
            async def create_session(self, db, got_user_id):
                test_case.assertEqual(got_user_id, user_id)
                return SimpleNamespace(id=session_id)

        with (
            patch.object(session_route, "unit_of_work", fake_unit_of_work),
            patch.object(session_route, "SessionRepo", FakeSessionRepo),
        ):
            got = await session_route.create_session(
                user_id,
                FakeRequest({"X-Session-Key": SESSION_KEY}),
            )

        self.assertEqual(got, {"session_id": session_id})
        with self.assertRaises(ValueError):
            require_session_kek()

    async def test_history_route_delegates_and_clears_session_key(self):
        from api.routes import history as history_route
        from db.crypto import require_session_kek

        user_id = uuid.uuid4()
        expected = [{"id": "session-1", "sections": []}]

        @asynccontextmanager
        async def fake_read_only_session():
            yield object()

        test_case = self

        class FakeSessionRepo:
            async def list_history(self, db, got_user_id):
                test_case.assertEqual(got_user_id, str(user_id))
                return expected

        with (
            patch.object(history_route, "read_only_session", fake_read_only_session),
            patch.object(history_route, "SessionRepo", FakeSessionRepo),
        ):
            got = await history_route.history(
                FakeRequest({"X-User-ID": str(user_id), "X-Session-Key": SESSION_KEY}),
            )

        self.assertEqual(got, {"sessions": expected})
        with self.assertRaises(ValueError):
            require_session_kek()

    async def test_intake_stream_requires_user_header(self):
        from api.routes.intake import stream_intake_chat
        from api.shared import ChatRequest

        with self.assertRaises(HTTPException) as exc:
            await collect(
                stream_intake_chat(
                    ChatRequest(message="hi", conversation_id=None, session_id=None),
                    FakeRequest({"X-Session-Key": SESSION_KEY}),
                )
            )
        self.assertEqual(exc.exception.status_code, 400)

    async def test_stream_routes_delegate_and_clear_session_key(self):
        from api.routes import diagnosis, doctor, intake, research
        from api.shared import ChatRequest
        from db.crypto import require_session_kek

        headers = {"X-User-ID": str(uuid.uuid4()), "X-Session-Key": SESSION_KEY}
        conversation_id = uuid.uuid4()
        session_id = uuid.uuid4()

        async def fake_intake_service(chat_request, user_id):
            yield {"type": "message", "content": chat_request.message, "user_id": user_id}

        async def fake_doctor_service(chat_request, user_id):
            yield {"type": "message", "content": chat_request.message, "user_id": user_id}

        async def fake_research_service(intake_id, user_id, got_session_id, effort):
            yield {
                "type": "research_complete",
                "intake_id": str(intake_id),
                "session_id": str(got_session_id),
                "effort": effort,
                "user_id": user_id,
            }

        async def fake_diagnosis_service(intake_id, user_id, got_session_id):
            yield {"type": "diagnosis_complete", "intake_id": str(intake_id), "user_id": user_id}

        with (
            patch.object(intake, "stream_intake_chat_service", fake_intake_service),
            patch.object(doctor, "stream_doctor_chat_service", fake_doctor_service),
            patch.object(research, "stream_research_service", fake_research_service),
            patch.object(diagnosis, "stream_diagnosis_service", fake_diagnosis_service),
        ):
            intake_events = await collect(
                intake.stream_intake_chat(
                    ChatRequest(message="hello", conversation_id=conversation_id, session_id=session_id),
                    FakeRequest(headers),
                )
            )
            doctor_events = await collect(
                doctor.stream_doctor_chat(
                    ChatRequest(message="hello", conversation_id=conversation_id, session_id=session_id),
                    FakeRequest(headers),
                )
            )
            research_events = await collect(
                research.stream_research(
                    research.ResearchRequest(
                        intake_id=conversation_id,
                        session_id=session_id,
                        research_effort="fast",
                    ),
                    FakeRequest(headers),
                )
            )
            diagnosis_events = await collect(
                diagnosis.stream_diagnosis(
                    diagnosis.DiagnosisRequest(intake_id=conversation_id, session_id=session_id),
                    FakeRequest(headers),
                )
            )

        self.assertEqual(intake_events[0]["content"], "hello")
        self.assertEqual(doctor_events[0]["content"], "hello")
        self.assertEqual(research_events[0]["effort"], "fast")
        self.assertEqual(diagnosis_events[0]["type"], "diagnosis_complete")
        with self.assertRaises(ValueError):
            require_session_kek()

    async def test_citation_route_delegates(self):
        from api.routes import research

        research_session_id = uuid.uuid4()

        async def fake_get_citation_text(got_session_id, citation_num, user_id):
            self.assertEqual(got_session_id, research_session_id)
            self.assertEqual(citation_num, 2)
            return f"{user_id}: citation text"

        with patch.object(research, "get_citation_text", fake_get_citation_text):
            got = await research.citation_text(
                research.CitationTextRequest(research_session_id=research_session_id, citation_num=2),
                FakeRequest({"X-User-ID": "user-1", "X-Session-Key": SESSION_KEY}),
            )

        self.assertEqual(got, {"text": "user-1: citation text"})

    async def test_research_repo_reserves_citation_numbers(self):
        from db.repositories import ResearchRepo

        user_id = uuid.uuid4()
        session = SimpleNamespace(next_citation_num=4)

        class FakeResult:
            def scalar_one_or_none(self):
                return session

        class FakeDb:
            flushed = False

            async def execute(self, stmt):
                return FakeResult()

            async def flush(self):
                self.flushed = True

        db = FakeDb()
        repo = ResearchRepo(str(user_id))

        start = await repo.reserve_citation_numbers(db, uuid.uuid4(), 3)

        self.assertEqual(start, 4)
        self.assertEqual(session.next_citation_num, 7)
        self.assertTrue(db.flushed)
        with self.assertRaises(ValueError):
            await repo.reserve_citation_numbers(db, uuid.uuid4(), 0)


if __name__ == "__main__":
    unittest.main()
