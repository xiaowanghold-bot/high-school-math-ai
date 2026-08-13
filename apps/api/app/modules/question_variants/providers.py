from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.modules.model_operations import ModelRunRecorder, NullModelRunRecorder
from app.modules.deepseek import DeepSeekClientError, DeepSeekJsonClient
from app.modules.question_bank.schemas import QuestionDetail, QuestionOptionDraft
from app.modules.question_variants.schemas import (
    GeneratedQuestionVariant,
    QuestionVariantGenerationRequest,
)


class QuestionVariantProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class QuestionVariantGenerationContext:
    source: QuestionDetail
    request: QuestionVariantGenerationRequest


class QuestionVariantProvider(Protocol):
    name: str
    model: str

    def generate(self, context: QuestionVariantGenerationContext) -> GeneratedQuestionVariant: ...


class LocalDiagnosticVariantProvider:
    """Creates a deterministic misconception-diagnosis task from a verified MCQ."""

    name = "local_rule"
    model = "diagnostic-variant-v1"

    def __init__(self, *, recorder: ModelRunRecorder | None = None) -> None:
        self.recorder = recorder or NullModelRunRecorder()

    def generate(self, context: QuestionVariantGenerationContext) -> GeneratedQuestionVariant:
        with self.recorder.track(
            feature="question_variant",
            provider=self.name,
            model=self.model,
            prompt_version="question-variant-v1",
            actor_id=context.request.teacher_id,
        ):
            return self._generate(context)

    def _generate(self, context: QuestionVariantGenerationContext) -> GeneratedQuestionVariant:
        if context.request.variant_kind != "diagnostic":
            raise QuestionVariantProviderError(
                "当前未配置大模型；本地模式仅支持错因诊断变式。数值、难度和情境变式需配置 OpenAI API Key。"
            )
        source = context.source
        if source.question_type != "single_choice":
            raise QuestionVariantProviderError("本地错因诊断变式目前只支持单选题")
        options = source.raw.get("options") or []
        correct_key = (source.answer_value or "").strip()
        wrong = next(
            (
                item
                for item in options
                if str(item.get("key", "")).strip() and str(item.get("key", "")).strip() != correct_key
            ),
            None,
        )
        if not correct_key or wrong is None:
            raise QuestionVariantProviderError("原题缺少可识别的正确选项或干扰项，无法生成诊断变式")
        wrong_key = str(wrong.get("key", "")).strip()
        wrong_text = str(wrong.get("latex") or wrong.get("plain_text") or "").strip()
        source_solution = (source.raw.get("solutions") or [{}])[0]
        source_steps = [
            str(step).strip() for step in source_solution.get("steps_latex", []) if str(step).strip()
        ]
        steps = [
            f"原题已经独立验证，正确选项为 {correct_key}。",
            f"选项 {wrong_key}（{wrong_text}）与原题条件或正确推理不一致。",
            *source_steps[:6],
        ]
        instruction = context.request.instruction.strip()
        if instruction:
            steps.append(f"教师补充要求：{instruction}")
        return GeneratedQuestionVariant(
            question_type="open_response",
            stem_plain=(
                f"阅读原题并诊断错误：{source.stem_plain}\n"
                f"某同学选择了 {wrong_key}（{wrong_text}）。请判断该选择是否正确，并写出关键理由。"
            ),
            stem_latex=None,
            options=[],
            answer_value=f"不正确，原题正确选项为 {correct_key}",
            solution_method="错因诊断",
            solution_steps=steps,
            final_answer=f"该选择不正确；正确选项为 {correct_key}。",
            difficulty=context.request.target_difficulty or min(5, source.difficulty + 1),
            verification_status="passed",
            verification_details=[
                "该诊断题由已验证单选题和一个已确认错误的干扰项确定性生成。",
                f"所依赖原题 {source.question_id} 的独立验证状态为 passed。",
            ],
        )


class OpenAIQuestionVariantProvider:
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

    def generate(self, context: QuestionVariantGenerationContext) -> GeneratedQuestionVariant:
        source = context.source
        request_data = context.request.model_dump(exclude={"teacher_id"})
        prompt_context = {
            "variant_requirements": request_data,
            "source_question": {
                "question_id": source.question_id,
                "question_type": source.question_type,
                "stem_plain": source.stem_plain,
                "stem_latex": source.raw.get("stem", {}).get("latex"),
                "options": source.raw.get("options") or [],
                "answer": source.answer_value,
                "verified_solution": source.raw.get("solutions") or [],
                "curriculum": source.raw.get("curriculum") or {},
                "difficulty": source.difficulty,
                "stem_images": [
                    {
                        "alt_text": image.alt_text,
                        "caption": image.caption,
                        "width": image.width,
                        "height": image.height,
                    }
                    for image in source.images
                    if image.placement == "stem"
                ],
            },
        }
        safety_identifier = hashlib.sha256(
            f"math-ai-variant:{context.request.teacher_id}".encode("utf-8")
        ).hexdigest()[:32]
        payload = {
            "model": self.model,
            "instructions": (
                "你是中国高中数学命题教师。基于一道人教A版适配且已验证的原题，生成一道新的中文变式草稿。"
                "必须保持知识点一致，完整给出可独立作答的题干、答案和原创解析；不得虚构题源、年份或教材页码。"
                "数值变式必须重新计算答案，选择题必须保证唯一正确选项。图片只可依据给出的文字说明复用，不得臆造图中信息。"
                "输出只是待教师审核草稿，不要声称已经通过独立数学验证。"
            ),
            "input": json.dumps(prompt_context, ensure_ascii=False),
            "reasoning": {"effort": self.reasoning_effort},
            "text": {"format": self._output_format(), "verbosity": "medium"},
            "safety_identifier": safety_identifier,
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
            feature="question_variant",
            provider=self.name,
            model=self.model,
            prompt_version="question-variant-v1",
            actor_id=context.request.teacher_id,
        ) as run:
            raw = self._request(payload, request)
            run.capture_response(raw)
            if raw.get("status") == "incomplete":
                raise QuestionVariantProviderError("OpenAI 返回未完成结果，请缩短补充要求后重试")
            try:
                content = json.loads(self._extract_output_text(raw))
                generated = GeneratedQuestionVariant.model_validate(
                    {
                        **content,
                        "verification_status": "needs_math_review",
                        "verification_details": ["大模型生成了答案与解析，尚未经过独立数学验证。"],
                    }
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise QuestionVariantProviderError(f"OpenAI 返回内容不符合题目结构：{exc}") from exc
            return generated

    def _request(self, payload: dict, request: Request) -> dict:
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")[:500]
            raise QuestionVariantProviderError(
                f"OpenAI 返回 HTTP {exc.code}：{details}"
            ) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise QuestionVariantProviderError(f"OpenAI 题目变式生成失败：{exc}") from exc

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
        option = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"key": {"type": "string"}, "text": {"type": "string"}},
            "required": ["key", "text"],
        }
        properties = {
            "question_type": {"type": "string"},
            "stem_plain": {"type": "string"},
            "stem_latex": {"type": ["string", "null"]},
            "options": {"type": "array", "items": option},
            "answer_value": {"type": "string"},
            "solution_method": {"type": "string"},
            "solution_steps": {"type": "array", "items": {"type": "string"}},
            "final_answer": {"type": "string"},
            "difficulty": {"type": "integer", "minimum": 1, "maximum": 5},
        }
        return {
            "type": "json_schema",
            "name": "high_school_math_question_variant",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": properties,
                "required": list(properties),
            },
        }


class DeepSeekQuestionVariantProvider(OpenAIQuestionVariantProvider):
    name = "deepseek"

    def __init__(
        self, *, api_key: str, model: str, base_url: str,
        timeout_seconds: int = 90, recorder=None, **_kwargs,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.reasoning_effort = "low"
        self.timeout_seconds = timeout_seconds
        self.recorder = recorder or NullModelRunRecorder()
        self.client = DeepSeekJsonClient(
            api_key=api_key, model=model, base_url=base_url,
            timeout_seconds=timeout_seconds,
        )

    def _request(self, payload: dict, request: Request) -> dict:
        try:
            return self.client.request(
                instructions=payload["instructions"],
                input_text=str(payload["input"]), action="题目变式生成",
                output_schema=payload.get("text", {}).get("format"),
            )
        except DeepSeekClientError as exc:
            raise QuestionVariantProviderError(str(exc)) from exc
