import contextvars
import os
from typing import Any


_current_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("iatreon_user_id", default=None)

LLM_BASE_URLS = {
    "Iatreon AI": "https://ai.hackclub.com/proxy/v1",
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
    "Iatreon AI": "https://ai.hackclub.com/proxy/v1/exa",
}


def set_current_user_id(user_id: Any):
    return _current_user_id.set(str(user_id) if user_id else None)


def reset_current_user_id(token) -> None:
    _current_user_id.reset(token)


def provider_setup() -> dict[str, Any]:
    if os.getenv("IATREON_LOCAL_WORKER") != "1":
        return {}

    user_id = _current_user_id.get()
    if not user_id:
        return {}

    try:
        from local_worker import store

        return store.get_provider_setup(user_id)
    except Exception:
        return {}


def llm_config() -> dict[str, str | None]:
    setup = provider_setup()
    provider = setup.get("llm_provider") or "Iatreon AI"
    base_url = setup.get("llm_base_url")
    if not base_url and (provider == "Iatreon AI" or not setup):
        base_url = os.getenv("AI_API_BASE_URL") or LLM_BASE_URLS["Iatreon AI"]
    if not base_url:
        base_url = LLM_BASE_URLS.get(provider) or os.getenv("AI_API_BASE_URL")
    return {
        "provider": provider,
        "api_key": setup.get("llm_api_key") or os.getenv("AI_API_KEY"),
        "base_url": base_url,
    }


def search_config() -> dict[str, str | None]:
    setup = provider_setup()
    provider = setup.get("search_provider") or "Iatreon AI"
    base_url = setup.get("search_base_url")
    if not base_url and (provider == "Iatreon AI" or not setup):
        base_url = os.getenv("EXA_BASE_URL") or SEARCH_BASE_URLS["Iatreon AI"]
    return {
        "provider": provider,
        "api_key": setup.get("search_api_key") or os.getenv("EXA_API_KEY") or os.getenv("AI_API_KEY"),
        "base_url": base_url,
    }
