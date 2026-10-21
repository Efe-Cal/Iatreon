import asyncio
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

import httpx

from context.processing.pdf_utils_v2 import PDFClient


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b"pdf", text=""):
        self.status_code = status_code
        self.payload = payload
        self.content = content
        self.text = text

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload or {}


class FakeAsyncClient:
    def __init__(self, post_result=None, get_results=None, **kwargs):
        self.post_result = post_result
        self.get_results = list(get_results or [])

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        if isinstance(self.post_result, Exception):
            raise self.post_result
        return self.post_result

    async def get(self, *args, **kwargs):
        result = self.get_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


async def no_sleep(_seconds):
    return None


class PDFUtilsV2Tests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_parse_keeps_input_and_serializes_next_parse(self):
        started = threading.Event()
        finish = threading.Event()
        second_started = threading.Event()
        paths = []

        def parse(path):
            paths.append(Path(path))
            if len(paths) == 1:
                started.set()
                if not finish.wait(5):
                    raise TimeoutError("test parser was not released")
            else:
                second_started.set()
            self.assertTrue(Path(path).is_file())
            return "extracted text"

        async def download(*args):
            return b"%PDF fake"

        with (
            patch("context.processing.pdf_utils_v2.httpx.AsyncClient", return_value=FakeAsyncClient()),
            patch.object(PDFClient, "download_pdf", side_effect=download),
            patch.object(PDFClient, "extract_text_from_pdf_liteparse", side_effect=parse),
        ):
            first = asyncio.create_task(PDFClient().get_pdf_content("https://example.com/first.pdf"))
            second = None
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 5))
                first.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await first
                self.assertTrue(paths[0].is_file())
                second = asyncio.create_task(PDFClient().get_pdf_content("https://example.com/second.pdf"))
                self.assertFalse(await asyncio.to_thread(second_started.wait, 0.05))
                finish.set()
                self.assertEqual(await second, "extracted text")
                self.assertTrue(all(not path.exists() for path in paths))
            finally:
                finish.set()
                await asyncio.gather(first, *([second] if second else []), return_exceptions=True)

    async def get_content(self, client):
        with patch("context.processing.pdf_utils_v2.httpx.AsyncClient", return_value=client):
            return await PDFClient().get_pdf_content("https://example.com/article.pdf")

    async def test_worker_connection_error_returns_empty_text(self):
        text = await self.get_content(
            FakeAsyncClient(post_result=httpx.ConnectError("worker down"))
        )
        self.assertEqual(text, "")

    async def test_enqueue_error_returns_empty_text(self):
        text = await self.get_content(
            FakeAsyncClient(post_result=FakeResponse(status_code=500, text="nope"))
        )
        self.assertEqual(text, "")

    async def test_enqueue_invalid_json_returns_empty_text(self):
        text = await self.get_content(
            FakeAsyncClient(
                post_result=FakeResponse(
                    status_code=202,
                    payload=ValueError("bad json"),
                )
            )
        )
        self.assertEqual(text, "")

    async def test_failed_job_returns_empty_text(self):
        text = await self.get_content(
            FakeAsyncClient(
                post_result=FakeResponse(status_code=202, payload={"job_id": "job-1"}),
                get_results=[FakeResponse(payload={"status": "failed"})],
            )
        )
        self.assertEqual(text, "")

    async def test_polling_timeout_returns_empty_text(self):
        client = FakeAsyncClient(
            post_result=FakeResponse(status_code=202, payload={"job_id": "job-1"}),
            get_results=[FakeResponse(payload={"status": "in_progress"}) for _ in range(60)],
        )
        with (
            patch("context.processing.pdf_utils_v2.httpx.AsyncClient", return_value=client),
            patch("context.processing.pdf_utils_v2.asyncio.sleep", no_sleep),
        ):
            text = await PDFClient().get_pdf_content("https://example.com/article.pdf")

        self.assertEqual(text, "")

    async def test_successful_download_extracts_text(self):
        client = FakeAsyncClient(
            post_result=FakeResponse(status_code=202, payload={"job_id": "job-1"}),
            get_results=[
                FakeResponse(payload={"status": "finished", "result": "/tmp/article.pdf"}),
                FakeResponse(status_code=200, content=b"%PDF fake"),
            ],
        )
        with (
            patch("context.processing.pdf_utils_v2.httpx.AsyncClient", return_value=client),
            patch.object(PDFClient, "extract_text_from_pdf_liteparse", return_value="extracted text"),
        ):
            text = await PDFClient().get_pdf_content("https://example.com/article.pdf")

        self.assertEqual(text, "extracted text")


if __name__ == "__main__":
    unittest.main()
