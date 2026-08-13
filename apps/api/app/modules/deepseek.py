from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class DeepSeekClientError(RuntimeError):
    pass


class DeepSeekJsonClient:
    """Minimal OpenAI-compatible Chat Completions adapter for JSON workflows."""

    name = "deepseek"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        timeout_seconds: int = 90,
    ) -> None:
        if not api_key:
            raise ValueError("DeepSeek API Key 不能为空")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def request(
        self,
        *,
        instructions: str,
        input_text: str,
        action: str,
        output_schema: dict | None = None,
        max_tokens: int = 4096,
    ) -> dict:
        schema_instruction = ""
        if output_schema:
            schema = output_schema.get("schema", output_schema)
            schema_instruction = (
                "\n输出必须严格符合以下 JSON Schema，不得增加额外字段：\n"
                + json.dumps(schema, ensure_ascii=False)
            )
        system = (
            f"{instructions}{schema_instruction}\n必须只输出合法 JSON，不要使用 Markdown 代码块。"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": input_text},
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "max_tokens": max(256, min(max_tokens, 8192)),
            "stream": False,
        }
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")[:500]
            raise DeepSeekClientError(
                f"DeepSeek 返回 HTTP {exc.code}：{details}"
            ) from exc
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise DeepSeekClientError(f"DeepSeek {action}失败：{exc}") from exc
        try:
            content = raw["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("返回内容为空")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise DeepSeekClientError(f"DeepSeek 返回结构异常：{exc}") from exc
        try:
            normalized = self._normalize_json(content)
        except (json.JSONDecodeError, ValueError) as exc:
            raise DeepSeekClientError(f"DeepSeek 返回的 JSON 无法解析：{exc}") from exc
        return {
            **raw,
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": normalized}]}
            ],
        }

    @staticmethod
    def _normalize_json(content: str) -> str:
        """Recover one JSON object while leaving schema checks to providers."""
        value = content.strip()
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```", value, flags=re.DOTALL | re.IGNORECASE)
        if fence:
            value = fence.group(1).strip()
        # JSON considers \b, \f, \n and \t valid escapes, while the same
        # prefixes start common LaTeX commands. Preserve those commands before
        # decoding so \frac/\begin/\neq/\text/\times are not turned into
        # invisible control characters.
        value = re.sub(
            r'\\(?=(?:begin|beta|frac|neq|not|text|times|theta|tan|to|nabla)\b)',
            r'\\\\',
            value,
        )
        decoder = json.JSONDecoder(strict=False)
        try:
            parsed, _end = decoder.raw_decode(value)
        except json.JSONDecodeError:
            # LaTeX backslashes are occasionally not JSON-escaped by the model.
            repaired = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', value)
            parsed, _end = decoder.raw_decode(repaired)
        if not isinstance(parsed, dict):
            raise ValueError("顶层结果必须是 JSON 对象")
        return json.dumps(parsed, ensure_ascii=False)
