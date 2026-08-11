from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ImportRightsBasis = Literal[
    "question_content_user_declared_usable",
    "licensed",
    "original",
    "private_research_only",
]
ImportFileStatus = Literal["registered", "analyzing", "ready_for_segmentation", "failed"]
BoundaryCandidateStatus = Literal["draft", "confirmed", "discarded"]
StructuredDraftStatus = Literal["draft", "confirmed", "imported"]
FormulaReviewStatus = Literal["pending", "needs_review", "confirmed"]
BoundaryQuestionType = Literal[
    "single_choice",
    "multiple_choice",
    "fill_blank",
    "open_response",
    "unknown",
]


class ImportBatchCommand(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    rights_basis: ImportRightsBasis
    rights_statement: str = Field(min_length=6, max_length=2000)
    rights_acknowledged: bool
    owner_id: str = Field(default="owner_teacher", min_length=1, max_length=120)


class ImportPageView(BaseModel):
    page_id: str
    page_number: int
    width_points: float
    height_points: float
    extracted_text: str
    character_count: int
    question_marker_count: int
    embedded_image_count: int
    has_text_layer: bool
    warnings: list[str] = Field(default_factory=list)


class ImportFileSummary(BaseModel):
    file_id: str
    batch_id: str
    original_filename: str
    size_bytes: int
    sha256: str
    page_count: int
    status: ImportFileStatus
    analyzed_page_count: int
    text_page_count: int
    scan_page_count: int
    extracted_character_count: int
    question_marker_count: int
    image_page_count: int
    embedded_image_count: int
    warnings: list[str] = Field(default_factory=list)
    error_message: str
    created_at: str
    updated_at: str


class ImportFileDetail(ImportFileSummary):
    pages: list[ImportPageView] = Field(default_factory=list)


class ImportBatchSummary(BaseModel):
    batch_id: str
    title: str
    rights_basis: ImportRightsBasis
    rights_statement: str
    owner_id: str
    file_count: int
    registered_count: int
    ready_count: int
    failed_count: int
    page_count: int
    question_marker_count: int
    created_at: str
    updated_at: str
    files: list[ImportFileSummary] = Field(default_factory=list)


class ImportWorkspaceStats(BaseModel):
    batches: int = 0
    files: int = 0
    pages: int = 0
    ready_files: int = 0
    scan_pages: int = 0
    question_markers: int = 0


class ImportWorkspace(BaseModel):
    stats: ImportWorkspaceStats
    batches: list[ImportBatchSummary]


class ImportBatchResult(BaseModel):
    batch: ImportBatchSummary
    message: str


class ImportAnalysisResult(BaseModel):
    file: ImportFileDetail
    message: str


class ImportBatchAnalysisResult(BaseModel):
    batch: ImportBatchSummary
    analyzed_count: int
    failed_count: int
    message: str


class BoundaryCandidateCreate(BaseModel):
    start_page: int = Field(ge=1)
    end_page: int = Field(ge=1)
    stem_text: str = Field(min_length=1, max_length=100_000)
    question_type: BoundaryQuestionType = "unknown"
    subquestion_count: int = Field(default=0, ge=0, le=20)
    note: str = Field(default="", max_length=2000)
    editor_id: str = Field(default="owner_teacher", min_length=1, max_length=120)


class BoundaryCandidateUpdate(BoundaryCandidateCreate):
    status: BoundaryCandidateStatus = "draft"


class BoundaryCandidateView(BaseModel):
    candidate_id: str
    file_id: str
    position: int
    start_page: int
    end_page: int
    stem_text: str
    question_type: BoundaryQuestionType
    subquestion_count: int
    status: BoundaryCandidateStatus
    note: str
    editor_id: str
    source_analysis_updated_at: str
    created_at: str
    updated_at: str


class BoundaryCandidateList(BaseModel):
    file_id: str
    source_analysis_updated_at: str
    total: int
    draft_count: int
    confirmed_count: int
    discarded_count: int
    items: list[BoundaryCandidateView] = Field(default_factory=list)


class BoundaryProposalResult(BaseModel):
    candidates: BoundaryCandidateList
    created_count: int
    message: str


class StructuredQuestionOption(BaseModel):
    key: str = Field(min_length=1, max_length=12)
    text: str = Field(default="", max_length=4000)


class StructuredMediaReference(BaseModel):
    page_number: int = Field(ge=1)
    placement: Literal["stem", "solution"] = "stem"
    note: str = Field(default="", max_length=1000)


class StructuredQuestionDraftUpdate(BaseModel):
    question_type: BoundaryQuestionType
    stem_plain: str = Field(min_length=1, max_length=40_000)
    stem_latex: str | None = Field(default=None, max_length=40_000)
    options: list[StructuredQuestionOption] = Field(default_factory=list, max_length=20)
    answer_value: str | None = Field(default=None, max_length=4000)
    solution_method: str = Field(default="待独立编写", max_length=500)
    solution_steps: list[str] = Field(default_factory=list, max_length=100)
    final_answer: str | None = Field(default=None, max_length=4000)
    difficulty: int = Field(default=3, ge=1, le=5)
    formula_status: FormulaReviewStatus = "pending"
    media_references: list[StructuredMediaReference] = Field(default_factory=list, max_length=30)
    note: str = Field(default="", max_length=2000)
    status: StructuredDraftStatus = "draft"
    editor_id: str = Field(default="owner_teacher", min_length=1, max_length=120)


class StructuredQuestionDraftView(StructuredQuestionDraftUpdate):
    draft_id: str
    file_id: str
    boundary_candidate_id: str
    position: int
    start_page: int
    end_page: int
    source_text: str
    warnings: list[str] = Field(default_factory=list)
    imported_question_id: str | None = None
    created_at: str
    updated_at: str


class StructuredQuestionDraftList(BaseModel):
    file_id: str
    total: int
    draft_count: int
    confirmed_count: int
    imported_count: int
    items: list[StructuredQuestionDraftView] = Field(default_factory=list)


class StructuredDraftProposalResult(BaseModel):
    drafts: StructuredQuestionDraftList
    created_count: int
    message: str


class StructuredDraftImportResult(BaseModel):
    draft: StructuredQuestionDraftView
    question_id: str
    already_imported: bool = False
