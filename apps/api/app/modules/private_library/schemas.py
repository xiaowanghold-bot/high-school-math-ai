from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RightsBasis = Literal["original", "licensed", "private_teaching_only"]
LibraryFileKind = Literal["pdf", "docx", "image"]
ExtractionStatus = Literal["extracted", "needs_ocr", "failed"]
TextReviewStatus = Literal["pending", "confirmed"]
LibraryLifecycleState = Literal["active", "trashed"]
CandidateStatus = Literal["draft", "discarded", "imported"]
QuestionType = Literal["single_choice", "multiple_choice", "fill_blank", "open_response"]


class LibraryIngestCommand(BaseModel):
    title: str = Field(default="", max_length=300)
    rights_basis: RightsBasis
    rights_statement: str = Field(min_length=6, max_length=2000)
    rights_acknowledged: bool
    owner_id: str = Field(default="owner_teacher", min_length=1, max_length=120)


class LibraryTextReviewCommand(BaseModel):
    corrected_text: str = Field(max_length=2_000_000)
    note: str = Field(default="", max_length=2000)
    confirm: bool = False
    reviewer_id: str = Field(default="owner_teacher", min_length=1, max_length=120)


class LibraryOCRCommand(BaseModel):
    external_processing_consent: bool
    teacher_id: str = Field(default="owner_teacher", min_length=1, max_length=120)


class LibraryOCRResult(BaseModel):
    item: "LibraryItemView"
    provider: str
    warnings: list[str] = Field(default_factory=list)


class LibraryAIRepairCommand(BaseModel):
    draft_text: str = Field(min_length=1, max_length=2_000_000)
    instruction: str = Field(default="", max_length=2000)
    external_processing_consent: bool
    teacher_id: str = Field(default="owner_teacher", min_length=1, max_length=120)


class LibraryAIRepairResult(BaseModel):
    repaired_text: str
    provider: str
    model: str
    warnings: list[str] = Field(default_factory=list)


class LibraryLifecycleCommand(BaseModel):
    action: Literal["trash", "restore"]
    actor_id: str = Field(default="owner_teacher", min_length=1, max_length=120)
    reason: str = Field(default="用户删除", max_length=2000)


class QuestionCandidateOption(BaseModel):
    key: str = Field(min_length=1, max_length=12)
    text: str = Field(default="", max_length=4000)


class QuestionCandidateUpdate(BaseModel):
    question_type: QuestionType
    stem_plain: str = Field(min_length=1, max_length=20000)
    stem_latex: str | None = Field(default=None, max_length=20000)
    options: list[QuestionCandidateOption] = Field(default_factory=list, max_length=20)
    answer_value: str | None = Field(default=None, max_length=4000)
    solution_method: str = Field(default="教师整理", max_length=500)
    solution_steps: list[str] = Field(default_factory=list, max_length=100)
    final_answer: str | None = Field(default=None, max_length=4000)
    difficulty: int = Field(default=3, ge=1, le=5)
    editor_id: str = Field(default="owner_teacher", min_length=1, max_length=120)


class QuestionCandidateView(BaseModel):
    candidate_id: str
    library_item_id: str
    source_version: int
    position: int
    question_type: QuestionType
    stem_plain: str
    stem_latex: str | None
    options: list[QuestionCandidateOption]
    answer_value: str | None
    solution_method: str
    solution_steps: list[str]
    final_answer: str | None
    difficulty: int
    status: CandidateStatus
    warnings: list[str]
    imported_question_id: str | None
    updated_at: str


class QuestionCandidateList(BaseModel):
    library_item_id: str
    source_version: int
    items: list[QuestionCandidateView]


class CandidateImportResult(BaseModel):
    candidate: QuestionCandidateView
    question_id: str
    already_imported: bool = False


class LibraryItemSummary(BaseModel):
    library_item_id: str
    title: str
    original_filename: str
    file_kind: LibraryFileKind
    mime_type: str
    size_bytes: int
    page_count: int | None
    extraction_status: ExtractionStatus
    text_review_status: TextReviewStatus
    extracted_char_count: int
    corrected_char_count: int
    rights_basis: RightsBasis
    lifecycle_state: LibraryLifecycleState = "active"
    trashed_at: str | None = None
    visibility: Literal["private"] = "private"
    public_search_allowed: bool = False
    model_training_allowed: bool = False
    version: int
    created_at: str
    updated_at: str


class LibraryItemView(LibraryItemSummary):
    source_sha256: str
    extracted_text: str
    corrected_text: str
    rights_statement: str
    adaptation_allowed: bool
    warnings: list[str]
    review_note: str


class LibraryItemList(BaseModel):
    items: list[LibraryItemSummary]
    total: int


class LibraryStats(BaseModel):
    total: int
    pending_review: int
    confirmed: int
    needs_ocr: int
    trashed: int = 0
    by_file_kind: dict[str, int]
