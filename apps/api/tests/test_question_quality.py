from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.curriculum import CurriculumNode, InMemoryCurriculumCatalog
from app.modules.question_bank import QuestionBank, QuestionRevisionCommand
from app.modules.question_quality import (
    BatchCurriculumMappingCommand,
    CurriculumMappingCommand,
    ManualVerificationCommand,
    QuestionQualityError,
    QuestionQualityWorkflow,
)


def curriculum_node(**updates) -> CurriculumNode:
    values = {
        "node_id": "root",
        "parent_id": None,
        "volume": "必修第一册",
        "node_type": "volume",
        "code": "R1",
        "name": "必修第一册",
        "description": "",
        "prerequisite_node_ids": [],
        "primary_competencies": [],
        "typical_question_types": [],
        "common_errors": [],
        "gaokao_priority": "high",
        "status": "ready_for_teacher_review",
        "reviewed_by": "teacher",
    }
    values.update(updates)
    return CurriculumNode(**values)


def make_workflow(tmp_path: Path) -> tuple[QuestionQualityWorkflow, QuestionBank, str]:
    catalog = InMemoryCurriculumCatalog(
        [
            curriculum_node(),
            curriculum_node(node_id="chapter", parent_id="root", node_type="chapter", code="3", name="函数的概念与性质"),
            curriculum_node(node_id="section", parent_id="chapter", node_type="section", code="3.2", name="函数的基本性质"),
            curriculum_node(
                node_id="kp_monotonic",
                parent_id="section",
                node_type="knowledge_point",
                code="3.2.1",
                name="函数的单调性",
                description="用定义或图象判断函数在区间上的单调性",
                typical_question_types=["单调区间", "单调性判断"],
            ),
            curriculum_node(
                node_id="kp_parity",
                parent_id="section",
                node_type="knowledge_point",
                code="3.2.2",
                name="函数的奇偶性",
                description="奇函数与偶函数的定义和图象对称性",
            ),
        ]
    )
    bank = QuestionBank(tmp_path / "questions.sqlite3", tmp_path / "media")
    question = bank.create_private_resource_question(
        {
            "candidate_id": "cand_quality_test",
            "source_version": 1,
            "position": 1,
            "question_type": "open_response",
            "stem_plain": "已知函数 f(x)=2x+1，判断它在实数集上的单调性。",
            "stem_latex": None,
            "options": [],
            "answer_value": "增函数",
            "solution_method": "定义法",
            "solution_steps": ["任取 x₁<x₂，则 f(x₁)<f(x₂)。"],
            "final_answer": "增函数",
            "difficulty": 2,
            "status": "draft",
        },
        resource={
            "library_item_id": "lib_quality",
            "title": "函数资料",
            "original_filename": "functions.docx",
            "rights_basis": "original",
            "rights_statement": "教师原创资料",
            "adaptation_allowed": True,
        },
    )
    return QuestionQualityWorkflow(question_bank=bank, curriculum_catalog=catalog), bank, question.question_id


def test_quality_workflow_recommends_and_applies_curriculum(tmp_path: Path) -> None:
    workflow, bank, question_id = make_workflow(tmp_path)

    workspace = workflow.inspect(question_id)

    assert workspace.curriculum_suggestions[0].node_id == "kp_monotonic"
    assert workspace.curriculum_suggestions[0].confidence >= 0.6
    assert workspace.current_curriculum.knowledge_point_names == []
    result = workflow.apply_curriculum(
        question_id,
        CurriculumMappingCommand(node_id="kp_monotonic", teacher_id="teacher_1"),
    )
    question = bank.get_question(question_id)
    assert result.status == "curriculum_applied"
    assert question.volume == "必修第一册"
    assert question.chapter == "函数的概念与性质"
    assert question.section == "函数的基本性质"
    assert question.knowledge_point_ids == ["kp_monotonic"]
    assert question.visibility == "private"
    assert question.verification_status == "needs_math_review"
    assert result.workspace.current_curriculum.knowledge_point_names == ["函数的单调性"]


def test_batch_curriculum_workspace_and_teacher_confirmed_apply(tmp_path: Path) -> None:
    workflow, bank, question_id = make_workflow(tmp_path)

    workspace = workflow.inspect_curriculum_batch([question_id, question_id])

    assert workspace.total == 1
    assert workspace.high_confidence_count == 1
    assert workspace.items[0].suggestions[0].node_id == "kp_monotonic"
    result = workflow.apply_curriculum_batch(
        BatchCurriculumMappingCommand(
            mappings=[{"question_id": question_id, "node_id": "kp_monotonic"}],
            teacher_id="teacher_1",
        )
    )

    assert result.applied_count == 1
    assert bank.get_question(question_id).knowledge_point_ids == ["kp_monotonic"]


def test_generic_real_parameter_symbol_does_not_trigger_set_mapping(tmp_path: Path) -> None:
    workflow, bank, question_id = make_workflow(tmp_path)
    question = bank.get_question(question_id)
    bank.revise(
        question_id,
        QuestionRevisionCommand(
            stem_plain="已知 a∈R，函数 f(x)=e^x-ax^3，求函数的极值点。",
            stem_latex=None,
            options=[],
            answer_value=question.answer_value,
            solution_method="教师修订",
            solution_steps=[],
            final_answer=question.answer_value,
        ),
    )

    suggestions = workflow.inspect(question_id).curriculum_suggestions

    assert all(
        item.name != "元素与集合的关系" or item.confidence < workflow.HIGH_CONFIDENCE_THRESHOLD
        for item in suggestions
    )


def test_close_competing_suggestions_require_teacher_review(tmp_path: Path) -> None:
    workflow, _, question_id = make_workflow(tmp_path)
    original_recommend = workflow._recommend
    workflow._recommend = lambda stem, raw: [
        *original_recommend(stem, raw)[:1],
        original_recommend(stem, raw)[0].model_copy(
            update={"node_id": "kp_parity", "name": "函数的奇偶性", "confidence": 0.9}
        ),
    ]

    workspace = workflow.inspect_curriculum_batch([question_id])

    assert workspace.high_confidence_count == 0
    assert workspace.review_required_count == 1


def test_manual_verification_requires_declaration_and_evidence(tmp_path: Path) -> None:
    workflow, _, question_id = make_workflow(tmp_path)

    with pytest.raises(QuestionQualityError, match="独立核验"):
        workflow.record_verification(
            question_id,
            ManualVerificationCommand(
                conclusion="passed",
                computed_answer="增函数",
                evidence_steps=["独立使用定义法验证"],
                independently_checked=False,
            ),
        )


def test_matching_manual_answer_passes_but_keeps_review_gate(tmp_path: Path) -> None:
    workflow, bank, question_id = make_workflow(tmp_path)

    result = workflow.record_verification(
        question_id,
        ManualVerificationCommand(
            conclusion="passed",
            computed_answer="增函数",
            evidence_steps=["任取 x₁<x₂。", "计算 f(x₂)-f(x₁)=2(x₂-x₁)>0。"],
            independently_checked=True,
            verifier_id="teacher_1",
        ),
    )
    question = bank.get_question(question_id)

    assert result.status == "passed"
    assert question.verification_status == "passed"
    assert question.raw["verification"]["answers_match"] is True
    assert "teacher_review_required" in question.publication_blockers
    assert "approved_original_solution_required" in question.publication_blockers


def test_mismatching_answer_can_never_be_marked_passed(tmp_path: Path) -> None:
    workflow, bank, question_id = make_workflow(tmp_path)

    result = workflow.record_verification(
        question_id,
        ManualVerificationCommand(
            conclusion="passed",
            computed_answer="减函数",
            evidence_steps=["独立计算得到减函数。"],
            independently_checked=True,
        ),
    )
    question = bank.get_question(question_id)

    assert result.status == "source_inconsistency_detected"
    assert question.verification_status == "source_inconsistency_detected"
    assert question.raw["verification"]["answers_match"] is False
    assert "系统拒绝标记通过" in question.raw["verification"]["details"][-1]


def test_question_quality_http_endpoints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workflow, bank, question_id = make_workflow(tmp_path)
    monkeypatch.setattr("app.routes.questions.get_question_quality_workflow", lambda: workflow)
    monkeypatch.setattr("app.routes.questions.get_question_bank", lambda: bank)
    client = TestClient(app)

    workspace = client.get(f"/api/v1/questions/{question_id}/quality")
    batch_workspace = client.post(
        "/api/v1/questions/quality/curriculum/batch/inspect",
        json={"question_ids": [question_id]},
    )
    batch_applied = client.post(
        "/api/v1/questions/quality/curriculum/batch/apply",
        json={
            "mappings": [{"question_id": question_id, "node_id": "kp_monotonic"}],
            "teacher_id": "teacher_1",
        },
    )
    applied = client.post(
        f"/api/v1/questions/{question_id}/quality/curriculum",
        json={"node_id": "kp_monotonic", "teacher_id": "teacher_1"},
    )
    verified = client.post(
        f"/api/v1/questions/{question_id}/quality/verification",
        json={
            "conclusion": "passed",
            "computed_answer": "增函数",
            "evidence_steps": ["斜率为 2>0，所以在实数集上单调递增。"],
            "independently_checked": True,
            "verifier_id": "teacher_1",
        },
    )

    assert workspace.status_code == 200
    assert batch_workspace.status_code == 200
    assert batch_workspace.json()["high_confidence_count"] == 1
    assert batch_applied.status_code == 200
    assert batch_applied.json()["applied_count"] == 1
    assert workspace.json()["curriculum_suggestions"][0]["node_id"] == "kp_monotonic"
    assert applied.status_code == 200
    assert verified.status_code == 200
    assert verified.json()["status"] == "passed"
