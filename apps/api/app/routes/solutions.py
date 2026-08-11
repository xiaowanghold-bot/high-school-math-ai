from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.modules.solution_assistant import (
    OpenAISolutionProvider,
    SolutionAssistant,
    SolutionAssistantError,
    SolutionProviderError,
    SolutionRequest,
    SolutionResult,
)
from app.routes.questions import get_question_bank
from app.routes.model_operations import get_model_operations_registry


router = APIRouter(prefix="/solutions", tags=["solution-assistant"])


@lru_cache
def get_solution_assistant() -> SolutionAssistant:
    settings = get_settings()
    use_openai = settings.solution_provider == "openai" or (
        settings.solution_provider == "auto" and bool(settings.openai_api_key)
    )
    provider = (
        OpenAISolutionProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            reasoning_effort=settings.openai_reasoning_effort,
            timeout_seconds=settings.openai_timeout_seconds,
            recorder=get_model_operations_registry(),
        )
        if use_openai
        else None
    )
    return SolutionAssistant(question_bank=get_question_bank(), provider=provider)


@router.post("/solve", response_model=SolutionResult)
def solve_question(command: SolutionRequest) -> SolutionResult:
    try:
        return get_solution_assistant().solve(command)
    except SolutionAssistantError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SolutionProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
