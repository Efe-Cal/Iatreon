"""
OCR Service Layer for MarkItDown
Provides Mistral OCR implementation
"""

import base64
import os
from typing import Any, BinaryIO
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from markitdown import StreamInfo


@dataclass
class OCRResult:
    """Result from OCR extraction."""

    text: str
    confidence: float | None = None
    backend_used: str | None = None
    error: str | None = None


class MistralOCRService:
    """OCR service using LLM vision models (OpenAI-compatible)."""

    def __init__(self,*args,**kwargs: Any) -> None:
        """
        Initialize Mistral OCR service.
        """
        

    def extract_text(
        self,
        image_stream: BinaryIO,
        stream_info: StreamInfo | None = None,
        **kwargs: Any,
    ) -> OCRResult:
        """Extract text using Mistral OCR."""


        try:
            image_stream.seek(0)

            content_type: str | None = None
            if stream_info:
                content_type = stream_info.mimetype

            if not content_type:
                try:
                    from PIL import Image

                    image_stream.seek(0)
                    img = Image.open(image_stream)
                    fmt = img.format.lower() if img.format else "png"
                    content_type = f"image/{fmt}"
                except Exception:
                    content_type = "image/png"

            image_stream.seek(0)
            base64_image = base64.b64encode(image_stream.read()).decode("utf-8")
            data_uri = f"data:{content_type};base64,{base64_image}"

            body = {
                "document": {
                    "type": "image_url",
                    "image_url": data_uri,
                },
                "table_format":"markdown",
            }
            response = httpx.post(
                os.getenv("OCR_API_URL") or urljoin(os.getenv("AI_API_BASE_URL"), "/ocr"),
                json=body,
                headers={"Authorization": f"Bearer {os.getenv('OCR_API_KEY') or os.getenv('AI_API_KEY')}"},
                timeout=30,
            )
            text = ""
            if response.status_code == 200:
                try:
                    text = response.json()["pages"][0]["markdown"]
                except (KeyError, IndexError, ValueError, TypeError) as exc:
                    return OCRResult(text="", backend_used="mistral_ocr", error=str(exc))
            return OCRResult(
                text=text.strip() if text else "",
                backend_used="mistral_ocr",
            )
        except Exception as e:
            return OCRResult(text="", backend_used="mistral_ocr", error=str(e))
        finally:
            image_stream.seek(0)

if __name__ == "__main__":
    from markitdown import MarkItDown
    mitd = MarkItDown(enable_plugins=True)
    
    text = mitd.convert(r"C:\Users\efeca\Downloads\ehw128.pdf").text_content
    with open("output.txt", "w", encoding="utf-8") as f:
        f.write(text)