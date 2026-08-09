from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile


class OCRProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class OCRTextResult:
    text: str
    warnings: list[str] = field(default_factory=list)


class OpenAIResourceOCRProvider:
    """Small Responses API adapter; consent is enforced by PrivateLibrary."""

    name = "openai"
    MAX_EXTERNAL_BYTES = 20 * 1024 * 1024

    def __init__(self, *, api_key: str, model: str, timeout_seconds: int = 90) -> None:
        if not api_key:
            raise ValueError("OpenAI API Key 不能为空")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def extract(
        self, *, path: Path, mime_type: str, filename: str, teacher_id: str
    ) -> OCRTextResult:
        content = path.read_bytes()
        if len(content) > self.MAX_EXTERNAL_BYTES:
            raise OCRProviderError("发送到 OCR 服务的单个文件不能超过 20 MB")
        media = self._media_inputs(content, mime_type=mime_type, filename=filename)
        payload = {
            "model": self.model,
            "instructions": (
                "你是高中数学资料 OCR 助手。忠实转录文件中的中文、数字、公式、题号、选项、答案与解析。"
                "数学公式优先写为可读的 LaTeX；不补题、不改题、不推导答案。无法辨认处使用【无法辨认】。"
            ),
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "请逐页转录这份私人教学资料，并返回结构化结果。"},
                        *media,
                    ],
                }
            ],
            "text": {"format": self._output_format(), "verbosity": "low"},
            "safety_identifier": hashlib.sha256(
                f"math-ai-library-ocr:{teacher_id}".encode("utf-8")
            ).hexdigest()[:32],
            "store": False,
        }
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")[:500]
            raise OCRProviderError(f"OpenAI OCR 返回 HTTP {exc.code}：{details}") from exc
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise OCRProviderError(f"OpenAI OCR 调用失败：{exc}") from exc
        try:
            parsed = json.loads(self._output_text(raw))
            return OCRTextResult(text=str(parsed["text"]), warnings=list(parsed["warnings"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OCRProviderError(f"OCR 返回内容不符合预期结构：{exc}") from exc

    @staticmethod
    def _media_inputs(content: bytes, *, mime_type: str, filename: str) -> list[dict]:
        if mime_type.startswith("image/"):
            encoded = base64.b64encode(content).decode("ascii")
            return [{
                "type": "input_image",
                "image_url": f"data:{mime_type};base64,{encoded}",
                "detail": "original",
            }]
        if mime_type.endswith("wordprocessingml.document"):
            try:
                with ZipFile(BytesIO(content)) as archive:
                    entries = [
                        name for name in archive.namelist()
                        if name.startswith("word/media/") and Path(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
                    ][:12]
                    if not entries:
                        raise OCRProviderError("DOCX 中没有可供 OCR 的 PNG、JPEG 或 WebP 图片")
                    mime_by_suffix = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
                    return [
                        {
                            "type": "input_image",
                            "image_url": f"data:{mime_by_suffix[Path(name).suffix.lower()]};base64,{base64.b64encode(archive.read(name)).decode('ascii')}",
                            "detail": "original",
                        }
                        for name in entries
                    ]
            except BadZipFile as exc:
                raise OCRProviderError("DOCX 压缩结构损坏，无法提取内嵌图片") from exc
        encoded = base64.b64encode(content).decode("ascii")
        return [{
            "type": "input_file",
            "filename": filename,
            "file_data": f"data:{mime_type};base64,{encoded}",
        }]

    @staticmethod
    def _output_text(payload: dict) -> str:
        for item in payload.get("output", []):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        return str(content["text"])
        raise KeyError("output_text")

    @staticmethod
    def _output_format() -> dict:
        return {
            "type": "json_schema",
            "name": "private_resource_ocr",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "text": {"type": "string"},
                    "warnings": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "warnings"],
            },
        }
