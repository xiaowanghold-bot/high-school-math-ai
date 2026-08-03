from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.modules.curriculum import InMemoryCurriculumCatalog
from app.modules.lesson_plans.providers import LessonPlanDraftProvider, LessonPlanGenerationContext
from app.modules.lesson_plans.schemas import (
    LessonCurriculumContext,
    LessonPlanContent,
    LessonPlanGenerationMeta,
    LessonPlanGenerationRequest,
    LessonPlanList,
    LessonPlanSummary,
    LessonPlanUpdateCommand,
    LessonPlanView,
    RecommendedQuestion,
)
from app.modules.question_bank import QuestionBank
from app.modules.question_bank.schemas import QuestionSummary


class LessonPlanStudioError(ValueError):
    pass


class LessonPlanStudio:
    """Deep module for curriculum grounding, retrieval, generation and draft persistence."""

    def __init__(
        self,
        *,
        database_path: Path,
        curriculum_catalog: InMemoryCurriculumCatalog,
        question_bank: QuestionBank,
        provider: LessonPlanDraftProvider,
    ) -> None:
        self.database_path = database_path
        self.curriculum_catalog = curriculum_catalog
        self.question_bank = question_bank
        self.provider = provider
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def create(self, request: LessonPlanGenerationRequest) -> LessonPlanView:
        curriculum = self._curriculum_context(request.curriculum_node_id)
        questions = self._retrieve_questions(curriculum, request.question_count)
        generated = self.provider.generate(
            LessonPlanGenerationContext(request=request, curriculum=curriculum, questions=questions)
        )
        if sum(item.minutes for item in generated.teaching_flow) != request.duration_minutes:
            raise LessonPlanStudioError("教学流程分钟数之和必须等于课时长度")
        recommended = [
            RecommendedQuestion(
                question_id=item.question_id,
                stem=item.stem_plain,
                difficulty=item.difficulty,
                usage=f"用于{['概念辨析', '例题探究', '课堂变式'][index % 3]}",
                verification_status=item.verification_status,
            )
            for index, item in enumerate(questions)
        ]
        warnings = ["所有 AI 生成内容必须由教师审核后使用"]
        if not questions:
            warnings.append("当前章节暂无独立验证通过的题目，教案未绑定题库例题")
        elif any(item.review_status != "approved" for item in questions):
            warnings.append("推荐题目已通过数学验证，但仍有题目等待教师确认")
        plan_id = f"lp_{uuid4().hex[:12]}"
        now = self._now()
        plan = LessonPlanView(
            lesson_plan_id=plan_id,
            status="draft",
            version=1,
            created_at=now,
            updated_at=now,
            request=request,
            curriculum=curriculum,
            content=LessonPlanContent(
                **generated.model_dump(), recommended_questions=recommended
            ),
            generation=LessonPlanGenerationMeta(
                provider=self.provider.name,
                model=self.provider.model,
                mode="live_ai" if self.provider.name == "openai" else "local_preview",
                retrieved_question_ids=[item.question_id for item in questions],
                warnings=warnings,
            ),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO lesson_plans
                (lesson_plan_id, status, version, curriculum_node_id, title, provider,
                 raw_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.lesson_plan_id,
                    plan.status,
                    plan.version,
                    request.curriculum_node_id,
                    plan.content.title,
                    plan.generation.provider,
                    plan.model_dump_json(),
                    now,
                    now,
                ),
            )
        return plan

    def list(self, *, limit: int = 30) -> LessonPlanList:
        with self._connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM lesson_plans").fetchone()[0]
            rows = connection.execute(
                """
                SELECT lesson_plan_id, title, status, version, curriculum_node_id,
                       provider, raw_json, updated_at
                FROM lesson_plans ORDER BY updated_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        items = []
        for row in rows:
            raw = json.loads(row["raw_json"])
            items.append(
                LessonPlanSummary(
                    lesson_plan_id=row["lesson_plan_id"],
                    title=row["title"],
                    status=row["status"],
                    version=row["version"],
                    curriculum_node_id=row["curriculum_node_id"],
                    topic=raw["curriculum"]["topic"],
                    provider=row["provider"],
                    updated_at=row["updated_at"],
                )
            )
        return LessonPlanList(items=items, total=total)

    def get(self, lesson_plan_id: str) -> LessonPlanView:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT raw_json FROM lesson_plans WHERE lesson_plan_id = ?", (lesson_plan_id,)
            ).fetchone()
        if row is None:
            raise KeyError(lesson_plan_id)
        return LessonPlanView.model_validate_json(row["raw_json"])

    def update(self, lesson_plan_id: str, command: LessonPlanUpdateCommand) -> LessonPlanView:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT raw_json FROM lesson_plans WHERE lesson_plan_id = ?", (lesson_plan_id,)
            ).fetchone()
            if row is None:
                raise KeyError(lesson_plan_id)
            current = LessonPlanView.model_validate_json(row["raw_json"])
            if sum(item.minutes for item in command.content.teaching_flow) != current.request.duration_minutes:
                raise LessonPlanStudioError("教学流程分钟数之和必须等于课时长度")
            now = self._now()
            updated = current.model_copy(
                update={
                    "content": command.content,
                    "version": current.version + 1,
                    "updated_at": now,
                }
            )
            connection.execute(
                """
                UPDATE lesson_plans SET title = ?, version = ?, raw_json = ?, updated_at = ?
                WHERE lesson_plan_id = ?
                """,
                (
                    updated.content.title,
                    updated.version,
                    updated.model_dump_json(),
                    now,
                    lesson_plan_id,
                ),
            )
        return updated

    def _curriculum_context(self, node_id: str) -> LessonCurriculumContext:
        try:
            node = self.curriculum_catalog.get_node(node_id)
        except KeyError as exc:
            raise LessonPlanStudioError("所选教材节点不存在") from exc
        if node.node_type not in {"section", "knowledge_point"}:
            raise LessonPlanStudioError("请选择教材中的一节或一个知识点")
        lineage = [node]
        current = node
        while current.parent_id:
            current = self.curriculum_catalog.get_node(current.parent_id)
            lineage.append(current)
        chapter = next(item for item in lineage if item.node_type == "chapter")
        section = next(item for item in lineage if item.node_type == "section")
        if node.node_type == "knowledge_point":
            knowledge_points = [node.name]
        else:
            knowledge_points = self._child_knowledge_points(node.node_id)
        return LessonCurriculumContext(
            node_id=node.node_id,
            volume=node.volume,
            chapter=chapter.name,
            section=section.name,
            topic=node.name,
            description=node.description,
            competencies=node.primary_competencies,
            common_errors=node.common_errors,
            knowledge_points=knowledge_points,
        )

    def _child_knowledge_points(self, node_id: str) -> list[str]:
        def visit(item) -> list[str] | None:
            if item.node_id == node_id:
                return [child.name for child in item.children if child.node_type == "knowledge_point"]
            for child in item.children:
                found = visit(child)
                if found is not None:
                    return found
            return None

        return visit(self.curriculum_catalog.get_tree()) or []

    def _retrieve_questions(
        self, curriculum: LessonCurriculumContext, count: int
    ) -> list[QuestionSummary]:
        if count == 0:
            return []
        page = self.question_bank.search(
            query=curriculum.section,
            verification_status="passed",
            page_size=100,
        )
        exact = [
            item for item in page.items
            if item.section and item.section.endswith(curriculum.section)
        ]
        pool = exact or page.items
        if not pool:
            fallback = self.question_bank.search(
                verification_status="passed",
                page_size=100,
            )
            pool = [
                item for item in fallback.items
                if item.chapter and item.chapter.endswith(curriculum.chapter)
            ]
        return sorted(pool, key=lambda item: (item.difficulty, item.question_id))[:count]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS lesson_plans (
                    lesson_plan_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    curriculum_node_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_lesson_plans_updated
                ON lesson_plans(updated_at DESC);
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
