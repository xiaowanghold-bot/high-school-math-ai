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
    use_deepseek = bool(settings.deepseek_api_key)
    return get_model_operations_registry().dashboard(
        api_configured=use_deepseek or bool(settings.openai_api_key),
        model=settings.deepseek_model if use_deepseek else settings.openai_model,
        reasoning_effort=settings.openai_reasoning_effort,
        timeout_seconds=settings.openai_timeout_seconds,
        lesson_plan_provider=settings.lesson_plan_provider,
        question_variant_provider=settings.question_variant_provider,
        solution_provider=settings.solution_provider,
        external_provider="deepseek" if use_deepseek else "openai",
        provider_configuration={
            "deepseek": (bool(settings.deepseek_api_key), settings.deepseek_model),
            "openai": (bool(settings.openai_api_key), settings.openai_model),
        },
        ocr_api_configured=bool(settings.openai_api_key),
        limit=limit,
    )
