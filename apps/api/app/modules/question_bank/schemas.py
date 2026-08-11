from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ReviewDecision = Literal["approved", "changes_requested", "rejected"]
QuestionImagePlacement = Literal["stem", "solution"]


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
    images: list["QuestionImage"] = Field(default_factory=list)
    revision_count: int = 0


class QuestionOptionDraft(BaseModel):
    key: str = Field(min_length=1, max_length=12)
    text: str = Field(default="", max_length=4000)


class QuestionRevisionCommand(BaseModel):
    stem_plain: str = Field(min_length=1, max_length=20000)
    stem_latex: str | None = Field(default=None, max_length=20000)
    options: list[QuestionOptionDraft] = Field(default_factory=list, max_length=20)
    answer_value: str | None = Field(default=None, max_length=4000)
    solution_method: str = Field(default="教师修订", max_length=500)
    solution_steps: list[str] = Field(default_factory=list, max_length=100)
    final_answer: str | None = Field(default=None, max_length=4000)
    editor_id: str = Field(default="owner_teacher", min_length=1, max_length=120)
    note: str = Field(default="教师在审核台手工修订", max_length=2000)


class QuestionRevisionResult(BaseModel):
    question: QuestionDetail
    revision_id: int
    verification_reset: bool


class QuestionImage(BaseModel):
    image_id: str
    question_id: str
    placement: QuestionImagePlacement
    original_filename: str
    mime_type: str
    width: int
    height: int
    alt_text: str
    caption: str
    sort_order: int
    content_url: str
    created_at: str
    updated_at: str


class QuestionImageMetadataCommand(BaseModel):
    placement: QuestionImagePlacement | None = None
    alt_text: str | None = Field(default=None, max_length=500)
    caption: str | None = Field(default=None, max_length=1000)


class QuestionImageOrderCommand(BaseModel):
    image_ids: list[str] = Field(min_length=1, max_length=8)


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
    by_work_queue: dict[str, int]
    by_module: dict[str, int]
    publishable: int
