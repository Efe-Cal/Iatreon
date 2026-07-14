import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlparse


def validate_public_http_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("PDF URL must use HTTP or HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("PDF URL must not contain credentials")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port)}
    except (socket.gaierror, ValueError) as exc:
        raise ValueError("PDF URL host could not be resolved") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("PDF URL must resolve only to public addresses")
    return url


def resolve_download_path(result: str, downloads_dir: Path) -> Path:
    candidate = Path(result).resolve()
    try:
        candidate.relative_to(downloads_dir.resolve())
    except ValueError as exc:
        raise FileNotFoundError("PDF file is outside downloads directory") from exc
    if not candidate.is_file():
        raise FileNotFoundError("PDF file not found")
    return candidate
