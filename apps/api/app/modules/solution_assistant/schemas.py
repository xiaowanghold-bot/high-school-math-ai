from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


SolutionMode = Literal["standard", "alternative"]
SolutionConfidence = Literal[
    "program_verified",
    "model_reviewed",
    "teacher_review_required",
]


class SolutionRequest(BaseModel):
    question_text: str = Field(min_length=5, max_length=30000)
    solution_mode: SolutionMode = "standard"
    teacher_instruction: str = Field(default="", max_length=2000)
    teacher_id: str = Field(default="owner_teacher", min_length=1, max_length=120)


class SolutionExplanation(BaseModel):
    method: str = Field(min_length=1, max_length=500)
    steps: list[str] = Field(min_length=1, max_length=100)
    final_answer: str = Field(min_length=1, max_length=4000)


class GeneratedSolution(BaseModel):
    explanation: SolutionExplanation
    knowledge_points: list[str] = Field(default_factory=list, max_length=30)
    common_mistakes: list[str] = Field(default_factory=list, max_length=20)
    teaching_notes: list[str] = Field(default_factory=list, max_length=20)


class SolutionResult(BaseModel):
    question_text: str
    solution_mode: SolutionMode
    explanation: SolutionExplanation
    knowledge_points: list[str]
    common_mistakes: list[str]
    teaching_notes: list[str]
    confidence_status: SolutionConfidence
    verification_evidence: list[str]
    provider: str
    model: str
    mode: Literal["verified_bank", "live_ai"]
    matched_question_id: str | None = None
    match_score: float | None = Field(default=None, ge=0, le=1)
    alternative_available: bool = False
    warnings: list[str] = Field(default_factory=list)
