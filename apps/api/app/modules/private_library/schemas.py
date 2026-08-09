from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RightsBasis = Literal["original", "licensed", "private_teaching_only"]
LibraryFileKind = Literal["pdf", "docx", "image"]
ExtractionStatus = Literal["extracted", "needs_ocr", "failed"]
TextReviewStatus = Literal["pending", "confirmed"]


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
    by_file_kind: dict[str, int]
