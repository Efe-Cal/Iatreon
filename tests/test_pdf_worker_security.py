import socket
from pathlib import Path

import pytest


def test_url_validation_rejects_schemes_credentials_and_private_hosts(monkeypatch):
    from pdf_worker.security import validate_public_http_url

    monkeypatch.setattr(socket, "getaddrinfo", lambda *args: [(socket.AF_INET, 0, 0, "", ("93.184.216.34", 0))])
    assert validate_public_http_url("https://example.com/article.pdf")
    with pytest.raises(ValueError):
        validate_public_http_url("file:///etc/passwd")
    with pytest.raises(ValueError):
        validate_public_http_url("https://user:pass@example.com/a.pdf")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args: [(socket.AF_INET, 0, 0, "", ("127.0.0.1", 0))])
    with pytest.raises(ValueError):
        validate_public_http_url("http://localhost/a.pdf")


def test_internal_download_rejects_paths_outside_downloads(monkeypatch, tmp_path):
    from pdf_worker.security import resolve_download_path

    downloads = tmp_path / "downloads"
    downloads.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF")
    with pytest.raises(FileNotFoundError):
        resolve_download_path(str(outside), downloads)

    traversal = downloads / ".." / "outside.pdf"
    with pytest.raises(FileNotFoundError):
        resolve_download_path(str(traversal), downloads)


def test_internal_download_rejects_symlink_escape(tmp_path):
    from pdf_worker.security import resolve_download_path

    downloads = tmp_path / "downloads"
    downloads.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF")
    link = downloads / "linked.pdf"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable")
    with pytest.raises(FileNotFoundError):
        resolve_download_path(str(link), downloads)
