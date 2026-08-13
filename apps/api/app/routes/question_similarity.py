from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.config import get_settings
from app.modules.question_similarity import (
    DuplicateReviewCommand,
    DuplicateReviewResult,
    DuplicateScanResult,
    DuplicateWorkspace,
    DuplicateLibraryStateCommand,
    DuplicateLibraryStateResult,
    QuestionSimilarityError,
    QuestionSimilarityRegistry,
)
from app.routes.questions import get_question_bank


router = APIRouter(prefix="/question-similarity", tags=["question-similarity"])


@lru_cache
def get_question_similarity_registry() -> QuestionSimilarityRegistry:
    settings = get_settings()
    return QuestionSimilarityRegistry(
        settings.question_similarity_db,
        question_bank=get_question_bank(),
    )


@router.get("", response_model=DuplicateWorkspace)
def duplicate_workspace(
    status: str | None = Query(default=None),
    relation: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    registry: QuestionSimilarityRegistry = Depends(get_question_similarity_registry),
) -> DuplicateWorkspace:
    return registry.workspace(
        status=status,
        relation=relation,
        limit=limit,
    )


@router.post("/scan", response_model=DuplicateScanResult)
def scan_question_similarity(
    registry: QuestionSimilarityRegistry = Depends(get_question_similarity_registry),
) -> DuplicateScanResult:
    return registry.scan()


@router.patch("/{candidate_id}", response_model=DuplicateReviewResult)
def review_question_similarity(
    candidate_id: str,
    command: DuplicateReviewCommand,
    registry: QuestionSimilarityRegistry = Depends(get_question_similarity_registry),
) -> DuplicateReviewResult:
    try:
        return registry.review(candidate_id, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="重复候选不存在") from exc
    except QuestionSimilarityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/{candidate_id}/library-state", response_model=DuplicateLibraryStateResult)
def change_duplicate_library_state(
    candidate_id: str,
    command: DuplicateLibraryStateCommand,
    registry: QuestionSimilarityRegistry = Depends(get_question_similarity_registry),
) -> DuplicateLibraryStateResult:
    try:
        return registry.change_library_state(candidate_id, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="重复候选不存在") from exc
    except QuestionSimilarityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
