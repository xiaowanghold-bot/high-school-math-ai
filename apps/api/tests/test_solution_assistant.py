from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.modules.question_bank import QuestionBank
from app.modules.solution_assistant import (
    GeneratedSolution,
    SolutionAssistant,
    SolutionExplanation,
    SolutionRequest,
)
from app.routes.questions import get_question_bank


client = TestClient(app)


class FakeSolutionProvider:
    name = "fake_model"
    model = "fake-solver-v1"

    def solve(self, request: SolutionRequest) -> GeneratedSolution:
        return GeneratedSolution(
            explanation=SolutionExplanation(
                method="代数法",
                steps=["移项并合并同类项。", "解得 $x=2$。"],
                final_answer="$x=2$",
            ),
            knowledge_points=["一元一次方程"],
            common_mistakes=["移项时忘记变号"],
            teaching_notes=["要求学生口述等式性质"],
        )


def test_solve_exact_verified_bank_question() -> None:
    bank = get_question_bank()
    source = bank.search(verification_status="passed", page_size=1).items[0]

    response = client.post(
        "/api/v1/solutions/solve",
        json={"question_text": source.stem_plain},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["matched_question_id"] == source.question_id
    assert result["confidence_status"] == "program_verified"
    assert result["mode"] == "verified_bank"
    assert result["explanation"]["steps"]
    assert result["explanation"]["final_answer"]
    assert result["verification_evidence"]
    assert all(not item.startswith("kp_") for item in result["knowledge_points"])


def test_unmatched_question_without_provider_explains_configuration() -> None:
    response = client.post(
        "/api/v1/solutions/solve",
        json={"question_text": "求一个当前测试题库中绝对不存在的复合虚构数学问题 987654321。"},
    )

    assert response.status_code == 422
    assert "OpenAI API Key" in response.json()["detail"]


def test_short_fragment_cannot_inherit_verified_answer() -> None:
    bank = get_question_bank()
    source = bank.search(verification_status="passed", page_size=1).items[0]

    response = client.post(
        "/api/v1/solutions/solve",
        json={"question_text": source.stem_plain[:12]},
    )

    assert response.status_code == 422


def test_provider_solves_question_outside_bank(tmp_path: Path) -> None:
    assistant = SolutionAssistant(
        question_bank=QuestionBank(tmp_path / "empty.sqlite3"),
        provider=FakeSolutionProvider(),
    )

    result = assistant.solve(SolutionRequest(question_text="解方程 $2x-4=0$。"))

    assert result.provider == "fake_model"
    assert result.mode == "live_ai"
    assert result.confidence_status == "teacher_review_required"
    assert result.explanation.final_answer == "$x=2$"
    assert result.alternative_available


def test_solution_request_rejects_too_short_question() -> None:
    response = client.post(
        "/api/v1/solutions/solve",
        json={"question_text": "求解"},
    )

    assert response.status_code == 422
