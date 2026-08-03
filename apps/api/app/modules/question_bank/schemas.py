from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ReviewDecision = Literal["approved", "changes_requested", "rejected"]


class ImportResult(BaseModel):
    batch_id: str
    declared_count: int
    created_count: int
    skipped_count: int
    quarantined_count: int = 0


class ImportBatchView(BaseModel):
    batch_id: str
    schema_version: str
    publication_status: str
    declared_count: int
    imported_at: str


class CurationResult(BaseModel):
    package_id: str
    candidate_count: int
    applied_count: int
    skipped_count: int
    passed_count: int
    inconsistency_count: int


class QuestionSummary(BaseModel):
    question_id: str
    status: str
    review_status: str
    visibility: str
    question_type: str
    stem_plain: str
    answer_value: str | None
    volume: str | None
    chapter: str | None
    section: str | None
    knowledge_point_ids: list[str]
    difficulty: int
    verification_status: str
    source_document: str
    source_page_start: int | None
    source_page_end: int | None
    license_status: str
    publication_blockers: list[str]


class QuestionDetail(QuestionSummary):
    raw: dict[str, Any]
    reviews: list[dict[str, Any]]


class QuestionSearchPage(BaseModel):
    items: list[QuestionSummary]
    total: int
    page: int
    page_size: int


class ReviewCommand(BaseModel):
    decision: ReviewDecision
    note: str = Field(default="", max_length=2000)
    reviewer_id: str = Field(default="owner_teacher", min_length=1, max_length=120)


class ReviewResult(BaseModel):
    question_id: str
    decision: ReviewDecision
    status: str
    review_status: str
    reviewed_at: str


class PublishDecision(BaseModel):
    question_id: str
    allowed: bool
    blockers: list[str]
    status: str
    visibility: str


class QuestionBankStats(BaseModel):
    total: int
    by_review_status: dict[str, int]
    by_verification_status: dict[str, int]
    by_chapter: dict[str, int]
    publishable: int
