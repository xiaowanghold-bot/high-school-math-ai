import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import PROJECT_ROOT
from app.main import app
from app.modules.math_verifier import MathVerifier
from app.modules.question_bank import QuestionBank, QuestionRevisionCommand
from app.modules.question_variants import (
    LocalDiagnosticVariantProvider,
    QuestionVariantGenerationRequest,
    QuestionVariantProviderError,
    QuestionVariantService,
    QuestionVariantServiceError,
    TeacherVariantDraftCommand,
)
from app.routes import questions as question_routes


PILOT_BATCH = PROJECT_ROOT / "data" / "pilot" / "batch-2026-08-001-30q.json"
SET_CURATION = PROJECT_ROOT / "data" / "curated" / "set-10q-corrections-v1.json"


def make_service(tmp_path: Path) -> tuple[QuestionBank, QuestionVariantService]:
    bank = QuestionBank(tmp_path / "question-bank.sqlite3", tmp_path / "media")
    bank.import_batch(PILOT_BATCH)
    bank.apply_curation_package(SET_CURATION, MathVerifier())
    return bank, QuestionVariantService(
        question_bank=bank, provider=LocalDiagnosticVariantProvider()
    )


def test_verified_single_choice_creates_auditable_private_diagnostic_variant(
    tmp_path: Path,
) -> None:
    bank, service = make_service(tmp_path)

    result = service.generate(
        "q_pilot_set_1_1",
        QuestionVariantGenerationRequest(
            variant_kind="diagnostic",
            target_difficulty=3,
            instruction="要求学生指出补集范围",
        ),
    )

    question = result.question
    assert result.mode == "local_rule"
    assert question.question_id.startswith("q_variant_")
    assert question.visibility == "private"
    assert question.review_status == "pending"
    assert question.verification_status == "passed"
    assert question.difficulty == 3
    assert "某同学选择了" in question.stem_plain
    assert question.raw["provenance"]["derived_from_question_ids"] == ["q_pilot_set_1_1"]
    assert question.raw["generation_request"]["instruction"] == "要求学生指出补集范围"
    assert "派生变式" in question.source_document
    assert bank.stats().total == 31

    with sqlite3.connect(bank.database_path) as connection:
        run = connection.execute(
            "SELECT source_question_id, output_question_id, provider FROM question_generation_runs"
        ).fetchone()
    assert run == ("q_pilot_set_1_1", question.question_id, "local_rule")


def test_generated_variant_enters_existing_teacher_editing_workflow(tmp_path: Path) -> None:
    bank, service = make_service(tmp_path)
    generated = service.generate(
        "q_pilot_set_1_1", QuestionVariantGenerationRequest()
    ).question

    revised = bank.revise(
        generated.question_id,
        QuestionRevisionCommand(
            stem_plain=f"{generated.stem_plain}\n请再说明一个常见错误。",
            options=[],
            answer_value=generated.answer_value,
            solution_method="教师修订的错因诊断",
            solution_steps=["先完成原题", "再定位错误推理"],
            final_answer=generated.answer_value,
        ),
    )

    assert revised.verification_reset is True
    assert revised.question.verification_status == "needs_math_review"
    assert revised.question.revision_count == 1


def test_teacher_custom_variant_is_private_and_does_not_change_source(tmp_path: Path) -> None:
    bank, service = make_service(tmp_path)
    source_before = bank.get_question("q_pilot_set_1_1")

    saved = service.save_teacher_draft(
        source_before.question_id,
        TeacherVariantDraftCommand(
            question_type="single_choice",
            stem_plain="教师自拟：设全集为实数集，重新判断下列集合关系。",
            answer_value="B",
            final_answer="B",
            solution_steps=["由补集定义判断"],
        ),
    )

    assert saved.visibility == "private"
    assert saved.verification_status == "needs_math_review"
    assert saved.raw["generation_request"]["teacher_id"] == "owner_teacher"
    assert bank.get_question(source_before.question_id).stem_plain == source_before.stem_plain


def test_unverified_source_and_nonlocal_modes_are_blocked(tmp_path: Path) -> None:
    _, service = make_service(tmp_path)

    with pytest.raises(QuestionVariantServiceError, match="尚未通过"):
        service.generate("q_pilot_set_3_1", QuestionVariantGenerationRequest())

    with pytest.raises(QuestionVariantProviderError, match="需配置 OpenAI API Key"):
        service.generate(
            "q_pilot_set_1_1",
            QuestionVariantGenerationRequest(variant_kind="numeric"),
        )


def test_question_variant_http_endpoint_uses_private_draft_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, service = make_service(tmp_path)
    monkeypatch.setattr(question_routes, "get_question_variant_service", lambda: service)
    client = TestClient(app)

    response = client.post(
        "/api/v1/questions/q_pilot_set_1_1/variants",
        json={"variant_kind": "diagnostic", "target_difficulty": 4},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["provider"] == "local_rule"
    assert payload["question"]["difficulty"] == 4
    assert payload["question"]["visibility"] == "private"
    assert payload["question"]["review_status"] == "pending"
