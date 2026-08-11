from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Query

from app.core.config import get_settings
from app.modules.model_operations import ModelOperationsDashboard, ModelOperationsRegistry


router = APIRouter(prefix="/admin/model-operations", tags=["model-operations"])


@lru_cache
def get_model_operations_registry() -> ModelOperationsRegistry:
    settings = get_settings()
    return ModelOperationsRegistry(
        settings.model_operations_db,
        input_rate=settings.openai_input_usd_per_million,
        cached_input_rate=settings.openai_cached_input_usd_per_million,
        output_rate=settings.openai_output_usd_per_million,
    )


@router.get("", response_model=ModelOperationsDashboard)
def model_operations_dashboard(
    limit: int = Query(default=50, ge=1, le=200),
) -> ModelOperationsDashboard:
    settings = get_settings()
    return get_model_operations_registry().dashboard(
        api_configured=bool(settings.openai_api_key),
        model=settings.openai_model,
        reasoning_effort=settings.openai_reasoning_effort,
        timeout_seconds=settings.openai_timeout_seconds,
        lesson_plan_provider=settings.lesson_plan_provider,
        question_variant_provider=settings.question_variant_provider,
        solution_provider=settings.solution_provider,
        limit=limit,
    )
