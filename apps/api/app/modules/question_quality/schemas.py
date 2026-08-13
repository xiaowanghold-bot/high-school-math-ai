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
    knowledge_point_names: list[str] = Field(default_factory=list)


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


CurriculumRecommendationStatus = Literal[
    "already_mapped", "high_confidence", "review_required", "no_suggestion"
]


class BatchCurriculumQuestion(BaseModel):
    question_id: str
    stem_plain: str
    source_document: str
    source_page_start: int | None = None
    source_page_end: int | None = None
    current_curriculum: CurrentCurriculumMapping
    suggestions: list[CurriculumSuggestion] = Field(default_factory=list)
    recommendation_status: CurriculumRecommendationStatus


class BatchCurriculumWorkspace(BaseModel):
    total: int
    mapped_count: int
    high_confidence_count: int
    review_required_count: int
    no_suggestion_count: int
    items: list[BatchCurriculumQuestion] = Field(default_factory=list)


class BatchCurriculumInspectCommand(BaseModel):
    question_ids: list[str] = Field(min_length=1, max_length=100)


class BatchCurriculumMappingItem(BaseModel):
    question_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)


class BatchCurriculumMappingCommand(BaseModel):
    mappings: list[BatchCurriculumMappingItem] = Field(min_length=1, max_length=100)
    teacher_id: str = Field(default="owner_teacher", min_length=1, max_length=120)


class BatchCurriculumActionResult(BaseModel):
    applied_count: int
    question_ids: list[str]
    message: str
