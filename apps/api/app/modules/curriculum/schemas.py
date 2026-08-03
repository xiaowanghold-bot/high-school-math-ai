from __future__ import annotations

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
