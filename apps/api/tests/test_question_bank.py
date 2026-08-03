import json
import sqlite3
from pathlib import Path

import pytest

from app.core.config import PROJECT_ROOT
from app.modules.math_verifier import MathVerifier
from app.modules.question_bank import QuestionBank, QuestionBankError, ReviewCommand


PILOT_BATCH = PROJECT_ROOT / "data" / "pilot" / "batch-2026-08-001-30q.json"
SET_CURATION = PROJECT_ROOT / "data" / "curated" / "set-10q-corrections-v1.json"
PROBABILITY_CURATION = PROJECT_ROOT / "data" / "curated" / "probability-4q-corrections-v1.json"


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
