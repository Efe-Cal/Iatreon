import asyncio
import base64
import io
import json
import logging
import uuid
from types import SimpleNamespace

import pytest


pytest.importorskip("sqlcipher3")

from local_worker import store
from local_worker.errors import NotFoundError


def _key(seed: bytes) -> str:
    return base64.b64encode(seed * 32).decode("ascii")


@pytest.fixture()
def initialized_store(tmp_path):
    store._reset_for_tests()
    store.initialize(str(tmp_path / "local.sqlite3"), _key(b"o"))
    try:
        yield
    finally:
        store._reset_for_tests()


def _seed_owned_intake():
    owner_id = str(uuid.uuid4())
    session_id = store.create_session(owner_id)
    intake_id = str(uuid.uuid4())
    store.save_intake(
        owner_id,
        intake_id,
        session_id,
        {"chief_complaint": "owner-only symptom", "medical_summary": "owner-only summary"},
        "owner-only transcript",
    )
    return owner_id, session_id, intake_id


def test_store_rejects_cross_user_records_links_and_citations(initialized_store):
    owner_id, owner_session_id, intake_id = _seed_owned_intake()
    other_id = str(uuid.uuid4())
    other_session_id = store.create_session(other_id)
    research_id = str(uuid.uuid4())
    store.save_research(owner_id, research_id, owner_session_id, "fast", "owner report", {1: {"text": "owner-only citation"}})

    assert store.get_intake(other_id, intake_id) is None
    assert store.get_intake_by_chat_session(other_id, owner_session_id) is None
    assert store.get_citation_text(other_id, research_id, 1) == ""

    with pytest.raises(NotFoundError):
        store.link_intake_session(other_id, owner_session_id, intake_id)
    with pytest.raises(NotFoundError):
        store.link_doctor_session(other_id, owner_session_id, str(uuid.uuid4()))
    with pytest.raises(NotFoundError):
        store.save_intake(other_id, intake_id, other_session_id, {}, "overwrite")
    with pytest.raises(NotFoundError):
        store.save_research(other_id, research_id, other_session_id, "fast", "overwrite", {})
    with pytest.raises(NotFoundError):
        store.save_diagnosis(other_id, str(uuid.uuid4()), intake_id, other_session_id, {}, None, "user")


def test_services_reject_foreign_chat_or_intake_before_agent_work(initialized_store):
    from local_worker.models import ChatRequest, CitationTextRequest, ResearchRequest
    from local_worker.services.doctor_service import stream_doctor_chat_service
    from local_worker.services.intake_service import stream_intake_chat
    from local_worker.services.research_service import get_citation_text, stream_research

    owner_id, owner_session_id, intake_id = _seed_owned_intake()
    other_id = uuid.uuid4()

    async def consume(stream):
        return [item async for item in stream]

    with pytest.raises(NotFoundError):
        asyncio.run(consume(stream_intake_chat(ChatRequest(user_id=other_id, message="hello", conversation_id=None, session_id=uuid.UUID(owner_session_id)))))
    with pytest.raises(NotFoundError):
        asyncio.run(consume(stream_doctor_chat_service(ChatRequest(user_id=other_id, message="hello", conversation_id=None, session_id=uuid.UUID(owner_session_id)))))
    with pytest.raises(NotFoundError):
        asyncio.run(consume(stream_research(ResearchRequest(user_id=other_id, intake_id=uuid.UUID(intake_id), session_id=None))))
    with pytest.raises(NotFoundError):
        asyncio.run(get_citation_text(CitationTextRequest(user_id=other_id, research_session_id=uuid.uuid4(), citation_num=1)))


def test_doctor_chat_starts_and_resumes_without_intake(initialized_store, monkeypatch):
    from local_worker.models import ChatRequest
    from local_worker.services import doctor_service

    user_id = uuid.uuid4()
    session_id = uuid.UUID(store.create_session(str(user_id)))
    calls = []

    class Doctor:
        def __init__(self, user_id, chat_session_id):
            assert chat_session_id == session_id

        async def run_doctor(self, message, conversation_id):
            calls.append((message, conversation_id))
            yield "Hello"

    monkeypatch.setattr(doctor_service, "DoctorAgent", Doctor)

    async def chat(conversation_id):
        request = ChatRequest(user_id=user_id, session_id=session_id, conversation_id=conversation_id, message="hello")
        return [event async for event in doctor_service.stream_doctor_chat_service(request)]

    started = asyncio.run(chat(None))
    conversation_id = started[0]["conversation_id"]
    resumed = asyncio.run(chat(conversation_id))
    assert resumed[0]["conversation_id"] == conversation_id
    assert calls == [("hello", conversation_id), ("hello", conversation_id)]
    with pytest.raises(NotFoundError):
        asyncio.run(chat(uuid.uuid4()))


def test_intake_chat_keeps_the_server_owned_conversation_id(initialized_store, monkeypatch):
    from local_worker.models import ChatRequest
    from local_worker.services import intake_service

    user_id = uuid.uuid4()
    session_id = uuid.UUID(store.create_session(str(user_id)))

    async def fake_intake(_message, _conversation_id, _user_id):
        if False:
            yield None

    monkeypatch.setattr(intake_service, "run_intake_cli", fake_intake)

    async def first_event(request):
        return await anext(intake_service.stream_intake_chat(request))

    started = asyncio.run(first_event(ChatRequest(user_id=user_id, message="first", conversation_id=None, session_id=session_id)))
    conversation_id = started["conversation_id"]
    resumed = asyncio.run(first_event(ChatRequest(user_id=user_id, message="second", conversation_id=conversation_id, session_id=session_id)))

    assert resumed["conversation_id"] == conversation_id


def test_worker_not_found_response_is_sanitized(monkeypatch):
    from pydantic import BaseModel
    from local_worker import worker

    class Request(BaseModel):
        pass

    async def missing(_request):
        raise NotFoundError("owner-only sentinel")

    output = io.StringIO()
    monkeypatch.setattr(worker, "protocol_stdout", output)
    monkeypatch.setitem(worker.routes, "test/not-found", {"fn": missing, "request_model": Request})

    asyncio.run(worker.handle_message({"id": "request-1", "action": "test/not-found", "input": {}}))

    payload = json.loads(output.getvalue())
    assert payload == {
        "id": "request-1",
        "ok": False,
        "error": "Not found",
        "error_code": "not_found",
        "done": True,
    }
    assert "sentinel" not in output.getvalue()


def test_worker_cancels_active_request_and_rejects_concurrent_work(monkeypatch):
    from pydantic import BaseModel
    from local_worker import worker

    class Request(BaseModel):
        pass

    async def slow(_request):
        await asyncio.sleep(60)

    output = io.StringIO()
    monkeypatch.setattr(worker, "protocol_stdout", output)
    monkeypatch.setattr(worker.sys, "stdin", io.StringIO(
        '{"id":"target","action":"test/slow","input":{}}\n'
        '{"id":"busy","action":"test/slow","input":{}}\n'
        '{"id":"control","action":"worker/cancel","input":{"request_id":"target"}}\n'
    ))
    monkeypatch.setitem(worker.routes, "test/slow", {"fn": slow, "request_model": Request})

    asyncio.run(worker.main())

    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert {response["id"]: response for response in responses}["busy"] == {
        "id": "busy",
        "ok": False,
        "error": "Worker is busy",
        "error_code": "busy",
        "done": True,
    }
    assert {response["id"]: response for response in responses}["target"] == {
        "id": "target",
        "ok": False,
        "error": "Request cancelled",
        "error_code": "cancelled",
        "done": True,
    }


def test_agent_payloads_are_not_logged(monkeypatch, caplog):
    from agents import diagnosis, inference
    from db.schemas import IntakeSessionData

    sentinel = "PHI-SENTINEL-DO-NOT-LOG"
    user_id = uuid.uuid4()

    class DiagnosisGraph:
        async def ainvoke(self, _payload):
            return {"structured_response": {"primary_diagnosis": "test"}}

    async def user_info(*, user_id):
        return sentinel

    diagnosis_agent = diagnosis.DiagnosisAgent.__new__(diagnosis.DiagnosisAgent)
    diagnosis_agent.user_id = user_id
    diagnosis_agent.intake_session = IntakeSessionData(
        id=uuid.uuid4(),
        user_id=user_id,
        chief_complaint=sentinel,
        medical_summary=sentinel,
    )
    diagnosis_agent.research_session = None
    diagnosis_agent.patient_notes = sentinel
    diagnosis_agent.agent = DiagnosisGraph()
    monkeypatch.setattr(diagnosis, "get_user_info", user_info)

    class InferenceGraph:
        async def ainvoke(self, _payload):
            return {"messages": [SimpleNamespace(content=sentinel)]}

    monkeypatch.setattr(inference, "create_agent_by_type", lambda *_args, **_kwargs: InferenceGraph())

    with caplog.at_level(logging.DEBUG):
        diagnosis_result = asyncio.run(anext(diagnosis_agent.diagnose()))
        inference_result = asyncio.run(inference.run_inference(sentinel))

    assert diagnosis_result == {"primary_diagnosis": "test"}
    assert inference_result == sentinel
    assert sentinel not in caplog.text
