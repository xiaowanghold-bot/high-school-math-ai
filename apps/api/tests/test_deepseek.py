from __future__ import annotations

import json

from app.modules.deepseek import DeepSeekJsonClient


def test_deepseek_uses_chat_completions_json_mode(monkeypatch) -> None:
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": '{"answer":"4"}'}}]}
            ).encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("app.modules.deepseek.urlopen", fake_urlopen)
    client = DeepSeekJsonClient(
        api_key="test-secret", model="deepseek-v4-flash", timeout_seconds=23
    )
    result = client.request(
        instructions="解题并输出 JSON",
        input_text='{"question":"2+2"}',
        action="解题",
        output_schema={"schema": {"type": "object", "required": ["answer"]}},
    )

    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["authorization"] == "Bearer test-secret"
    assert captured["payload"]["model"] == "deepseek-v4-flash"
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert captured["payload"]["thinking"] == {"type": "disabled"}
    assert '"required": ["answer"]' in captured["payload"]["messages"][0]["content"]
    assert captured["timeout"] == 23
    assert result["output"][0]["content"][0]["text"] == '{"answer":"4"}'
