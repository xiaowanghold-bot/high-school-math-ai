from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.question_bank import QuestionBank, QuestionRevisionCommand
from app.modules.question_similarity import (
    DuplicateReviewCommand,
    QuestionSimilarityError,
    QuestionSimilarityRegistry,
)
from app.routes import question_similarity as similarity_routes


def create_question(
    bank: QuestionBank,
    *,
    candidate_id: str,
    stem: str,
    answer: str = "2",
    steps: list[str] | None = None,
    source: str = "来源甲",
    position: int = 1,
):
    return bank.create_private_resource_question(
        {
            "candidate_id": candidate_id,
            "source_version": 1,
            "position": position,
            "question_type": "open_response",
            "stem_plain": stem,
            "stem_latex": None,
            "options": [],
            "answer_value": answer,
            "solution_method": "代数法",
            "solution_steps": steps or ["移项求解"],
            "final_answer": answer,
            "difficulty": 2,
            "status": "draft",
        },
        resource={
            "library_item_id": f"lib_{candidate_id}",
            "title": source,
            "original_filename": f"{source}.pdf",
            "rights_basis": "original",
            "rights_statement": "测试资料",
            "adaptation_allowed": True,
        },
    )


def make_registry(tmp_path: Path) -> tuple[QuestionBank, QuestionSimilarityRegistry]:
    bank = QuestionBank(tmp_path / "questions.sqlite3", tmp_path / "media")
    return bank, QuestionSimilarityRegistry(
        tmp_path / "similarity.sqlite3",
        question_bank=bank,
    )


def test_scan_classifies_same_problem_and_numeric_variant(tmp_path: Path) -> None:
    bank, registry = make_registry(tmp_path)
    create_question(
        bank,
        candidate_id="source_a",
        stem="1.（2024·湖北联考）已知函数 f(x)=x+1，求 f(1)。",
        source="湖北联考",
    )
    create_question(
        bank,
        candidate_id="source_b",
        stem="（2024·湖北联考）已知函数 f(x)=x+1，求 f(1)。",
        source="函数专题",
    )
    create_question(
        bank,
        candidate_id="variant",
        stem="已知函数 f(x)=x+3，求 f(2)。",
        answer="5",
        source="教师变式",
    )

    result = registry.scan()

    relations = {item.suggested_relation for item in result.workspace.items}
    assert result.scanned_questions == 3
    assert "same_problem_different_source" in relations
    assert "variant" in relations
    assert result.new_candidates >= 2


def test_scan_classifies_same_problem_different_solution_and_is_idempotent(tmp_path: Path) -> None:
    bank, registry = make_registry(tmp_path)
    create_question(bank, candidate_id="method_a", stem="解方程 x+1=3。", steps=["移项得 x=2"])
    create_question(bank, candidate_id="method_b", stem="解方程 x+1=3。", steps=["两边同时减 1"])

    first = registry.scan()
    second = registry.scan()

    assert first.workspace.items[0].suggested_relation == "same_problem_different_solution"
    assert first.new_candidates == 1
    assert second.new_candidates == 0
    assert second.workspace.stats.total == 1


def test_teacher_review_persists_but_never_changes_question_content(tmp_path: Path) -> None:
    bank, registry = make_registry(tmp_path)
    left = create_question(bank, candidate_id="left", stem="解方程 x+1=3。")
    right = create_question(bank, candidate_id="right", stem="解方程 x+1=3。", source="来源乙")
    candidate = registry.scan().workspace.items[0]

    result = registry.review(
        candidate.candidate_id,
        DuplicateReviewCommand(
            relation="same_problem_different_source",
            reviewer_id="teacher_1",
            note="两份资料收录同一题",
        ),
    )

    assert result.candidate.status == "confirmed"
    assert result.candidate.teacher_relation == "same_problem_different_source"
    assert bank.get_question(left.question_id).stem_plain == "解方程 x+1=3。"
    assert bank.get_question(right.question_id).stem_plain == "解方程 x+1=3。"
    assert bank.stats().total == 2


def test_changed_question_stales_old_decision(tmp_path: Path) -> None:
    bank, registry = make_registry(tmp_path)
    left = create_question(bank, candidate_id="stale_left", stem="解方程 x+1=3。")
    create_question(bank, candidate_id="stale_right", stem="解方程 x+1=3。", source="来源乙")
    candidate = registry.scan().workspace.items[0]
    registry.review(candidate.candidate_id, DuplicateReviewCommand(relation="exact_duplicate"))
    bank.revise(
        left.question_id,
        QuestionRevisionCommand(
            stem_plain="求函数 f(x)=x+1 的零点。",
            options=[],
            answer_value="-1",
            solution_method="代入",
            solution_steps=["令 f(x)=0"],
            final_answer="-1",
        ),
    )

    rescanned = registry.scan()

    assert rescanned.workspace.stats.stale == 1
    with pytest.raises(QuestionSimilarityError, match="重新扫描"):
        registry.review(candidate.candidate_id, DuplicateReviewCommand(relation="not_duplicate"))


def test_http_scan_workspace_and_review(tmp_path: Path) -> None:
    bank, registry = make_registry(tmp_path)
    create_question(bank, candidate_id="api_left", stem="已知 a=1，求 a+1。")
    create_question(bank, candidate_id="api_right", stem="已知 a=1，求 a+1。", source="来源乙")
    app.dependency_overrides[similarity_routes.get_question_similarity_registry] = lambda: registry
    try:
        client = TestClient(app)
        scan = client.post("/api/v1/question-similarity/scan")
        assert scan.status_code == 200
        candidate_id = scan.json()["workspace"]["items"][0]["candidate_id"]

        review = client.patch(
            f"/api/v1/question-similarity/{candidate_id}",
            json={"relation": "not_duplicate", "note": "人工确认不构成重复"},
        )
        assert review.status_code == 200
        assert review.json()["candidate"]["status"] == "rejected"
        workspace = client.get("/api/v1/question-similarity?status=rejected")
        assert workspace.status_code == 200
        assert workspace.json()["stats"]["rejected"] == 1
    finally:
        app.dependency_overrides.clear()


def test_scan_uses_recorded_parent_variant_relationship(tmp_path: Path) -> None:
    bank, registry = make_registry(tmp_path)
    source = create_question(bank, candidate_id="parent", stem="已知函数 f(x)=x+1，求 f(1)。")
    derived = create_question(bank, candidate_id="child", stem="阅读原题并诊断一名学生的错误推理。")
    with bank._connect() as connection:  # test fixture records the same provenance used by generated variants
        row = connection.execute("SELECT raw_json FROM questions WHERE question_id = ?", (derived.question_id,)).fetchone()
        import json
        raw = json.loads(row["raw_json"])
        raw["provenance"]["derived_from_question_ids"] = [source.question_id]
        connection.execute("UPDATE questions SET raw_json = ? WHERE question_id = ?", (json.dumps(raw, ensure_ascii=False), derived.question_id))

    result = registry.scan()

    assert result.workspace.items[0].suggested_relation == "variant"
    assert result.workspace.items[0].confidence == 0.99
    assert "母题与派生题" in result.workspace.items[0].signals[0]
