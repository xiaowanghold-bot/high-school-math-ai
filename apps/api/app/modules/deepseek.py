from __future__ import annotations

import json
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
            "max_tokens": 8192,
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
        return {
            **raw,
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": content}]}
            ],
        }
