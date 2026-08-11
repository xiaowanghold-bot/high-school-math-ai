from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CurriculumNode(BaseModel):
    node_id: str
    parent_id: str | None = None
    volume: str
    node_type: str
    code: str
    name: str
    description: str = ""
    prerequisite_node_ids: list[str] = Field(default_factory=list)
    primary_competencies: list[str] = Field(default_factory=list)
    typical_question_types: list[str] = Field(default_factory=list)
    common_errors: list[str] = Field(default_factory=list)
    gaokao_priority: str
    status: str
    reviewed_by: str


class CurriculumTreeNode(CurriculumNode):
    children: list["CurriculumTreeNode"] = Field(default_factory=list)


class CurriculumSearchItem(BaseModel):
    node_id: str
    code: str
    name: str
    node_type: str
    volume: str
    chapter: str | None = None
    section: str | None = None
    description: str = ""
    primary_competencies: list[str] = Field(default_factory=list)
    gaokao_priority: str
    match_score: float = Field(ge=0, le=1)


class CurriculumSearchResponse(BaseModel):
    query: str
    total: int
    items: list[CurriculumSearchItem]


CurriculumReviewDecision = Literal["draft", "approved", "changes_requested"]


class CurriculumNodePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    primary_competencies: list[str] | None = Field(default=None, max_length=20)
    typical_question_types: list[str] | None = Field(default=None, max_length=30)
    common_errors: list[str] | None = Field(default=None, max_length=30)
    gaokao_priority: Literal["high", "medium", "low"] | None = None


class CurriculumReviewCommand(BaseModel):
    decision: CurriculumReviewDecision
    changes: CurriculumNodePatch = Field(default_factory=CurriculumNodePatch)
    note: str = Field(default="", max_length=2000)
    reviewer_id: str = Field(default="owner_teacher", min_length=1, max_length=120)
    cascade: bool = False


class CurriculumReviewRecord(BaseModel):
    review_id: str
    node_id: str
    decision: CurriculumReviewDecision
    changes: CurriculumNodePatch
    note: str
    reviewer_id: str
    created_at: str


class CurriculumReviewSummary(BaseModel):
    node_id: str
    parent_id: str | None
    volume: str
    node_type: str
    code: str
    name: str
    description: str
    review_status: Literal["pending", "draft", "approved", "changes_requested"]
    latest_reviewed_at: str | None = None
    descendant_count: int = 0


class CurriculumReviewCounts(BaseModel):
    total: int = 0
    pending: int = 0
    draft: int = 0
    approved: int = 0
    changes_requested: int = 0


class CurriculumReviewWorkspace(BaseModel):
    volume: str | None
    volume_node_id: str | None = None
    counts: CurriculumReviewCounts
    items: list[CurriculumReviewSummary]


class CurriculumReviewDetail(BaseModel):
    base_node: CurriculumNode
    effective_node: CurriculumNode
    review_status: Literal["pending", "draft", "approved", "changes_requested"]
    descendant_count: int
    history: list[CurriculumReviewRecord]


class CurriculumReviewResult(BaseModel):
    detail: CurriculumReviewDetail
    affected_count: int
    message: str
