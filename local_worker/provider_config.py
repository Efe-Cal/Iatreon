import os
from typing import Any

import httpx  # Compatibility: existing tests patch provider_config.httpx.

from local_worker.request_context import (
    current_user_id,
    reset_current_user_id,
    set_current_user_id,
)
from local_worker.store.backend_session import (
    BackendAuthRequired,
    BackendAuthUnavailable,
    backend_api_url,
    backend_session,
    ensure_backend_session,
)



LLM_BASE_URLS = {
    "Iatreon AI": "https://iatreon.efecal.hackclub.app/v1",
    "OpenAI": "https://api.openai.com/v1",
    "Hack Club AI": "https://ai.hackclub.com/proxy/v1",
    "OpenRouter": "https://openrouter.ai/api/v1",
    "Together AI": "https://api.together.ai/v1",
    "Groq": "https://api.groq.com/openai/v1",
    "Fireworks AI": "https://api.fireworks.ai/inference/v1",
    "DeepSeek": "https://api.deepseek.com",
    "xAI": "https://api.x.ai/v1",
    "Gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "Cohere": "https://api.cohere.ai/compatibility/v1",
    "Perplexity": "https://api.perplexity.ai",
    "Hugging Face": "https://router.huggingface.co/v1",
}

SEARCH_BASE_URLS = {
    "Iatreon AI": "https://iatreon.efecal.hackclub.app/v1/exa",
}

DEFAULT_MODEL = "google/gemini-3-flash-preview"
IATREON_AGENT_MODELS = {
    "intake": DEFAULT_MODEL,
    "research_fast": DEFAULT_MODEL,
    "doctor": "xiaomi/mimo-v2.5-pro",
    "diagnosis": "xiaomi/mimo-v2.5-pro",
    "inference": "xiaomi/mimo-v2.5-pro",
    "profiler": "xiaomi/mimo-v2.5-pro",
    "research_standard": "xiaomi/mimo-v2.5-pro",
    "research_deep": "xiaomi/mimo-v2.5-pro",
}


def agent_model_defaults() -> dict[str, str]:
    research = os.getenv("RESEARCH_AGENT_MODEL") or DEFAULT_MODEL
    return {
        "intake": os.getenv("INTAKE_AGENT_MODEL") or DEFAULT_MODEL,
        "doctor": os.getenv("DOCTOR_AGENT_MODEL") or DEFAULT_MODEL,
        "diagnosis": os.getenv("DIAGNOSIS_AGENT_MODEL") or DEFAULT_MODEL,
        "inference": os.getenv("INFERENCE_AGENT_MODEL") or DEFAULT_MODEL,
        "profiler": os.getenv("PROFILER_AGENT_MODEL") or DEFAULT_MODEL,
        "research_fast": os.getenv("RESEARCH_AGENT_FAST_MODEL") or research,
        "research_standard": research,
        "research_deep": os.getenv("RESEARCH_AGENT_DEEP_MODEL") or research,
    }


def provider_setup() -> dict[str, Any]:
    if os.getenv("IATREON_LOCAL_WORKER") != "1":
        return {}

    user_id = current_user_id()
    if not user_id:
        return {}

    from local_worker.store.provider_setup import get_provider_setup

    return get_provider_setup(user_id)


def agent_model(slot: str) -> str:
    setup = provider_setup()
    if (setup.get("llm_provider") or "Iatreon AI") == "Iatreon AI":
        return IATREON_AGENT_MODELS.get(slot, DEFAULT_MODEL)
    configured = setup.get("agent_models") or {}
    return configured.get(slot) or agent_model_defaults().get(slot, DEFAULT_MODEL)


async def fetch_provider_models(provider: str, api_key: str, base_url: str) -> list[str]:
    if provider == "Iatreon AI":
        return []
    url = (base_url.strip() or LLM_BASE_URLS.get(provider, "")).rstrip("/")
    if not url:
        raise ValueError(f"Base URL is required for {provider}")
    headers = {"Authorization": f"Bearer {api_key.strip()}"} if api_key.strip() else {}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(url + "/models", headers=headers)
        response.raise_for_status()
        payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ValueError("Provider returned an invalid model list")
    return sorted({
        item["id"].strip()
        for item in data
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
    })



def llm_config() -> dict[str, str | None]:
    setup = provider_setup()
    provider = setup.get("llm_provider") or "Iatreon AI"
    base_url = setup.get("llm_base_url")
    if not base_url and (provider == "Iatreon AI" or not setup):
        base_url = os.getenv("AI_API_BASE_URL") or backend_api_url() + "/v1"
    if not base_url:
        base_url = LLM_BASE_URLS.get(provider) or os.getenv("AI_API_BASE_URL")
    return {
        "provider": provider,
        "api_key": backend_session().get("access_token") if provider == "Iatreon AI" else setup.get("llm_api_key") or os.getenv("AI_API_KEY"),
        "base_url": base_url,
    }


def search_config() -> dict[str, str | None]:
    setup = provider_setup()
    provider = setup.get("search_provider") or "Iatreon AI"
    base_url = setup.get("search_base_url")
    if not base_url and (provider == "Iatreon AI" or not setup):
        base_url = os.getenv("EXA_BASE_URL") or backend_api_url() + "/v1/exa"
    return {
        "provider": provider,
        "api_key": backend_session().get("access_token") if provider == "Iatreon AI" else setup.get("search_api_key") or os.getenv("EXA_API_KEY") or os.getenv("AI_API_KEY"),
        "base_url": base_url,
    }
