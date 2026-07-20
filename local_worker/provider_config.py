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
    "OpenRouter": "https://openrouter.ai/api/v1",
    "Together": "https://api.together.ai/v1",
    "Groq": "https://api.groq.com/openai/v1",
    "Fireworks": "https://api.fireworks.ai/inference/v1",
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


def provider_setup() -> dict[str, Any]:
    if os.getenv("IATREON_LOCAL_WORKER") != "1":
        return {}

    user_id = current_user_id()
    if not user_id:
        return {}

    from local_worker.store.provider_setup import get_provider_setup

    return get_provider_setup(user_id)



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
