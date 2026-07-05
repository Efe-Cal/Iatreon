import sys
import json
import asyncio
import contextlib
import inspect
import os
from pathlib import Path
import traceback
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("IATREON_LOCAL_WORKER", "1")

routes = {}
protocol_stdout = sys.stdout


def route(name: str, request_model: type[BaseModel]):
    def decorator(fn):
        routes[name] = {"fn": fn, "request_model": request_model}
        return fn
    return decorator

from models import (
    ChatRequest,
    CitationTextRequest,
    DiagnosisRequest,
    HistoryRequest,
    ResearchRequest,
    SessionCreateRequest,
    UserProfileUpdateRequest,
)
from local_worker import store
from services.diagnosis_service import stream_diagnosis
from services.intake_service import stream_intake_chat
from services.doctor_service import stream_doctor_chat_service
from services.research_service import get_citation_text, stream_research


@route("session/create", SessionCreateRequest)
async def create_session(req: SessionCreateRequest):
    return {"session_id": store.create_session(str(req.user_id))}


@route("profile/update", UserProfileUpdateRequest)
async def update_profile(req: UserProfileUpdateRequest):
    store.update_profile(req.model_dump(mode="json"))
    return {"status": "success"}


@route("history/list", HistoryRequest)
async def list_history(req: HistoryRequest):
    return {"sessions": store.list_history(str(req.user_id))}


@route("research/citation", CitationTextRequest)
async def citation_text(req: CitationTextRequest):
    return {"text": await get_citation_text(req)}

@route("diagnose", DiagnosisRequest)
async def diagnose(req: DiagnosisRequest):
    return stream_diagnosis(req)


@route("chat/intake", ChatRequest)
async def chat_intake(req: ChatRequest):
    return stream_intake_chat(req)

@route("chat/doctor", ChatRequest)
async def chat_doctor(req: ChatRequest):
    return stream_doctor_chat_service(req)

@route("research", ResearchRequest)
async def research(req: ResearchRequest):
    return stream_research(req)


def serialize(value):
    if isinstance(value, BaseModel):
        return value.model_dump()
    return value


def emit(payload: dict) -> None:
    print(json.dumps(payload, default=str), file=protocol_stdout, flush=True)


async def handle_message(msg: dict) -> None:
    request_id = msg.get("id")

    try:
        action = msg["action"]

        if action not in routes:
            raise ValueError(f"Unknown action: {action}")

        entry = routes[action]
        model = entry["request_model"]
        fn = entry["fn"]

        req = model.model_validate(msg.get("input", {}))
        with contextlib.redirect_stdout(sys.stderr):
            result = await fn(req)
            if inspect.isasyncgen(result):
                async for event in result:
                    emit({
                        "id": request_id,
                        "ok": True,
                        "event": serialize(event),
                        "done": False,
                    })
                emit({"id": request_id, "ok": True, "result": None, "done": True})
                return

        emit({
            "id": request_id,
            "ok": True,
            "result": serialize(result),
            "done": True,
        })

    except Exception:
        emit({
            "id": request_id,
            "ok": False,
            "error": traceback.format_exc(),
            "done": True,
        })


async def main():
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)

        if not line:
            break

        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
            await handle_message(msg)
        except Exception:
            emit({
                "id": None,
                "ok": False,
                "error": traceback.format_exc(),
                "done": True,
            })


if __name__ == "__main__":
    asyncio.run(main())
