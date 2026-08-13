from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.modules.question_bank.schemas import QuestionDetail, QuestionOptionDraft


QuestionVariantKind = Literal["diagnostic", "numeric", "difficulty", "context"]


class QuestionVariantGenerationRequest(BaseModel):
    variant_kind: QuestionVariantKind = "diagnostic"
    target_difficulty: int | None = Field(default=None, ge=1, le=5)
    instruction: str = Field(default="", max_length=2000)
    teacher_id: str = Field(default="owner_teacher", min_length=1, max_length=120)


class GeneratedQuestionVariant(BaseModel):
    question_type: str = Field(min_length=1, max_length=80)
    stem_plain: str = Field(min_length=1, max_length=20000)
    stem_latex: str | None = Field(default=None, max_length=20000)
    options: list[QuestionOptionDraft] = Field(default_factory=list, max_length=20)
    answer_value: str = Field(min_length=1, max_length=4000)
    solution_method: str = Field(min_length=1, max_length=500)
    solution_steps: list[str] = Field(min_length=1, max_length=100)
    final_answer: str = Field(min_length=1, max_length=4000)
    difficulty: int = Field(ge=1, le=5)
    verification_status: Literal["passed", "needs_math_review"] = "needs_math_review"
    verification_details: list[str] = Field(min_length=1, max_length=20)


class QuestionVariantGenerationResult(BaseModel):
    question: QuestionDetail
    source_question_id: str
    provider: str
    model: str
    mode: Literal["local_rule", "live_ai"]
    warnings: list[str] = Field(default_factory=list)


class TeacherVariantDraftCommand(BaseModel):
    question_type: str = Field(min_length=1, max_length=80)
    stem_plain: str = Field(min_length=1, max_length=20000)
    stem_latex: str | None = Field(default=None, max_length=20000)
    options: list[QuestionOptionDraft] = Field(default_factory=list, max_length=20)
    answer_value: str = Field(default="待教师确认", max_length=4000)
    solution_method: str = Field(default="教师自拟变式", max_length=500)
    solution_steps: list[str] = Field(default_factory=lambda: ["待教师补充或由 DeepSeek 计算"], max_length=100)
    final_answer: str = Field(default="待教师确认", max_length=4000)
    difficulty: int = Field(default=3, ge=1, le=5)
    teacher_id: str = Field(default="owner_teacher", min_length=1, max_length=120)


class TeacherVariantPolishCommand(BaseModel):
    stem_plain: str = Field(min_length=5, max_length=20000)
    stem_latex: str | None = Field(default=None, max_length=20000)
    options: list[QuestionOptionDraft] = Field(default_factory=list, max_length=20)
    instruction: str = Field(default="", max_length=2000)
    teacher_id: str = Field(default="owner_teacher", min_length=1, max_length=120)


class TeacherVariantPolishResult(BaseModel):
    stem_plain: str
    stem_latex: str | None
    options: list[QuestionOptionDraft]
    provider: str
    model: str
    warnings: list[str] = Field(default_factory=list)
