import contextvars
import os
from typing import Any
import time
import base64
import binascii
import json
import httpx


_current_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("iatreon_user_id", default=None)
ACCESS_REFRESH_LEEWAY_SECONDS = 5 * 60


class BackendAuthRequired(RuntimeError):
    pass


class BackendAuthUnavailable(RuntimeError):
    pass

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


def backend_api_url() -> str:
    return os.getenv("IATREON_BACKEND_API_URL", "https://iatreon.efecal.hackclub.app").rstrip("/")


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


def backend_session() -> dict[str, str]:
    if os.getenv("IATREON_LOCAL_WORKER") != "1":
        return {"access_token": os.getenv("IATREON_BACKEND_API_TOKEN", "")}
    user_id = _current_user_id.get()
    if not user_id:
        return {}
    try:
        from local_worker import store

        return store.get_backend_session(user_id)
    except Exception:
        return {}


def _access_expires_soon(token: str) -> bool:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        expires_at = float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
        return expires_at <= time.time() + ACCESS_REFRESH_LEEWAY_SECONDS
    except (IndexError, KeyError, TypeError, ValueError, binascii.Error):
        return True


async def ensure_backend_session(user_id: str | None = None, validate: bool = False) -> dict[str, str]:
    if os.getenv("IATREON_LOCAL_WORKER") != "1":
        return backend_session()

    from local_worker import store

    user_id = str(user_id or _current_user_id.get() or "")
    session = store.get_backend_session(user_id) if user_id else {}
    access_token = session.get("access_token", "")
    refresh_token = session.get("refresh_token", "")
    if not refresh_token:
        raise BackendAuthRequired("Your session has expired. Please sign in again.")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            if access_token and not _access_expires_soon(access_token):
                if not validate:
                    return session
                response = await client.get(
                    backend_api_url() + "/auth/me",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if response.status_code == 200:
                    return session
                if response.status_code != 401:
                    raise BackendAuthUnavailable("Iatreon authentication is temporarily unavailable.")

            response = await client.post(
                backend_api_url() + "/auth/refresh",
                json={"refresh_token": refresh_token},
            )
    except httpx.HTTPError as exc:
        raise BackendAuthUnavailable("Iatreon authentication is temporarily unavailable.") from exc

    if response.status_code == 401:
        raise BackendAuthRequired("Your session has expired. Please sign in again.")
    if response.status_code != 200:
        raise BackendAuthUnavailable("Iatreon authentication is temporarily unavailable.")

    try:
        payload = response.json()
        access_token = payload["access_token"]
        refresh_token = payload["refresh_token"]
        if not access_token or not refresh_token:
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise BackendAuthUnavailable("Iatreon authentication returned an invalid response.") from exc

    store.update_backend_session(user_id, session.get("username", ""), access_token, refresh_token)
    return store.get_backend_session(user_id)


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
