# nuitka-project: --standalone
# nuitka-project: --output-dir=dist
# nuitka-project: --lto=yes
# nuitka-project: --assume-yes-for-downloads
# nuitka-project: --report=build-report.xml

# nuitka-project: --include-data-dir={MAIN_DIRECTORY}/../agents/prompts=agents/prompts

# Langchain
# nuitka-project: --include-module=langchain_core.callbacks.base
# nuitka-project: --include-module=langchain_core.callbacks.manager

# Chat models only; exclude legacy and fake LLM implementations
# nuitka-project: --include-module=langchain_core.language_models.base
# nuitka-project: --include-module=langchain_core.language_models.chat_models
# nuitka-project: --include-module=langchain_core.language_models.model_profile

# Messages are heavily lazy-loaded and dynamically deserialized.
# Keep this small package complete.
# nuitka-project: --include-package=langchain_core.messages

# Only parsers used by ChatOpenAI structured output
# nuitka-project: --include-module=langchain_core.output_parsers.json
# nuitka-project: --include-module=langchain_core.output_parsers.pydantic
# nuitka-project: --include-module=langchain_core.output_parsers.openai_tools

# Only six modules; keeping the complete package safely covers LLMResult.
# nuitka-project: --include-package=langchain_core.outputs

# Runnable implementations used by ChatOpenAI and LangGraph
# nuitka-project: --include-module=langchain_core.runnables.base
# nuitka-project: --include-module=langchain_core.runnables.config
# nuitka-project: --include-module=langchain_core.runnables.passthrough

# Tool decorator, BaseTool, and StructuredTool
# nuitka-project: --include-module=langchain_core.tools.base
# nuitka-project: --include-module=langchain_core.tools.convert
# nuitka-project: --include-module=langchain_core.tools.structured

# Target for the lazy get_pydantic_field_names export
# nuitka-project: --include-module=langchain_core.utils.utils

# Unused fake language models of langchain_core
# nuitka-project: --nofollow-import-to=langchain_core.language_models.fake
# nuitka-project: --nofollow-import-to=langchain_core.language_models.fake_chat_models
# nuitka-project: --nofollow-import-to=langchain_core.language_models.llms

# Langgraph
# nuitka-project: --include-module=langgraph.config
# nuitka-project: --include-module=langgraph.checkpoint.memory
# nuitka-project: --include-module=langgraph.graph.state
# nuitka-project: --include-module=langchain.agents

# Langchain graph renderers
# nuitka-project: --nofollow-import-to=langchain_core.runnables.graph_ascii
# nuitka-project: --nofollow-import-to=langchain_core.runnables.graph_mermaid
# nuitka-project: --nofollow-import-to=langchain_core.runnables.graph_png

# Langsmith
# nuitka-project: --nofollow-import-to=langchain_core.tracers.evaluation
# nuitka-project: --nofollow-import-to=langsmith.evaluation
# nuitka-project: --nofollow-import-to=langsmith.testing
# nuitka-project: --nofollow-import-to=langsmith._expect

# nuitka-project: --include-module=sqlalchemy.dialects.sqlite.pysqlite
# nuitka-project: --include-module=tiktoken_ext.openai_public

# nuitka-project: --noinclude-pytest-mode=nofollow
# nuitka-project: --noinclude-setuptools-mode=nofollow 
# nuitka-project: --nofollow-import-to="*.tests"

# nuitka-project: --nofollow-import-to=db.db
# nuitka-project: --nofollow-import-to=db.repositories

# HTTPX CLI and terminal presentation features are unused
# nuitka-project: --nofollow-import-to=httpx._main
# nuitka-project: --nofollow-import-to=rich
# nuitka-project: --nofollow-import-to=pygments

# Only the SQLite
# nuitka-project: --nofollow-import-to=sqlalchemy.dialects.postgresql
# nuitka-project: --nofollow-import-to=sqlalchemy.dialects.mysql
# nuitka-project: --nofollow-import-to=sqlalchemy.dialects.mssql
# nuitka-project: --nofollow-import-to=sqlalchemy.dialects.oracle
# nuitka-project: --nofollow-import-to=sqlalchemy.ext.asyncio
# nuitka-project: --include-module=sqlalchemy.dialects.sqlite.pysqlite

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


class _NullWriter:
    def write(self, value: str) -> int:
        return len(value)

    def flush(self) -> None:
        pass


route_stdout = _NullWriter()


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
    ProviderSetupStatusRequest,
    ProviderSetupUpdateRequest,
    ResearchRequest,
    SessionCreateRequest,
    UserProfileStatusRequest,
    UserProfileUpdateRequest,
    WorkerInitRequest,
)
from local_worker import store
from services.diagnosis_service import stream_diagnosis
from services.intake_service import stream_intake_chat
from services.doctor_service import stream_doctor_chat_service
from services.research_service import get_citation_text, stream_research
from local_worker.provider_config import reset_current_user_id, set_current_user_id


@route("worker/init", WorkerInitRequest)
async def init_worker(req: WorkerInitRequest):
    store.initialize(req.db_path, req.db_key)
    return {"status": "success"}


@route("session/create", SessionCreateRequest)
async def create_session(req: SessionCreateRequest):
    return {"session_id": store.create_session(str(req.user_id))}


@route("profile/update", UserProfileUpdateRequest)
async def update_profile(req: UserProfileUpdateRequest):
    store.update_profile(req.model_dump(mode="json"))
    return {"status": "success"}


@route("profile/status", UserProfileStatusRequest)
async def profile_status(req: UserProfileStatusRequest):
    return {"has_profile": store.has_profile(str(req.user_id))}


@route("provider/update", ProviderSetupUpdateRequest)
async def update_provider_setup(req: ProviderSetupUpdateRequest):
    store.update_provider_setup(req.model_dump(mode="json"))
    return {"status": "success"}


@route("provider/status", ProviderSetupStatusRequest)
async def provider_status(req: ProviderSetupStatusRequest):
    return {"has_provider_setup": store.has_provider_setup(str(req.user_id))}


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
        token = set_current_user_id(getattr(req, "user_id", None))
        try:
            with contextlib.redirect_stdout(route_stdout):
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
        finally:
            reset_current_user_id(token)

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
