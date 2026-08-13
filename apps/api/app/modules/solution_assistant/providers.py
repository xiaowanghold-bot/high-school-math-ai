from __future__ import annotations

import hashlib
import json
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.modules.model_operations import ModelRunRecorder, NullModelRunRecorder
from app.modules.deepseek import DeepSeekClientError, DeepSeekJsonClient
from app.modules.solution_assistant.schemas import GeneratedSolution, SolutionRequest


class SolutionProviderError(RuntimeError):
    pass


class SolutionProvider(Protocol):
    name: str
    model: str

    def solve(self, request: SolutionRequest) -> GeneratedSolution: ...


class OpenAISolutionProvider:
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        reasoning_effort: str = "low",
        timeout_seconds: int = 90,
        recorder: ModelRunRecorder | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI API Key 不能为空")
        self.api_key = api_key
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.timeout_seconds = timeout_seconds
        self.recorder = recorder or NullModelRunRecorder()

    def solve(self, request_data: SolutionRequest) -> GeneratedSolution:
        task = (
            "给出一种与常规解法不同但完整严谨的第二种解法。"
            if request_data.solution_mode == "alternative"
            else "给出适合高中教师审核和讲解的标准解法。"
        )
        prompt = {
            "task": task,
            "question": request_data.question_text,
            "teacher_instruction": request_data.teacher_instruction,
        }
        payload = {
            "model": self.model,
            "instructions": (
                "你是中国高中数学教研员，使用人教A版术语和新高考答题规范解题。"
                "必须检查题目条件是否充分，逐步给出依据，不能虚构题源、数值或验证结论。"
                "如果题目本身有歧义或无解，应在步骤与最终答案中明确指出。"
                "输出将交由教师复核，不要声称已经程序验证。"
            ),
            "input": json.dumps(prompt, ensure_ascii=False),
            "reasoning": {"effort": self.reasoning_effort},
            "text": {"format": self._output_format(), "verbosity": "medium"},
            "safety_identifier": hashlib.sha256(
                f"math-ai-solver:{request_data.teacher_id}".encode("utf-8")
            ).hexdigest()[:32],
            "store": False,
        }
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with self.recorder.track(
            feature="solution_assistant",
            provider=self.name,
            model=self.model,
            prompt_version="solution-assistant-v1",
            actor_id=request_data.teacher_id,
        ) as run:
            raw = self._request(payload, request)
            run.capture_response(raw)
            if raw.get("status") == "incomplete":
                raise SolutionProviderError("OpenAI 返回未完成结果，请缩短题目或要求后重试")
            try:
                return GeneratedSolution.model_validate(
                    json.loads(self._extract_output_text(raw))
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise SolutionProviderError(f"OpenAI 返回内容不符合解题结构：{exc}") from exc

    def _request(self, payload: dict, request: Request) -> dict:
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")[:500]
            raise SolutionProviderError(f"OpenAI 返回 HTTP {exc.code}：{details}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise SolutionProviderError(f"OpenAI 解题失败：{exc}") from exc

    @staticmethod
    def _extract_output_text(payload: dict) -> str:
        for item in payload.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    return str(content["text"])
        raise KeyError("output_text")

    @staticmethod
    def _output_format() -> dict:
        explanation = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "method": {"type": "string"},
                "steps": {"type": "array", "items": {"type": "string"}},
                "final_answer": {"type": "string"},
            },
            "required": ["method", "steps", "final_answer"],
        }
        properties = {
            "explanation": explanation,
            "knowledge_points": {"type": "array", "items": {"type": "string"}},
            "common_mistakes": {"type": "array", "items": {"type": "string"}},
            "teaching_notes": {"type": "array", "items": {"type": "string"}},
        }
        return {
            "type": "json_schema",
            "name": "high_school_math_solution",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": properties,
                "required": list(properties),
            },
        }


class DeepSeekSolutionProvider(OpenAISolutionProvider):
    name = "deepseek"

    def __init__(
        self, *, api_key: str, model: str, base_url: str,
        timeout_seconds: int = 90, recorder=None, **_kwargs,
    ) -> None:
        self.model = model
        self.recorder = recorder or NullModelRunRecorder()
        self.client = DeepSeekJsonClient(
            api_key=api_key, model=model, base_url=base_url,
            timeout_seconds=timeout_seconds,
        )

    def _request(self, payload: dict, request: Request) -> dict:
        try:
            return self.client.request(
                instructions=payload["instructions"],
                input_text=str(payload["input"]), action="解题",
                output_schema=payload.get("text", {}).get("format"),
            )
        except DeepSeekClientError as exc:
            raise SolutionProviderError(str(exc)) from exc
