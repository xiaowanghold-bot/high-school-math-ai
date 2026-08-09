from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.modules.question_bank.schemas import QuestionSummary


ExamPaperEdition = Literal["student", "answer", "blueprint"]
ExamPaperExportFormat = Literal["docx", "pdf"]
ExamPaperDifficultyProfile = Literal["foundation", "balanced", "challenge"]
ExamPaperReviewPolicy = Literal["approved_only", "verified"]


class ExamPaperItemInput(BaseModel):
    question_id: str = Field(min_length=1, max_length=160)
    score: float = Field(gt=0, le=50)


class ExamPaperCreateCommand(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    duration_minutes: int = Field(default=90, ge=10, le=300)
    instructions: str = Field(default="答题前请填写姓名和班级；所有解答须写出必要过程。", max_length=1000)
    items: list[ExamPaperItemInput] = Field(min_length=1, max_length=50)
    teacher_id: str = Field(default="owner_teacher", min_length=1, max_length=120)


class ExamPaperUpdateCommand(ExamPaperCreateCommand):
    pass


class ExamPaperOptionSnapshot(BaseModel):
    key: str
    text: str


class ExamPaperImageSnapshot(BaseModel):
    asset_id: str
    original_filename: str
    mime_type: str
    width: int
    height: int
    alt_text: str
    caption: str


class ExamPaperQuestionSnapshot(BaseModel):
    question_id: str
    source_revision_count: int
    question_type: str
    stem_plain: str
    stem_latex: str | None = None
    options: list[ExamPaperOptionSnapshot] = Field(default_factory=list)
    answer_value: str | None = None
    solution_method: str | None = None
    solution_steps: list[str] = Field(default_factory=list)
    final_answer: str | None = None
    volume: str | None = None
    chapter: str | None = None
    section: str | None = None
    knowledge_point_ids: list[str] = Field(default_factory=list)
    difficulty: int
    verification_status: str
    review_status: str
    source_document: str
    license_status: str
    images: list[ExamPaperImageSnapshot] = Field(default_factory=list)


class ExamPaperItemView(BaseModel):
    item_id: str
    position: int
    section_title: str
    score: float
    question: ExamPaperQuestionSnapshot


class ExamPaperBreakdownItem(BaseModel):
    label: str
    question_count: int
    score: float


class ExamPaperView(BaseModel):
    exam_paper_id: str
    status: Literal["draft"] = "draft"
    version: int
    title: str
    duration_minutes: int
    instructions: str
    total_score: float
    items: list[ExamPaperItemView]
    chapter_breakdown: list[ExamPaperBreakdownItem]
    difficulty_breakdown: list[ExamPaperBreakdownItem]
    warnings: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ExamPaperSummary(BaseModel):
    exam_paper_id: str
    title: str
    status: str
    version: int
    duration_minutes: int
    total_score: float
    question_count: int
    updated_at: str


class ExamPaperList(BaseModel):
    items: list[ExamPaperSummary]
    total: int


class ExamPaperTypeQuota(BaseModel):
    question_type: str = Field(min_length=1, max_length=80)
    count: int = Field(ge=1, le=30)


class ExamPaperComposeCommand(BaseModel):
    target_score: float = Field(ge=5, le=300)
    difficulty_profile: ExamPaperDifficultyProfile = "balanced"
    type_quotas: list[ExamPaperTypeQuota] = Field(min_length=1, max_length=8)
    chapters: list[str] = Field(default_factory=list, max_length=12)
    review_policy: ExamPaperReviewPolicy = "approved_only"
    exclude_question_ids: list[str] = Field(default_factory=list, max_length=100)
    seed: str = Field(default="default", max_length=120)

    @model_validator(mode="after")
    def validate_blueprint(self) -> "ExamPaperComposeCommand":
        question_types = [item.question_type for item in self.type_quotas]
        if len(question_types) != len(set(question_types)):
            raise ValueError("同一题型只能设置一次数量")
        if sum(item.count for item in self.type_quotas) > 50:
            raise ValueError("自动组卷最多选择 50 道题")
        if self.target_score * 2 != round(self.target_score * 2):
            raise ValueError("目标总分必须以 0.5 分为最小单位")
        return self


class ExamPaperProposalItem(BaseModel):
    question: QuestionSummary
    score: float
    selection_reason: str


class ExamPaperProposal(BaseModel):
    target_score: float
    actual_score: float
    average_difficulty: float
    items: list[ExamPaperProposalItem]
    chapter_breakdown: list[ExamPaperBreakdownItem]
    difficulty_breakdown: list[ExamPaperBreakdownItem]
    warnings: list[str] = Field(default_factory=list)
