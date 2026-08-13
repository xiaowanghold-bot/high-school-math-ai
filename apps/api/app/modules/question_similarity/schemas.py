from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.modules.question_bank.schemas import QuestionSummary


DuplicateRelation = Literal[
    "exact_duplicate",
    "same_problem_different_source",
    "same_problem_different_solution",
    "variant",
    "not_duplicate",
]
CandidateStatus = Literal["proposed", "confirmed", "rejected", "stale"]


class DuplicateCandidate(BaseModel):
    candidate_id: str
    left: QuestionSummary
    right: QuestionSummary
    suggested_relation: DuplicateRelation
    teacher_relation: DuplicateRelation | None = None
    confidence: float = Field(ge=0, le=1)
    signals: list[str] = Field(default_factory=list)
    status: CandidateStatus
    reviewer_id: str | None = None
    review_note: str = ""
    created_at: str
    updated_at: str


class DuplicateWorkspaceStats(BaseModel):
    total: int = 0
    proposed: int = 0
    confirmed: int = 0
    rejected: int = 0
    stale: int = 0
    exact_duplicate: int = 0
    same_problem: int = 0
    variant: int = 0


class DuplicateWorkspace(BaseModel):
    items: list[DuplicateCandidate] = Field(default_factory=list)
    stats: DuplicateWorkspaceStats


class DuplicateScanResult(BaseModel):
    scanned_questions: int
    compared_pairs: int
    active_candidates: int
    new_candidates: int
    stale_candidates: int
    workspace: DuplicateWorkspace


class DuplicateReviewCommand(BaseModel):
    relation: DuplicateRelation
    reviewer_id: str = Field(default="owner_teacher", min_length=1, max_length=120)
    note: str = Field(default="", max_length=2000)


class DuplicateReviewResult(BaseModel):
    candidate: DuplicateCandidate
    message: str
