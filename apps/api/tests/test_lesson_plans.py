import json
from pathlib import Path

import pytest

from app.modules.curriculum import CurriculumNode, InMemoryCurriculumCatalog
from app.modules.lesson_plans import (
    LessonPlanGenerationRequest,
    LessonPlanStudio,
    LessonPlanUpdateCommand,
    OpenAIResponsesLessonPlanProvider,
    TemplateLessonPlanProvider,
)
from app.modules.lesson_plans.providers import LessonPlanGenerationContext
from app.modules.lesson_plans.schemas import LessonCurriculumContext
from app.modules.question_bank.schemas import QuestionSearchPage, QuestionSummary


class FakeQuestionBank:
    def search(self, **_: object) -> QuestionSearchPage:
        return QuestionSearchPage(
            items=[
                QuestionSummary(
                    question_id="q_verified_function_01",
                    status="verified",
                    review_status="pending",
                    visibility="private",
                    question_type="single_choice",
                    stem_plain="若函数在给定区间单调递减，比较两个函数值的大小。",
                    answer_value="A",
                    volume="必修第一册",
                    chapter="第三章 函数的概念与性质",
                    section="3.2 函数的基本性质",
                    knowledge_point_ids=["kp_r1_3_2_01"],
                    difficulty=2,
                    verification_status="passed",
                    source_document="test.pdf",
                    source_page_start=1,
                    source_page_end=1,
                    license_status="question_content_user_declared_usable",
                    publication_blockers=["teacher_review_required"],
                )
            ],
            total=1,
            page=1,
            page_size=100,
        )


def _catalog() -> InMemoryCurriculumCatalog:
    common = {
        "description": "",
        "prerequisite_node_ids": [],
        "primary_competencies": [],
        "typical_question_types": [],
        "common_errors": [],
        "gaokao_priority": "high",
        "status": "ready_for_teacher_review",
        "reviewed_by": "teacher",
    }
    return InMemoryCurriculumCatalog(
        [
            CurriculumNode(
                node_id="root", parent_id=None, volume="必修第一册", node_type="volume",
                code="R1", name="必修第一册", **common,
            ),
            CurriculumNode(
                node_id="c3", parent_id="root", volume="必修第一册", node_type="chapter",
                code="3", name="第三章 函数的概念与性质", **common,
            ),
            CurriculumNode(
                node_id="s32", parent_id="c3", volume="必修第一册", node_type="section",
                code="3.2", name="函数的基本性质", description="单调性、最值与奇偶性",
                prerequisite_node_ids=[], primary_competencies=["逻辑推理", "直观想象"],
                typical_question_types=["选择题"], common_errors=["忽略定义域和区间"],
                gaokao_priority="high", status="ready_for_teacher_review", reviewed_by="teacher",
            ),
            CurriculumNode(
                node_id="kp1", parent_id="s32", volume="必修第一册", node_type="knowledge_point",
                code="3.2.1", name="函数单调性", description="增减函数的定义和图象判断",
                prerequisite_node_ids=[], primary_competencies=["逻辑推理"],
                typical_question_types=["单调性判断"], common_errors=["任取两点步骤不完整"],
                gaokao_priority="high", status="ready_for_teacher_review", reviewed_by="teacher",
            ),
        ]
    )


def test_studio_creates_retrieval_grounded_editable_plan(tmp_path: Path) -> None:
    studio = LessonPlanStudio(
        database_path=tmp_path / "lesson-plans.sqlite3",
        curriculum_catalog=_catalog(),
        question_bank=FakeQuestionBank(),  # type: ignore[arg-type]
        provider=TemplateLessonPlanProvider(),
    )

    plan = studio.create(
        LessonPlanGenerationRequest(curriculum_node_id="s32", duration_minutes=45)
    )

    assert plan.curriculum.chapter == "第三章 函数的概念与性质"
    assert plan.curriculum.knowledge_points == ["函数单调性"]
    assert sum(item.minutes for item in plan.content.teaching_flow) == 45
    assert plan.content.recommended_questions[0].question_id == "q_verified_function_01"
    assert plan.generation.mode == "local_preview"
    assert studio.list().total == 1

    revised_content = plan.content.model_copy(update={"title": "教师修订后的函数单调性教案"})
    revised = studio.update(
        plan.lesson_plan_id,
        LessonPlanUpdateCommand(content=revised_content),
    )

    assert revised.version == 2
    assert studio.get(plan.lesson_plan_id).content.title == "教师修订后的函数单调性教案"


def test_openai_adapter_requests_strict_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    generated = {
        "title": "函数单调性",
        "objectives": ["能用定义判断单调性"],
        "key_points": ["单调性定义"],
        "difficulties": ["任取两点并正确作差"],
        "teaching_flow": [
            {
                "phase": "概念建构",
                "minutes": 25,
                "teacher_activity": "组织定义辨析",
                "student_activity": "比较并表达",
                "assessment": "检查定义条件",
            },
            {
                "phase": "练习总结",
                "minutes": 20,
                "teacher_activity": "组织变式",
                "student_activity": "独立完成",
                "assessment": "出口题",
            },
        ],
        "homework": ["完成两道定义法证明题"],
        "board_plan": ["定义—步骤—易错点"],
        "teacher_notes": ["课后记录学情"],
    }
    captured: dict = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": json.dumps(generated, ensure_ascii=False)}
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
            ).encode("utf-8")

    def fake_urlopen(request, timeout: int):
        captured.update(json.loads(request.data.decode("utf-8")))
        assert timeout == 30
        return FakeResponse()

    monkeypatch.setattr("app.modules.lesson_plans.providers.urlopen", fake_urlopen)
    provider = OpenAIResponsesLessonPlanProvider(
        api_key="test-key", model="gpt-5.6-terra", timeout_seconds=30
    )
    result = provider.generate(
        LessonPlanGenerationContext(
            request=LessonPlanGenerationRequest(
                curriculum_node_id="kp1", duration_minutes=45
            ),
            curriculum=LessonCurriculumContext(
                node_id="kp1",
                volume="必修第一册",
                chapter="函数的概念与性质",
                section="函数的基本性质",
                topic="函数单调性",
                description="增减函数的定义和图象判断",
                competencies=["逻辑推理"],
                common_errors=["任取两点步骤不完整"],
                knowledge_points=["函数单调性"],
            ),
            questions=[],
        )
    )

    assert result.title == "函数单调性"
    assert captured["model"] == "gpt-5.6-terra"
    assert captured["store"] is False
    assert captured["text"]["format"]["type"] == "json_schema"
    assert captured["text"]["format"]["strict"] is True
    assert len(captured["safety_identifier"]) == 32
