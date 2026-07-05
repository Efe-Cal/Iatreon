import sys
import json
import asyncio
import traceback
from pydantic import BaseModel

routes = {}


def route(name: str, request_model: type[BaseModel]):
    def decorator(fn):
        routes[name] = {
            "fn": fn,
            "request_model": request_model,
        }
        return fn
    return decorator

from models import ChatRequest, DiagnosisRequest, ResearchRequest
from services.diagnosis_service import stream_diagnosis
from services.intake_service import stream_intake_chat
from services.doctor_service import stream_doctor_chat_service
from services.research_service import stream_research

@route("diagnose", DiagnosisRequest)
async def diagnose(req: DiagnosisRequest):
    return await stream_diagnosis(req)


@route("chat/intake", ChatRequest)
async def chat_intake(req: ChatRequest):
    return await stream_intake_chat(req) 

@route("chat/doctor", ChatRequest)
async def chat_doctor(req: ChatRequest):
    return await stream_doctor_chat_service(req)

@route("research", ResearchRequest)
async def research(req: ResearchRequest):
    return await stream_research(req.intake_id, req.session_id)


async def handle_message(msg: dict) -> dict:
    request_id = msg.get("id")

    try:
        action = msg["action"]

        if action not in routes:
            raise ValueError(f"Unknown action: {action}")

        entry = routes[action]
        model = entry["request_model"]
        fn = entry["fn"]

        req = model.model_validate(msg.get("input", {}))
        result = await fn(req)

        if isinstance(result, BaseModel):
            result = result.model_dump()

        return {
            "id": request_id,
            "ok": True,
            "result": result,
        }

    except Exception:
        return {
            "id": request_id,
            "ok": False,
            "error": traceback.format_exc(),
        }


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
            response = await handle_message(msg)
        except Exception:
            response = {
                "id": None,
                "ok": False,
                "error": traceback.format_exc(),
            }

        print(json.dumps(response, default=str), flush=True)


if __name__ == "__main__":
    asyncio.run(main())