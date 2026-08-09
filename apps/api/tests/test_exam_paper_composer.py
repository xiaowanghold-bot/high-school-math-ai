from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.modules.exam_papers import (
    ExamPaperComposer,
    ExamPaperComposeCommand,
    ExamPaperComposeError,
    ExamPaperTypeQuota,
)
from app.modules.question_bank.schemas import QuestionSearchPage, QuestionSummary
from app.routes import exam_papers as exam_paper_routes


def question(
    question_id: str,
    question_type: str,
    difficulty: int,
    chapter: str,
    *,
    review_status: str = "approved",
) -> QuestionSummary:
    return QuestionSummary(
        question_id=question_id,
        status="verified",
        review_status=review_status,
        visibility="private",
        question_type=question_type,
        stem_plain=f"{chapter}中的第 {question_id} 道题",
        answer_value="A",
        volume="必修第一册",
        chapter=chapter,
        section="测试小节",
        knowledge_point_ids=[f"kp_{question_id}"],
        difficulty=difficulty,
        verification_status="passed",
        source_document="教师自有题库.pdf",
        source_page_start=1,
        source_page_end=1,
        license_status="question_content_user_declared_usable",
        publication_blockers=[],
    )


class ComposerQuestionBank:
    def __init__(self) -> None:
        self.questions = [
            question("s1", "single_choice", 1, "集合"),
            question("s2", "single_choice", 2, "集合"),
            question("s3", "single_choice", 3, "函数"),
            question("s4", "single_choice", 4, "函数"),
            question("s5", "single_choice", 3, "函数", review_status="pending"),
            question("s6", "single_choice", 3, "函数", review_status="rejected"),
            question("c1", "composite", 2, "概率"),
            question("c2", "composite", 3, "概率"),
            question("c3", "composite", 4, "概率"),
        ]

    def search(self, **kwargs) -> QuestionSearchPage:
        page = kwargs.get("page", 1)
        page_size = kwargs.get("page_size", 100)
        start = (page - 1) * page_size
        return QuestionSearchPage(
            items=self.questions[start : start + page_size],
            total=len(self.questions),
            page=page,
            page_size=page_size,
        )


def command(**updates) -> ExamPaperComposeCommand:
    values = {
        "target_score": 50,
        "difficulty_profile": "balanced",
        "type_quotas": [
            ExamPaperTypeQuota(question_type="single_choice", count=3),
            ExamPaperTypeQuota(question_type="composite", count=2),
        ],
        "seed": "teacher-demo",
    }
    values.update(updates)
    return ExamPaperComposeCommand(**values)


def test_composer_returns_deterministic_exact_score_proposal() -> None:
    composer = ExamPaperComposer(ComposerQuestionBank())

    first = composer.compose(command())
    second = composer.compose(command())

    assert first.actual_score == first.target_score == 50
    assert len(first.items) == 5
    assert len({item.question.question_id for item in first.items}) == 5
    assert [item.question.question_id for item in first.items] == [
        item.question.question_id for item in second.items
    ]
    assert all(item.question.review_status == "approved" for item in first.items)
    assert sum(item.score for item in first.items) == 50
    assert first.chapter_breakdown
    assert first.difficulty_breakdown


def test_composer_can_include_pending_review_and_reports_warning() -> None:
    composer = ExamPaperComposer(ComposerQuestionBank())

    proposal = composer.compose(
        command(
            review_policy="verified",
            type_quotas=[ExamPaperTypeQuota(question_type="single_choice", count=5)],
        )
    )

    assert any(item.question.question_id == "s5" for item in proposal.items)
    assert all(item.question.question_id != "s6" for item in proposal.items)
    assert any("待教师审核" in warning for warning in proposal.warnings)


def test_composer_enforces_chapter_exclusion_and_supply() -> None:
    composer = ExamPaperComposer(ComposerQuestionBank())

    with pytest.raises(ExamPaperComposeError, match="不足"):
        composer.compose(
            command(
                target_score=10,
                chapters=["集合"],
                exclude_question_ids=["s1"],
                type_quotas=[ExamPaperTypeQuota(question_type="single_choice", count=2)],
            )
        )


def test_compose_http_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    composer = ExamPaperComposer(ComposerQuestionBank())
    monkeypatch.setattr(exam_paper_routes, "get_exam_paper_composer", lambda: composer)
    client = TestClient(app)

    response = client.post(
        "/api/v1/exam-papers/compose",
        json={
            "target_score": 40,
            "difficulty_profile": "foundation",
            "type_quotas": [
                {"question_type": "single_choice", "count": 2},
                {"question_type": "composite", "count": 2},
            ],
            "review_policy": "approved_only",
            "seed": "http-test",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["actual_score"] == 40
    assert len(payload["items"]) == 4
