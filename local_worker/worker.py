# nuitka-project: --standalone
# nuitka-project: --output-dir=dist
# nuitka-project: --assume-yes-for-downloads
# nuitka-project: --report=build-report.xml

# nuitka-project: --include-data-dir={MAIN_DIRECTORY}/../agents/prompts=agents/prompts

# Only parsers used by ChatOpenAI structured output
# nuitka-project: --include-module=langchain_core.output_parsers.json
# nuitka-project: --include-module=langchain_core.output_parsers.pydantic

# Only six modules; required lazy exports include LLMResult and ChatResult.
# nuitka-project: --include-package=langchain_core.outputs

# nuitka-project: --include-package=langchain_core.load

# The lazy tool export resolves to convert; convert statically imports BaseTool and StructuredTool.
# nuitka-project: --include-module=langchain_core.tools.convert

# Unused fake language models of langchain_core
# nuitka-project: --nofollow-import-to=langchain_core.language_models.fake
# nuitka-project: --nofollow-import-to=langchain_core.language_models.fake_chat_models
# nuitka-project: --nofollow-import-to=langchain_core.language_models.llms

# Langchain graph renderers
# nuitka-project: --nofollow-import-to=langchain_core.runnables.graph_ascii
# nuitka-project: --nofollow-import-to=langchain_core.runnables.graph_mermaid
# nuitka-project: --nofollow-import-to=langchain_core.runnables.graph_png

# Langsmith
# nuitka-project: --nofollow-import-to=langchain_core.tracers.evaluation
# nuitka-project: --nofollow-import-to=langsmith.evaluation
# nuitka-project: --nofollow-import-to=langsmith.testing
# nuitka-project: --nofollow-import-to=langsmith._expect

# Runtime registries that Nuitka cannot infer from the URL/entry-point lookup.
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

# Only SQLite is used
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
import signal
import subprocess
import time
import traceback
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("IATREON_LOCAL_WORKER", "1")

routes = {}
protocol_stdout = sys.stdout
_worker_init: "WorkerInitRequest | None" = None
_profile_runner_processes: dict[int, subprocess.Popen] = {}

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

from local_worker.models import (
    BackupListRequest,
    BackupRequest,
    BackendSessionRequest,
    BackendSessionUpdateRequest,
    BackupRestoreRequest,
    ChatRequest,
    CitationTextRequest,
    DiagnosisRequest,
    HistoryRequest,
    ProviderSetupStatusRequest,
    ProviderSetupUpdateRequest,
    ResearchRequest,
    SessionCreateRequest,
    SessionResumeRequest,
    SettingsRequest,
    UserProfileStatusRequest,
    UserProfileUpdateRequest,
    WorkerInitRequest,
)
from local_worker import store
from local_worker.services.diagnosis_service import stream_diagnosis
from local_worker.services.intake_service import stream_intake_chat
from local_worker.services.doctor_service import stream_doctor_chat_service
from local_worker.services.research_service import get_citation_text, stream_research
from local_worker.services.profiler_service import drain_profile_update_jobs
from local_worker.errors import NotFoundError
from local_worker.store.backend_session import (
    BackendAuthRequired,
    BackendAuthUnavailable,
    ensure_backend_session,
)
from local_worker.request_context import (
    reset_current_user_id,
    set_current_user_id,
)


BACKEND_AUTH_ROUTES = {
    "chat/intake",
    "chat/doctor",
    "research",
    "diagnose",
    "data/backup",
    "data/backup/list",
    "data/backup/restore",
}


@route("worker/init", WorkerInitRequest)
async def init_worker(req: WorkerInitRequest):
    global _worker_init
    store.initialize(req.db_path, req.db_key)
    await store.initialize_checkpointer()
    _worker_init = req
    launch_profile_job_runner()
    return {"status": "success"}


@route("data/backup", BackupRequest)
async def backup_data(req: BackupRequest):
    checksum = await store.create_encrypted_backup(
        source_path=Path(req.source_path),
        backup_path=Path(req.backup_path),
        db_key=req.db_key,
    )

    await store.upload_backup(Path(req.backup_path), str(req.user_id), checksum)
    return {"status": "success"}


@route("data/backup/list", BackupListRequest)
async def get_backup(req: BackupListRequest):
    from local_worker.store.backups import list_backups

    backup_data = await list_backups(str(req.user_id))
    return backup_data


@route("data/backup/restore", BackupRestoreRequest)
async def restore_backup(req: BackupRestoreRequest):
    from local_worker.store.backups import restore_backup as restore

    await store.close_checkpointer()
    runner_lock = None
    try:
        runner_lock = await asyncio.to_thread(_lock_profiler_for_restore, req.db_path)
        await restore(
            user_id=str(req.user_id),
            backup_id=req.backup_id,
            restore_path=Path(req.db_path),
            checksum=req.checksum,
            db_key=req.db_key,
        )
    finally:
        try:
            store.initialize(req.db_path, req.db_key)
            await store.initialize_checkpointer()
        finally:
            if runner_lock is not None:
                _release_profiler_lock(runner_lock)
            launch_profile_job_runner()
    return {"status": "success"}

@route("session/create", SessionCreateRequest)
async def create_session(req: SessionCreateRequest):
    return {"session_id": store.create_session(str(req.user_id))}


def _resume_messages(messages):
    restored = []
    for message in messages:
        if isinstance(message, dict):
            role = message.get("role") or message.get("type")
            content = message.get("content")
        else:
            role = getattr(message, "type", None)
            content = getattr(message, "content", None)

        role = {"human": "user", "assistant": "ai"}.get(role, role)
        if role not in {"user", "ai"}:
            continue

        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
            content = "".join(parts)

        if isinstance(content, str) and content.strip():
            restored.append({"role": role, "text": content})
    return restored



@route("session/resume", SessionResumeRequest)
async def resume_session(req: SessionResumeRequest):
    data = store.get_session_resume_data(str(req.user_id), str(req.session_id))
    if data is None:
        raise NotFoundError("Chat session not found.")

    history_conversation_ids = data.pop("history_conversation_ids", [])
    conversation_id = data["conversation_id"]
    messages = []
    seen = set()
    found_checkpoint = False
    for thread_id in [*history_conversation_ids, conversation_id]:
        if not thread_id or thread_id in seen:
            continue
        seen.add(thread_id)
        try:
            checkpoint = await store.get_checkpointer().aget_tuple(
                {"configurable": {"thread_id": str(thread_id)}}
            )
        except Exception:
            continue
        if checkpoint:
            found_checkpoint = True
            messages.extend(checkpoint.checkpoint["channel_values"].get("messages", []))

    if not found_checkpoint: 
        raise NotFoundError("Conversation not found.")

    return {
        **data,
        "conversation_id": str(conversation_id),
        "messages": _resume_messages(messages),
    }



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


@route("settings/get", SettingsRequest)
async def get_settings(req: SettingsRequest):
    user_id = str(req.user_id)
    return {
        "profile": store.get_profile(user_id),
        "provider_setup": store.get_provider_setup(user_id),
    }


@route("backend-session/update", BackendSessionUpdateRequest)
async def update_backend_session(req: BackendSessionUpdateRequest):
    store.update_backend_session(
        str(req.user_id), req.username, req.access_token, req.refresh_token
    )
    return {"status": "success"}


@route("backend-session/get", BackendSessionRequest)
async def get_backend_session(req: BackendSessionRequest):
    return store.get_backend_session(str(req.user_id))


@route("backend-session/ensure", BackendSessionRequest)
async def ensure_session(req: BackendSessionRequest):
    session = await ensure_backend_session(str(req.user_id), validate=True)
    return {"authenticated": True, "username": session.get("username", "")}


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

class ProfilerRequest(BaseModel):
    user_id: str
    chat_session_id: str
    state: str | None = None
    run_now: bool = False

@route("medical-profile/upsert", ProfilerRequest)
async def run_profiler(req: ProfilerRequest):
    delay_seconds = 0 if req.run_now else {
        "intake_done": 7 * 60,
        "doctor_turn_done": 2 * 60,
    }.get(req.state, 0)
    store.upsert_profile_update_job(
        user_id=str(req.user_id),
        chat_session_id=str(req.chat_session_id),
        delay_seconds=delay_seconds,
    )
    return {"status": "queued"}


PROFILE_JOB_ACTIONS = {
    "chat/intake",
    "chat/doctor",
    "diagnose",
    "medical-profile/upsert",
}


def build_profile_runner_command() -> list[str]:
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        return [sys.executable, "--drain-profile-jobs"]
    return [sys.executable, str(Path(__file__).resolve()), "--drain-profile-jobs"]


def _acquire_file_lock(path: str, blocking: bool = False):
    lock = open(path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt

            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
            mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
            msvcrt.locking(lock.fileno(), mode, 1)
        else:
            import fcntl

            flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            fcntl.flock(lock.fileno(), flags)
    except OSError:
        lock.close()
        return None
    return lock


def _release_file_lock(lock) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    finally:
        lock.close()


def _acquire_profiler_lock(db_path: str):
    return _acquire_file_lock(f"{db_path}.profile-runner.lock")


def _release_profiler_lock(lock) -> None:
    _release_file_lock(lock)


def _acquire_profiler_launch_lock(db_path: str):
    lock = _acquire_file_lock(f"{db_path}.profile-runner-launch.lock", blocking=True)
    if lock is None:
        raise RuntimeError("Could not acquire the profiler launch lock")
    return lock


def _write_profile_runner_pid(lock, pid: int | None) -> None:
    lock.seek(1)
    lock.truncate()
    if pid is not None:
        lock.write(str(pid).encode("ascii"))
    lock.flush()


def _read_profile_runner_pid(db_path: str) -> int | None:
    try:
        with open(f"{db_path}.profile-runner.lock", "rb") as lock:
            lock.seek(1)
            value = lock.read().decode("ascii").strip()
        return int(value) if value else None
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _lock_profiler_for_restore(db_path: str):
    launch_lock = _acquire_profiler_launch_lock(db_path)
    try:
        runner_lock = _acquire_profiler_lock(db_path)
        if runner_lock is None:
            pid = _read_profile_runner_pid(db_path)
            if pid is None or pid == os.getpid():
                raise RuntimeError("Could not identify the active profiler process for restore")

            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except OSError as exc:
                raise RuntimeError("Could not stop the active profiler process for restore") from exc

            deadline = time.monotonic() + 5
            while runner_lock is None and time.monotonic() < deadline:
                time.sleep(0.05)
                runner_lock = _acquire_profiler_lock(db_path)
            if runner_lock is None:
                raise RuntimeError("Timed out stopping the active profiler process for restore")

        _write_profile_runner_pid(runner_lock, None)
        return runner_lock
    finally:
        _release_file_lock(launch_lock)


def is_profile_runner_active(db_path: str) -> bool:
    lock = _acquire_profiler_lock(db_path)
    if lock is None:
        return True
    _release_profiler_lock(lock)
    return False


def get_profile_runner_pids() -> set[int]:
    for pid, process in list(_profile_runner_processes.items()):
        if process.poll() is not None:
            _profile_runner_processes.pop(pid)
    return set(_profile_runner_processes)


def launch_profile_job_runner() -> None:
    if _worker_init is None:
        return

    get_profile_runner_pids()
    launch_lock = _acquire_profiler_launch_lock(_worker_init.db_path)
    try:
        if (
            store.next_profile_update_delay() is None
            or is_profile_runner_active(_worker_init.db_path)
        ):
            return

        kwargs = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "text": True,
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
            )
        else:
            kwargs["start_new_session"] = True

        try:
            process = subprocess.Popen(build_profile_runner_command(), **kwargs)
            _profile_runner_processes[process.pid] = process
            if process.stdin is not None:
                process.stdin.write(_worker_init.model_dump_json())
                process.stdin.close()
        except OSError:
            return
    finally:
        _release_file_lock(launch_lock)


async def run_profile_job_runner() -> None:
    req = WorkerInitRequest.model_validate_json(await asyncio.to_thread(sys.stdin.read))
    runner_lock = None
    launch_lock = _acquire_profiler_launch_lock(req.db_path)
    try:
        runner_lock = _acquire_profiler_lock(req.db_path)
        if runner_lock is None:
            return
        _write_profile_runner_pid(runner_lock, os.getpid())
    finally:
        _release_file_lock(launch_lock)

    try:
        store.initialize(req.db_path, req.db_key)
        store.recover_profile_update_jobs()
        while True:
            await drain_profile_update_jobs()

            launch_lock = _acquire_profiler_launch_lock(req.db_path)
            try:
                if store.next_profile_update_delay() is not None:
                    continue
                _write_profile_runner_pid(runner_lock, None)
                _release_profiler_lock(runner_lock)
                runner_lock = None
                return
            finally:
                _release_file_lock(launch_lock)
    finally:
        try:
            await store.close_checkpointer()
        finally:
            if runner_lock is not None:
                launch_lock = _acquire_profiler_launch_lock(req.db_path)
                try:
                    _write_profile_runner_pid(runner_lock, None)
                    _release_profiler_lock(runner_lock)
                finally:
                    _release_file_lock(launch_lock)


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
        should_launch_profiler = action in PROFILE_JOB_ACTIONS

        req = model.model_validate(msg.get("input", {}))
        token = set_current_user_id(getattr(req, "user_id", None))
        try:
            with contextlib.redirect_stdout(route_stdout):
                if action in BACKEND_AUTH_ROUTES:
                    await ensure_backend_session()
                result = await fn(req)
                if inspect.isasyncgen(result):
                    async for event in result:
                        emit({
                            "id": request_id,
                            "ok": True,
                            "event": serialize(event),
                            "done": False,
                        })
                    if should_launch_profiler:
                        launch_profile_job_runner()
                        should_launch_profiler = False
                    emit({"id": request_id, "ok": True, "result": None, "done": True})
                    return
        finally:
            reset_current_user_id(token)
            if should_launch_profiler:
                launch_profile_job_runner()

        emit({
            "id": request_id,
            "ok": True,
            "result": serialize(result),
            "done": True,
        })

    except BackendAuthRequired as exc:
        emit({
            "id": request_id,
            "ok": False,
            "error": str(exc),
            "error_code": "backend_auth_required",
            "done": True,
        })
    except BackendAuthUnavailable as exc:
        emit({
            "id": request_id,
            "ok": False,
            "error": str(exc),
            "error_code": "backend_auth_unavailable",
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
    if "--drain-profile-jobs" in sys.argv[1:]:
        asyncio.run(run_profile_job_runner())
    else:
        asyncio.run(main())
