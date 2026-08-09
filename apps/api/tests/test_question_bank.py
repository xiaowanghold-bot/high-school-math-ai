import json
import sqlite3
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import PROJECT_ROOT
from app.modules.math_verifier import MathVerifier
from app.modules.question_bank import (
    QuestionBank,
    QuestionBankError,
    QuestionImageMetadataCommand,
    QuestionRevisionCommand,
    ReviewCommand,
)


PILOT_BATCH = PROJECT_ROOT / "data" / "pilot" / "batch-2026-08-001-30q.json"
SET_CURATION = PROJECT_ROOT / "data" / "curated" / "set-10q-corrections-v1.json"
PROBABILITY_CURATION = PROJECT_ROOT / "data" / "curated" / "probability-4q-corrections-v1.json"
PROBABILITY_CURATION_2 = PROJECT_ROOT / "data" / "curated" / "probability-6q-corrections-v1.json"
FUNCTION_PILOT = PROJECT_ROOT / "data" / "pilot" / "function-properties-5q-v1.json"
FUNCTION_CURATION = PROJECT_ROOT / "data" / "curated" / "function-properties-5q-corrections-v1.json"


def make_bank(tmp_path: Path) -> QuestionBank:
    return QuestionBank(tmp_path / "question-bank.sqlite3")


def test_batch_import_is_validated_and_idempotent(tmp_path: Path) -> None:
    bank = make_bank(tmp_path)

    first = bank.import_batch(PILOT_BATCH)
    second = bank.import_batch(PILOT_BATCH)

    assert first.declared_count == 30
    assert first.created_count == 30
    assert second.created_count == 0
    assert second.skipped_count == 30
    assert bank.stats().total == 30
    assert bank.import_batches()[0].batch_id == "batch-2026-08-001-pilot-30q"


def test_invalid_batch_never_enters_question_bank(tmp_path: Path) -> None:
    bank = make_bank(tmp_path)
    invalid = tmp_path / "invalid.json"
    invalid.write_text(
        json.dumps({"batch_id": "bad", "question_count": 1, "questions": []}),
        encoding="utf-8",
    )

    with pytest.raises(QuestionBankError, match="数量不一致"):
        bank.import_batch(invalid)

    assert bank.stats().total == 0


def test_search_combines_keyword_and_structured_filters(tmp_path: Path) -> None:
    bank = make_bank(tmp_path)
    bank.import_batch(PILOT_BATCH)

    page = bank.search(query="集合", difficulty=2, page_size=50)

    assert page.total == 10
    assert all(item.chapter == "第一章 集合与常用逻辑用语" for item in page.items)


def test_curation_package_is_independently_verified_and_idempotent(tmp_path: Path) -> None:
    bank = make_bank(tmp_path)
    bank.import_batch(PILOT_BATCH)

    first = bank.apply_curation_package(SET_CURATION, MathVerifier())
    second = bank.apply_curation_package(SET_CURATION, MathVerifier())

    assert first.applied_count == 10
    assert first.passed_count == 9
    assert first.inconsistency_count == 1
    assert second.applied_count == 0
    assert second.skipped_count == 10
    assert bank.get_question("q_pilot_set_1_1").verification_status == "passed"
    flawed = bank.get_question("q_pilot_set_3_1")
    assert flawed.status == "rejected"
    assert flawed.raw["verification"]["computed_canonical_value"] == "set:0,1,4"


def test_probability_composite_questions_are_independently_verified(tmp_path: Path) -> None:
    bank = make_bank(tmp_path)
    bank.import_batch(PILOT_BATCH)

    first = bank.apply_curation_package(PROBABILITY_CURATION, MathVerifier())
    second = bank.apply_curation_package(PROBABILITY_CURATION, MathVerifier())

    assert first.applied_count == 4
    assert first.passed_count == 4
    assert first.inconsistency_count == 0
    assert second.applied_count == 0
    assert second.skipped_count == 4
    tournament = bank.get_question("q_pilot_probability_01")
    assert tournament.verification_status == "passed"
    assert tournament.raw["verification"]["computed_canonical_value"] == (
        'composite:{"part1":"1/16","part2":"3/4","part3":"7/16"}'
    )
    assert bank.get_question("q_pilot_probability_04").raw["verification"][
        "computed_answer"
    ].endswith("E(X)=40/27")


def test_remaining_probability_questions_include_source_error_isolation(tmp_path: Path) -> None:
    bank = make_bank(tmp_path)
    bank.import_batch(PILOT_BATCH)

    first = bank.apply_curation_package(PROBABILITY_CURATION_2, MathVerifier())
    second = bank.apply_curation_package(PROBABILITY_CURATION_2, MathVerifier())

    assert first.applied_count == 6
    assert first.passed_count == 5
    assert first.inconsistency_count == 1
    assert second.applied_count == 0
    assert second.skipped_count == 6
    assert bank.get_question("q_pilot_probability_08").verification_status == "passed"
    flawed = bank.get_question("q_pilot_probability_10")
    assert flawed.status == "rejected"
    assert flawed.verification_status == "source_inconsistency_detected"
    assert flawed.raw["verification"]["computed_canonical_value"] == (
        'composite:{"conditional_distribution":{"0":"13/59","1":"22/59","2":"24/59"},'
        '"conditional_expectation":"70/59","part1":"5/36",'
        '"probability_game_ends_in_three":"59/144"}'
    )


def test_function_properties_batch_is_imported_verified_and_isolates_open_endpoint_error(
    tmp_path: Path,
) -> None:
    bank = make_bank(tmp_path)
    imported = bank.import_batch(FUNCTION_PILOT)

    first = bank.apply_curation_package(FUNCTION_CURATION, MathVerifier())
    second = bank.apply_curation_package(FUNCTION_CURATION, MathVerifier())

    assert imported.created_count == 5
    assert first.applied_count == 5
    assert first.passed_count == 4
    assert first.inconsistency_count == 1
    assert second.applied_count == 0
    assert second.skipped_count == 5
    flawed = bank.get_question("q_function_properties_01")
    assert flawed.status == "rejected"
    assert flawed.verification_status == "source_inconsistency_detected"
    assert flawed.raw["verification"]["computed_canonical_value"] == (
        "relation:f(4)<f(1)=f(3);f(2):undetermined"
    )
    assert bank.get_question("q_function_properties_05").verification_status == "passed"


def test_teacher_cannot_approve_before_independent_verification(tmp_path: Path) -> None:
    bank = make_bank(tmp_path)
    bank.import_batch(PILOT_BATCH)

    with pytest.raises(QuestionBankError, match="独立数学验证"):
        bank.review("q_pilot_set_1_1", ReviewCommand(decision="approved"))


def test_legacy_unverified_approval_is_repaired_on_open(tmp_path: Path) -> None:
    database_path = tmp_path / "question-bank.sqlite3"
    bank = QuestionBank(database_path)
    bank.import_batch(PILOT_BATCH)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE questions SET review_status = 'approved' WHERE question_id = ?",
            ("q_pilot_probability_02",),
        )

    reopened = QuestionBank(database_path)

    assert reopened.get_question("q_pilot_probability_02").review_status == "pending"


def test_verified_question_can_be_teacher_approved_and_published(tmp_path: Path) -> None:
    bank = make_bank(tmp_path)
    bank.import_batch(PILOT_BATCH)
    bank.apply_curation_package(SET_CURATION, MathVerifier())
    question_id = "q_pilot_set_1_1"

    review = bank.review(
        question_id,
        ReviewCommand(decision="approved", note="题干、答案与原创解析均审核通过"),
    )
    publish = bank.publish(question_id)
    detail = bank.get_question(question_id)

    assert review.review_status == "approved"
    assert publish.allowed is True
    assert publish.status == "published"
    assert detail.reviews[0]["note"] == "题干、答案与原创解析均审核通过"


def _verified_question(bank: QuestionBank):
    bank.import_batch(PILOT_BATCH)
    bank.apply_curation_package(SET_CURATION, MathVerifier())
    return bank.get_question("q_pilot_set_1_1")


def _revision_command(detail, *, stem_plain: str | None = None) -> QuestionRevisionCommand:
    solution = detail.raw["solutions"][0]
    return QuestionRevisionCommand(
        stem_plain=stem_plain or detail.stem_plain,
        stem_latex=detail.raw["stem"].get("latex"),
        options=[
            {"key": item["key"], "text": item.get("latex") or item.get("plain_text") or ""}
            for item in detail.raw.get("options", [])
        ],
        answer_value=detail.answer_value,
        solution_method="教师补充的集合运算方法",
        solution_steps=["先化简各集合", "再计算交集"],
        final_answer=detail.answer_value,
    )


def test_teacher_revision_keeps_history_and_resets_only_math_critical_edits(tmp_path: Path) -> None:
    bank = make_bank(tmp_path)
    detail = _verified_question(bank)

    solution_only = bank.revise(detail.question_id, _revision_command(detail))
    changed_stem = bank.revise(
        detail.question_id,
        _revision_command(solution_only.question, stem_plain=f"{detail.stem_plain}（教师修订）"),
    )

    assert solution_only.verification_reset is False
    assert solution_only.question.verification_status == "passed"
    assert changed_stem.verification_reset is True
    assert changed_stem.question.verification_status == "needs_math_review"
    assert changed_stem.question.review_status == "pending"
    assert changed_stem.question.revision_count == 3  # curation + two teacher revisions


def test_question_images_are_validated_ordered_and_audited(tmp_path: Path) -> None:
    bank = make_bank(tmp_path)
    detail = _verified_question(bank)
    payload = BytesIO()
    Image.new("RGB", (640, 480), "white").save(payload, format="PNG")

    stem_image = bank.add_image(
        detail.question_id,
        payload.getvalue(),
        "立体几何示意图.png",
        "stem",
        "正方体 ABCD-A1B1C1D1",
        "图 1",
    )
    solution_image = bank.add_image(
        detail.question_id,
        payload.getvalue(),
        "辅助线.png",
        "solution",
        "连接 AC1 的辅助线",
        "解析辅助图",
    )
    updated = bank.update_image(
        detail.question_id,
        solution_image.image_id,
        QuestionImageMetadataCommand(caption="解析图：连接 AC1"),
    )
    ordered = bank.reorder_images(
        detail.question_id, [solution_image.image_id, stem_image.image_id]
    )
    path, mime_type = bank.image_path(detail.question_id, stem_image.image_id)

    assert stem_image.width == 640
    assert stem_image.height == 480
    assert updated.caption == "解析图：连接 AC1"
    assert [item.image_id for item in ordered] == [stem_image.image_id, solution_image.image_id]
    assert path.is_file()
    assert mime_type == "image/png"
    assert bank.get_question(detail.question_id).verification_status == "needs_math_review"

    bank.delete_image(detail.question_id, stem_image.image_id)
    assert len(bank.get_question(detail.question_id).images) == 1


def test_question_image_rejects_non_image_payload(tmp_path: Path) -> None:
    bank = make_bank(tmp_path)
    detail = _verified_question(bank)

    with pytest.raises(QuestionBankError, match="有效的"):
        bank.add_image(detail.question_id, b"not-an-image", "fake.png", "stem", "", "")
