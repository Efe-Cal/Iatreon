import threading
import time
from email.utils import parsedate_to_datetime

import requests

from ..config import NCBI_API_KEY


_lock = threading.Lock()
_next_request_at = 0.0
_NCBI_REQUESTS_PER_SECOND = 10 if NCBI_API_KEY else 3
_NCBI_REQUEST_INTERVAL = (1 / _NCBI_REQUESTS_PER_SECOND) + 0.05 # jst to be safe  


def wait_for_ncbi_slot() -> None:
    """Serialize NCBI requests across worker threads in this process."""
    global _next_request_at

    with _lock:
        now = time.monotonic()
        if now < _next_request_at:
            time.sleep(_next_request_at - now)

        _next_request_at = time.monotonic() + _NCBI_REQUEST_INTERVAL


def ncbi_get(url: str, *, max_retries: int = 3, **kwargs) -> requests.Response:
    """Run a GET request through the shared NCBI rate limiter."""
    for attempt in range(max_retries + 1):
        wait_for_ncbi_slot()
        response = requests.get(url, **kwargs)
        if response.status_code != 429 or attempt == max_retries:
            return response

        retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
        if retry_after is None:
            retry_after = _NCBI_REQUEST_INTERVAL * (attempt + 1)
        time.sleep(retry_after)

    return response


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None

    try:
        return max(float(value), 0.0)
    except ValueError:
        pass

    try:
        retry_time = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None

    return max(retry_time.timestamp() - time.time(), 0.0)
