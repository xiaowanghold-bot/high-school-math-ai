from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.modules.model_operations import ModelRunRecorder, NullModelRunRecorder
from app.modules.deepseek import DeepSeekClientError, DeepSeekJsonClient
from app.modules.lesson_plans.schemas import (
    GeneratedLessonPlanContent,
    LessonCurriculumContext,
    LessonPlanBlock,
    LessonPlanContent,
    LessonPlanGenerationRequest,
    LessonPlanView,
    TeachingPhase,
)
from app.modules.question_bank.schemas import QuestionSummary


class LessonPlanProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class LessonPlanGenerationContext:
    request: LessonPlanGenerationRequest
    curriculum: LessonCurriculumContext
    questions: list[QuestionSummary]


@dataclass(frozen=True)
class LessonPlanRewriteContext:
    plan: LessonPlanView
    content: LessonPlanContent
    block: LessonPlanBlock
    instruction: str
    teacher_id: str


LessonPlanRewriteValue = list[str] | list[TeachingPhase]


class LessonPlanProvider(Protocol):
    name: str
    model: str

    def generate(self, context: LessonPlanGenerationContext) -> GeneratedLessonPlanContent: ...

    def rewrite(self, context: LessonPlanRewriteContext) -> LessonPlanRewriteValue: ...


class TemplateLessonPlanProvider:
    """Deterministic local adapter used before a paid model is configured."""

    name = "local_template"
    model = "teacher-template-v1"

    def __init__(self, *, recorder: ModelRunRecorder | None = None) -> None:
        self.recorder = recorder or NullModelRunRecorder()

    def generate(self, context: LessonPlanGenerationContext) -> GeneratedLessonPlanContent:
        with self.recorder.track(
            feature="lesson_plan_generation",
            provider=self.name,
            model=self.model,
            prompt_version="lesson-plan-v1",
            actor_id=context.request.teacher_id,
        ):
            return self._generate(context)

    def _generate(self, context: LessonPlanGenerationContext) -> GeneratedLessonPlanContent:
        curriculum = context.curriculum
        request = context.request
        phase_names = ["导入与诊断", "概念建构", "例题探究", "变式训练", "总结评价"]
        minutes = self._allocate_minutes(request.duration_minutes, [10, 25, 30, 25, 10])
        question_hint = (
            f"调用已验证题目 {context.questions[0].question_id}，先让学生独立判断再交流依据"
            if context.questions
            else "使用教材例题，引导学生先独立判断再交流依据"
        )
        activities = [
            (
                f"用一个与“{curriculum.topic}”相关的快速判断题检查前置知识，呈现本课问题链。",
                "独立作答并说明判断依据，暴露已有认识。",
                "根据举手与追问结果调整后续支架。",
            ),
            (
                f"围绕{curriculum.description}组织定义、图象和符号语言之间的转换。",
                "用自己的语言概括概念，补全关键条件并互相纠错。",
                "检查是否同时说清对象、范围和结论。",
            ),
            (
                question_hint,
                "先独立完成，再比较不同解法并标出关键转化。",
                "关注推理链完整性和结论成立的条件。",
            ),
            (
                f"围绕易错点“{curriculum.common_errors[0] if curriculum.common_errors else '忽略条件'}”设计一组正反例变式。",
                "小组修正错误解答，归纳可迁移的检查步骤。",
                "用一道出口题判断能否迁移到新情境。",
            ),
            (
                "回扣目标，板书知识结构与解题检查清单，布置分层作业。",
                "完成一分钟总结：我会什么、易错什么、还需追问什么。",
                "收集出口条并记录下一课时需要补偿的学生名单。",
            ),
        ]
        teaching_flow = [
            TeachingPhase(
                phase=phase,
                minutes=minute,
                teacher_activity=activity[0],
                student_activity=activity[1],
                assessment=activity[2],
            )
            for phase, minute, activity in zip(phase_names, minutes, activities, strict=True)
        ]
        competencies = curriculum.competencies or ["数学抽象", "逻辑推理"]
        return GeneratedLessonPlanContent(
            title=f"{curriculum.topic}——{self._lesson_type_label(request.lesson_type)}",
            objectives=[
                f"理解并能用数学语言表述{curriculum.topic}的核心概念与成立条件。",
                f"经历观察、猜想、验证与表达过程，发展{competencies[0]}素养。",
                "能够在典型题和变式中选择合适方法，并用检查清单发现常见错误。",
            ],
            key_points=[f"{curriculum.topic}的概念结构与关键条件", "图象、符号与代数推理之间的转换"],
            difficulties=[
                curriculum.common_errors[0] if curriculum.common_errors else "准确识别结论成立的范围与条件",
                "把局部解题经验概括为可迁移的方法",
            ],
            teaching_flow=teaching_flow,
            homework=[
                "基础层：整理本课概念、性质和一条完整例题解答。",
                "巩固层：完成两道同类变式，并在每一步旁标注使用的条件。",
                "拓展层：改编一道题的条件，说明结论如何变化。",
            ],
            board_plan=[
                f"课题：{curriculum.topic}",
                "一、概念与条件；二、图象/符号转换；三、典型方法；四、易错检查",
                "出口题与课后追问",
            ],
            teacher_notes=[
                f"学情假设：{request.student_profile}",
                request.focus or "生成稿是备课起点，例题难度和课堂节奏需结合班级实际调整。",
            ],
        )

    def rewrite(self, context: LessonPlanRewriteContext) -> LessonPlanRewriteValue:
        with self.recorder.track(
            feature="lesson_block_rewrite",
            provider=self.name,
            model=self.model,
            prompt_version="lesson-block-rewrite-v1",
            actor_id=context.teacher_id,
        ):
            return self._rewrite(context)

    def _rewrite(self, context: LessonPlanRewriteContext) -> LessonPlanRewriteValue:
        focus = context.instruction.strip().rstrip("。")
        if context.block == "teaching_flow":
            return [
                phase.model_copy(
                    update={
                        "teacher_activity": (
                            f"{self._strip_local_rewrite(phase.teacher_activity)}；"
                            f"围绕“{focus}”补充追问与示范。"
                        ),
                        "assessment": (
                            f"{self._strip_local_rewrite(phase.assessment)}；"
                            f"增加与“{focus}”对应的可观察证据。"
                        ),
                    }
                )
                for phase in context.content.teaching_flow
            ]
        current = list(getattr(context.content, context.block))
        if context.block == "teacher_notes":
            note = f"局部改写要求：{focus}。"
            return [*current[:7], note] if note not in current else current
        templates = {
            "objectives": "{item}，并通过“{focus}”相关任务呈现可观察的学习证据。",
            "key_points": "{item}；教学组织突出“{focus}”。",
            "difficulties": "{item}；围绕“{focus}”设置认知冲突与纠错支架。",
            "homework": "{item}；完成后围绕“{focus}”写出关键依据或反思。",
            "board_plan": "{item}（突出：{focus}）",
        }
        template = templates[context.block]
        return [
            template.format(item=self._strip_local_rewrite(item).rstrip("。；"), focus=focus)
            for item in current
        ]

    @staticmethod
    def _strip_local_rewrite(text: str) -> str:
        patterns = [
            r"，并通过“.*?”相关任务呈现可观察的学习证据。?$",
            r"；教学组织突出“.*?”。?$",
            r"；围绕“.*?”设置认知冲突与纠错支架。?$",
            r"；完成后围绕“.*?”写出关键依据或反思。?$",
            r"；围绕“.*?”补充追问与示范。?$",
            r"；增加与“.*?”对应的可观察证据。?$",
            r"（突出：.*?）$",
        ]
        for pattern in patterns:
            text = re.sub(pattern, "", text)
        return text.rstrip()

    @staticmethod
    def _allocate_minutes(total: int, weights: list[int]) -> list[int]:
        minutes = [max(1, round(total * weight / sum(weights))) for weight in weights]
        minutes[-1] += total - sum(minutes)
        return minutes

    @staticmethod
    def _lesson_type_label(lesson_type: str) -> str:
        return {"new_lesson": "新授课", "review": "复习课", "exercise": "习题课"}[lesson_type]


class OpenAIResponsesLessonPlanProvider:
    """Responses API adapter; the rest of the app only sees LessonPlanProvider."""

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

    def generate(self, context: LessonPlanGenerationContext) -> GeneratedLessonPlanContent:
        safety_identifier = hashlib.sha256(
            f"math-ai:{context.request.teacher_id}".encode("utf-8")
        ).hexdigest()[:32]
        prompt_context = {
            "curriculum": context.curriculum.model_dump(),
            "lesson_requirements": context.request.model_dump(exclude={"teacher_id"}),
            "verified_questions": [
                {
                    "question_id": item.question_id,
                    "stem": item.stem_plain,
                    "difficulty": item.difficulty,
                }
                for item in context.questions
            ],
        }
        payload = {
            "model": self.model,
            "instructions": (
                "你是中国高中数学教研员。依据人教A版课程节点和教师学情生成可执行的中文教案。"
                "只使用输入中提供的题目事实，不虚构题源、答案或教材页码。教学流程分钟数之和必须等于课时长度。"
                "目标必须可观察、可评价；把题库例题作为课堂素材而不是照搬来源解析。"
            ),
            "input": json.dumps(prompt_context, ensure_ascii=False),
            "reasoning": {"effort": self.reasoning_effort},
            "text": {"format": self._output_format(), "verbosity": "medium"},
            "safety_identifier": safety_identifier,
            "store": False,
        }
        with self.recorder.track(
            feature="lesson_plan_generation",
            provider=self.name,
            model=self.model,
            prompt_version="lesson-plan-v1",
            actor_id=context.request.teacher_id,
        ) as run:
            raw = self._request_structured_output(payload, action="教案生成")
            run.capture_response(raw)
            if raw.get("status") == "incomplete":
                raise LessonPlanProviderError("OpenAI 返回未完成结果，请缩短输入后重试")
            try:
                content = json.loads(self._extract_output_text(raw))
                result = GeneratedLessonPlanContent.model_validate(content)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise LessonPlanProviderError(f"OpenAI 返回内容不符合教案结构：{exc}") from exc
            if sum(item.minutes for item in result.teaching_flow) != context.request.duration_minutes:
                raise LessonPlanProviderError("OpenAI 返回的教学流程分钟数与课时长度不一致")
            return result

    def rewrite(self, context: LessonPlanRewriteContext) -> LessonPlanRewriteValue:
        current_value = getattr(context.content, context.block)
        prompt_context = {
            "curriculum": context.plan.curriculum.model_dump(),
            "lesson_requirements": context.plan.request.model_dump(exclude={"teacher_id"}),
            "current_lesson_plan": context.content.model_dump(),
            "target_block": context.block,
            "current_block": [
                item.model_dump() if isinstance(item, TeachingPhase) else item
                for item in current_value
            ],
            "teacher_instruction": context.instruction,
        }
        safety_identifier = hashlib.sha256(
            f"math-ai:{context.teacher_id}".encode("utf-8")
        ).hexdigest()[:32]
        payload = {
            "model": self.model,
            "instructions": (
                "你是中国高中数学教研员。只改写指定的教案内容块，不改动其他内容。"
                "必须遵守人教A版课程上下文、教师指令和当前教案事实，不虚构题源或教材页码。"
                "教学目标要可观察可评价；教学流程必须保持总分钟数不变。"
            ),
            "input": json.dumps(prompt_context, ensure_ascii=False),
            "reasoning": {"effort": self.reasoning_effort},
            "text": {
                "format": self._rewrite_output_format(context.block),
                "verbosity": "medium",
            },
            "safety_identifier": safety_identifier,
            "store": False,
        }
        with self.recorder.track(
            feature="lesson_block_rewrite",
            provider=self.name,
            model=self.model,
            prompt_version="lesson-block-rewrite-v1",
            actor_id=context.teacher_id,
        ) as run:
            raw = self._request_structured_output(payload, action="教案局部改写")
            run.capture_response(raw)
            if raw.get("status") == "incomplete":
                raise LessonPlanProviderError("OpenAI 返回未完成结果，请缩短改写指令后重试")
            try:
                content = json.loads(self._extract_output_text(raw))
                if context.block == "teaching_flow":
                    return [TeachingPhase.model_validate(item) for item in content["teaching_flow"]]
                items = content["items"]
                if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
                    raise TypeError("items 必须是字符串数组")
                return items
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise LessonPlanProviderError(f"OpenAI 返回的局部改写不符合结构：{exc}") from exc

    def _request_structured_output(self, payload: dict, *, action: str) -> dict:
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")[:500]
            raise LessonPlanProviderError(f"OpenAI 返回 HTTP {exc.code}：{details}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LessonPlanProviderError(f"OpenAI {action}失败：{exc}") from exc


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
        string_array = {"type": "array", "items": {"type": "string"}}
        phase = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "phase": {"type": "string"},
                "minutes": {"type": "integer"},
                "teacher_activity": {"type": "string"},
                "student_activity": {"type": "string"},
                "assessment": {"type": "string"},
            },
            "required": ["phase", "minutes", "teacher_activity", "student_activity", "assessment"],
        }
        properties = {
            "title": {"type": "string"},
            "objectives": string_array,
            "key_points": string_array,
            "difficulties": string_array,
            "teaching_flow": {"type": "array", "items": phase},
            "homework": string_array,
            "board_plan": string_array,
            "teacher_notes": string_array,
        }
        return {
            "type": "json_schema",
            "name": "high_school_math_lesson_plan",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": properties,
                "required": list(properties),
            },
        }
    @staticmethod
    def _rewrite_output_format(block: LessonPlanBlock) -> dict:
        if block == "teaching_flow":
            item_name = "teaching_flow"
            item_schema = {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "phase": {"type": "string"},
                        "minutes": {"type": "integer"},
                        "teacher_activity": {"type": "string"},
                        "student_activity": {"type": "string"},
                        "assessment": {"type": "string"},
                    },
                    "required": [
                        "phase",
                        "minutes",
                        "teacher_activity",
                        "student_activity",
                        "assessment",
                    ],
                },
            }
        else:
            item_name = "items"
            item_schema = {"type": "array", "items": {"type": "string"}}
        return {
            "type": "json_schema",
            "name": f"lesson_plan_{block}_rewrite",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {item_name: item_schema},
                "required": [item_name],
            },
        }


class DeepSeekLessonPlanProvider(OpenAIResponsesLessonPlanProvider):
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

    def _request_structured_output(self, payload: dict, *, action: str) -> dict:
        try:
            return self.client.request(
                instructions=payload["instructions"],
                input_text=str(payload["input"]), action=action,
                output_schema=payload.get("text", {}).get("format"),
            )
        except DeepSeekClientError as exc:
            raise LessonPlanProviderError(str(exc)) from exc
