from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query

from app.core.config import get_settings
from app.modules.math_verifier import MathVerifier
from app.modules.question_bank import QuestionBank, QuestionBankError, ReviewCommand
from app.modules.question_bank.schemas import (
    CurationResult,
    ImportBatchView,
    ImportResult,
    PublishDecision,
    QuestionBankStats,
    QuestionDetail,
    QuestionSearchPage,
    ReviewResult,
)


router = APIRouter(tags=["question-bank"])


@lru_cache
def get_question_bank() -> QuestionBank:
    settings = get_settings()
    bank = QuestionBank(settings.question_bank_db)
    if settings.pilot_batch_json.exists():
        bank.import_batch(settings.pilot_batch_json)
    if settings.set_curation_json.exists():
        bank.apply_curation_package(settings.set_curation_json, MathVerifier())
    if settings.probability_curation_json.exists():
        bank.apply_curation_package(settings.probability_curation_json, MathVerifier())
    if settings.probability_curation_2_json.exists():
        bank.apply_curation_package(settings.probability_curation_2_json, MathVerifier())
    if settings.function_pilot_batch_json.exists():
        bank.import_batch(settings.function_pilot_batch_json)
    if settings.function_curation_json.exists():
        bank.apply_curation_package(settings.function_curation_json, MathVerifier())
    return bank


@router.post("/question-bank/import-pilot", response_model=ImportResult)
def import_pilot() -> ImportResult:
    settings = get_settings()
    try:
        return get_question_bank().import_batch(settings.pilot_batch_json)
    except QuestionBankError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/question-bank/import-batches", response_model=list[ImportBatchView])
def list_import_batches() -> list[ImportBatchView]:
    return get_question_bank().import_batches()


@router.post("/question-bank/import-function-pilot", response_model=ImportResult)
def import_function_pilot() -> ImportResult:
    settings = get_settings()
    try:
        return get_question_bank().import_batch(settings.function_pilot_batch_json)
    except QuestionBankError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/question-bank/apply-set-curation", response_model=CurationResult)
def apply_set_curation() -> CurationResult:
    settings = get_settings()
    try:
        return get_question_bank().apply_curation_package(settings.set_curation_json, MathVerifier())
    except QuestionBankError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/question-bank/apply-probability-curation", response_model=CurationResult)
def apply_probability_curation() -> CurationResult:
    settings = get_settings()
    try:
        return get_question_bank().apply_curation_package(
            settings.probability_curation_json, MathVerifier()
        )
    except QuestionBankError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/question-bank/apply-probability-curation-2", response_model=CurationResult)
def apply_probability_curation_2() -> CurationResult:
    settings = get_settings()
    try:
        return get_question_bank().apply_curation_package(
            settings.probability_curation_2_json, MathVerifier()
        )
    except QuestionBankError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/question-bank/apply-function-curation", response_model=CurationResult)
def apply_function_curation() -> CurationResult:
    settings = get_settings()
    try:
        return get_question_bank().apply_curation_package(
            settings.function_curation_json, MathVerifier()
        )
    except QuestionBankError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/question-bank/stats", response_model=QuestionBankStats)
def question_bank_stats() -> QuestionBankStats:
    return get_question_bank().stats()


@router.get("/questions", response_model=QuestionSearchPage)
def search_questions(
    query: str = "",
    chapter: str | None = None,
    difficulty: int | None = Query(default=None, ge=1, le=5),
    verification_status: str | None = None,
    review_status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> QuestionSearchPage:
    return get_question_bank().search(
        query=query,
        chapter=chapter,
        difficulty=difficulty,
        verification_status=verification_status,
        review_status=review_status,
        page=page,
        page_size=page_size,
    )


@router.get("/questions/{question_id}", response_model=QuestionDetail)
def get_question(question_id: str) -> QuestionDetail:
    try:
        return get_question_bank().get_question(question_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="题目不存在") from exc


@router.post("/questions/{question_id}/review", response_model=ReviewResult)
def review_question(question_id: str, command: ReviewCommand) -> ReviewResult:
    try:
        return get_question_bank().review(question_id, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="题目不存在") from exc
    except QuestionBankError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/questions/{question_id}/publish", response_model=PublishDecision)
def publish_question(question_id: str) -> PublishDecision:
    try:
        return get_question_bank().publish(question_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="题目不存在") from exc
