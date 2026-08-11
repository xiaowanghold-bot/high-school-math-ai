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
