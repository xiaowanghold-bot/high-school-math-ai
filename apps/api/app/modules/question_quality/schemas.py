from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CurriculumSuggestion(BaseModel):
    node_id: str
    name: str
    volume: str
    chapter: str
    section: str
    confidence: float = Field(ge=0, le=1)
    reasons: list[str]


class CurrentCurriculumMapping(BaseModel):
    volume: str | None = None
    chapter: str | None = None
    section: str | None = None
    knowledge_point_ids: list[str] = Field(default_factory=list)


class VerificationWorkspace(BaseModel):
    status: str
    capability: Literal["already_verified", "rule_based", "teacher_evidence_required"]
    source_answer: str | None = None
    computed_answer: str | None = None
    method: str | None = None
    details: list[str] = Field(default_factory=list)


class QuestionQualityWorkspace(BaseModel):
    question_id: str
    current_curriculum: CurrentCurriculumMapping
    curriculum_suggestions: list[CurriculumSuggestion]
    verification: VerificationWorkspace


class CurriculumMappingCommand(BaseModel):
    node_id: str = Field(min_length=1, max_length=160)
    teacher_id: str = Field(default="owner_teacher", min_length=1, max_length=120)


class ManualVerificationCommand(BaseModel):
    conclusion: Literal["passed", "inconsistent", "inconclusive"]
    computed_answer: str = Field(default="", max_length=4000)
    evidence_steps: list[str] = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=2000)
    independently_checked: bool
    verifier_id: str = Field(default="owner_teacher", min_length=1, max_length=120)


class QualityActionResult(BaseModel):
    workspace: QuestionQualityWorkspace
    status: str
    message: str

