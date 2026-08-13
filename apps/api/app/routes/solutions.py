from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.modules.solution_assistant import (
    DeepSeekSolutionProvider,
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
    use_deepseek = settings.solution_provider == "deepseek" or (
        settings.solution_provider == "auto" and bool(settings.deepseek_api_key)
    )
    use_openai = not use_deepseek and (
        settings.solution_provider == "openai" or (
            settings.solution_provider == "auto" and bool(settings.openai_api_key)
        )
    )
    provider = DeepSeekSolutionProvider(
        api_key=settings.deepseek_api_key,
        model=settings.deepseek_model,
        base_url=settings.deepseek_base_url,
        timeout_seconds=settings.deepseek_timeout_seconds,
        recorder=get_model_operations_registry(),
    ) if use_deepseek else (
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
