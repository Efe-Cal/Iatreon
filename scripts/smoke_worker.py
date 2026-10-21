"""Offline release check: python scripts/smoke_worker.py [packaged-worker.exe]."""

import base64
import json
import os
from pathlib import Path
from queue import Queue
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import uuid


def main():
    worker = Path(sys.argv[1] if len(sys.argv) > 1 else "release/python-worker/python-worker.exe").resolve()
    for agent in ("intake", "research", "diagnosis", "inference", "profiler", "doctor"):
        prompt = worker.parent / "_internal" / "agents" / "prompts" / f"{agent}_agent_system_prompt.txt"
        assert prompt.read_text(encoding="utf-8").strip(), prompt
    user_id = str(uuid.uuid4())
    key = base64.b64encode(os.urandom(32)).decode("ascii")
    with TemporaryDirectory(prefix="iatreon-release-") as temp:
        database = Path(temp) / "smoke.sqlite3"
        with open(Path(temp) / "stderr.log", "w+", encoding="utf-8") as errors:
            process = subprocess.Popen(
                [str(worker)], cwd=temp, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=errors, text=True, encoding="utf-8",
            )
            output = Queue()

            def read_output():
                for line in process.stdout:
                    output.put(line)

            Thread(target=read_output, daemon=True).start()

            def call(action, payload, error_code=None):
                request_id = str(uuid.uuid4())
                process.stdin.write(json.dumps({"id": request_id, "action": action, "input": payload}) + "\n")
                process.stdin.flush()
                response = json.loads(output.get(timeout=45))
                assert response["id"] == request_id and response["done"], response
                if error_code:
                    assert not response["ok"] and response.get("error_code") == error_code, response
                    return response
                assert response["ok"], response
                return response.get("result")

            try:
                assert call("worker/init", {"db_path": str(database), "db_key": key}) == {"status": "success"}
                assert not database.read_bytes().startswith(b"SQLite format 3")
                call("profile/update", {"user_id": user_id, "medical_summary": "Release smoke check"})
                settings = call("settings/get", {"user_id": user_id})
                assert settings["profile"]["medical_summary"] == "Release smoke check", settings
                session = call("session/create", {"user_id": user_id})["session_id"]
                assert uuid.UUID(session)
                call("session/resume", {"user_id": user_id, "session_id": session}, error_code="not_found")
                call("worker/cancel", {"request_id": "nonexistent"})
                print("PASS: packaged worker starts outside the repository; encrypted storage, profile, sessions, and cancellation work.")
            except Exception:
                errors.flush()
                errors.seek(0)
                print(errors.read(), file=sys.stderr)
                raise
            finally:
                process.kill()
                process.wait(timeout=10)


if __name__ == "__main__":
    main()
