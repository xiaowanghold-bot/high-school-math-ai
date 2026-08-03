from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


LessonType = Literal["new_lesson", "review", "exercise"]


class LessonPlanGenerationRequest(BaseModel):
    curriculum_node_id: str
    lesson_type: LessonType = "new_lesson"
    duration_minutes: int = Field(default=45, ge=20, le=120)
    student_profile: str = Field(
        default="基础中等，能够完成教材基础练习，抽象概括能力需要支架",
        min_length=2,
        max_length=500,
    )
    focus: str = Field(default="", max_length=500)
    question_count: int = Field(default=3, ge=0, le=8)
    teacher_id: str = Field(default="owner_teacher", min_length=1, max_length=120)


class LessonCurriculumContext(BaseModel):
    node_id: str
    volume: str
    chapter: str
    section: str
    topic: str
    description: str
    competencies: list[str]
    common_errors: list[str]
    knowledge_points: list[str]


class TeachingPhase(BaseModel):
    phase: str
    minutes: int = Field(ge=1, le=120)
    teacher_activity: str
    student_activity: str
    assessment: str


class RecommendedQuestion(BaseModel):
    question_id: str
    stem: str
    difficulty: int
    usage: str
    verification_status: str


class GeneratedLessonPlanContent(BaseModel):
    title: str
    objectives: list[str] = Field(min_length=1, max_length=8)
    key_points: list[str] = Field(min_length=1, max_length=6)
    difficulties: list[str] = Field(min_length=1, max_length=6)
    teaching_flow: list[TeachingPhase] = Field(min_length=2, max_length=10)
    homework: list[str] = Field(min_length=1, max_length=8)
    board_plan: list[str] = Field(min_length=1, max_length=8)
    teacher_notes: list[str] = Field(default_factory=list, max_length=8)


class LessonPlanContent(GeneratedLessonPlanContent):
    recommended_questions: list[RecommendedQuestion] = Field(default_factory=list)


class LessonPlanGenerationMeta(BaseModel):
    provider: str
    model: str
    mode: str
    retrieved_question_ids: list[str]
    warnings: list[str] = Field(default_factory=list)


class LessonPlanView(BaseModel):
    lesson_plan_id: str
    status: str
    version: int
    created_at: str
    updated_at: str
    request: LessonPlanGenerationRequest
    curriculum: LessonCurriculumContext
    content: LessonPlanContent
    generation: LessonPlanGenerationMeta


class LessonPlanSummary(BaseModel):
    lesson_plan_id: str
    title: str
    status: str
    version: int
    curriculum_node_id: str
    topic: str
    provider: str
    updated_at: str


class LessonPlanList(BaseModel):
    items: list[LessonPlanSummary]
    total: int


class LessonPlanUpdateCommand(BaseModel):
    content: LessonPlanContent
    editor_id: str = Field(default="owner_teacher", min_length=1, max_length=120)
