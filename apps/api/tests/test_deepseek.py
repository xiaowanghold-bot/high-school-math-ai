from __future__ import annotations

import json

from app.modules.deepseek import DeepSeekJsonClient
from app.modules.lesson_plans import DeepSeekLessonPlanProvider
from app.modules.question_variants import DeepSeekQuestionVariantProvider
from app.modules.solution_assistant import DeepSeekSolutionProvider


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
    assert captured["payload"]["max_tokens"] == 4096
    assert '"required": ["answer"]' in captured["payload"]["messages"][0]["content"]
    assert captured["timeout"] == 23
    assert json.loads(result["output"][0]["content"][0]["text"]) == {"answer": "4"}


def test_deepseek_normalizes_control_characters_fences_and_trailing_text(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            payload = {
                "choices": [{"message": {"content": '```json\n{"answer":"line\none","formula":"\\frac{1}{2}"}\n```\n补充说明'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
            }
            return json.dumps(payload, ensure_ascii=False).encode()

    monkeypatch.setattr("app.modules.deepseek.urlopen", lambda *_args, **_kwargs: Response())
    result = DeepSeekJsonClient(api_key="test-secret").request(
        instructions="test", input_text="{}", action="test", max_tokens=900,
    )
    parsed = json.loads(result["output"][0]["content"][0]["text"])
    assert parsed == {"answer": "line\none", "formula": "\\frac{1}{2}"}


def test_deepseek_providers_initialize_openai_compatible_fields() -> None:
    common = {
        "api_key": "test-secret",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
    }

    providers = [
        DeepSeekLessonPlanProvider(**common),
        DeepSeekQuestionVariantProvider(**common),
        DeepSeekSolutionProvider(**common),
    ]

    assert all(provider.reasoning_effort == "low" for provider in providers)
    assert all(provider.api_key == "test-secret" for provider in providers)
    assert all(provider.timeout_seconds == 90 for provider in providers)
