from __future__ import annotations

from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.modules.lesson_exports import LessonPlanDocumentRenderer, LessonPlanExportError
from app.modules.lesson_plans import (
    LessonPlanBlock,
    DeepSeekLessonPlanProvider,
    LessonPlanBlockLockCommand,
    LessonPlanBlockRewriteCommand,
    LessonPlanBlockRewriteResult,
    LessonPlanGenerationRequest,
    LessonPlanList,
    LessonPlanLifecycleCommand,
    LessonPlanProviderError,
    LessonPlanStudio,
    LessonPlanStudioError,
    LessonPlanUpdateCommand,
    LessonPlanView,
    OpenAIResponsesLessonPlanProvider,
    TemplateLessonPlanProvider,
)
from app.modules.curriculum import CsvCurriculumCatalog, CurriculumBaseline
from app.routes.model_operations import get_model_operations_registry
from app.routes.questions import get_question_bank


router = APIRouter(prefix="/lesson-plans", tags=["lesson-plans"])


@lru_cache
def get_lesson_plan_studio() -> LessonPlanStudio:
    settings = get_settings()
    baseline = CurriculumBaseline.load(
        settings.curriculum_baseline_manifest, settings.curriculum_csv
    )
    use_deepseek = settings.lesson_plan_provider == "deepseek" or (
        settings.lesson_plan_provider == "auto" and bool(settings.deepseek_api_key)
    )
    use_openai = not use_deepseek and (
        settings.lesson_plan_provider == "openai" or (
            settings.lesson_plan_provider == "auto" and bool(settings.openai_api_key)
        )
    )
    provider = DeepSeekLessonPlanProvider(
        api_key=settings.deepseek_api_key,
        model=settings.deepseek_model,
        base_url=settings.deepseek_base_url,
        timeout_seconds=settings.deepseek_timeout_seconds,
        recorder=get_model_operations_registry(),
    ) if use_deepseek else (
        OpenAIResponsesLessonPlanProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            reasoning_effort=settings.openai_reasoning_effort,
            timeout_seconds=settings.openai_timeout_seconds,
            recorder=get_model_operations_registry(),
        )
        if use_openai
        else TemplateLessonPlanProvider(recorder=get_model_operations_registry())
    )
    return LessonPlanStudio(
        database_path=settings.lesson_plan_db,
        curriculum_catalog=CsvCurriculumCatalog(settings.curriculum_csv),
        curriculum_baseline=baseline,
        question_bank=get_question_bank(),
        provider=provider,
    )


@lru_cache
def get_lesson_plan_renderer() -> LessonPlanDocumentRenderer:
    settings = get_settings()
    return LessonPlanDocumentRenderer(
        output_root=settings.lesson_export_dir,
        cjk_font_regular=settings.cjk_font_regular,
        cjk_font_bold=settings.cjk_font_bold,
    )


@router.get("", response_model=LessonPlanList)
def list_lesson_plans(limit: int = Query(default=30, ge=1, le=100), lifecycle_state: Literal["active", "trashed"] = Query(default="active")) -> LessonPlanList:
    return get_lesson_plan_studio().list(limit=limit, lifecycle_state=lifecycle_state)


@router.post("/{lesson_plan_id}/lifecycle", response_model=LessonPlanView)
def change_lesson_plan_lifecycle(lesson_plan_id: str, command: LessonPlanLifecycleCommand) -> LessonPlanView:
    try:
        return get_lesson_plan_studio().change_lifecycle(lesson_plan_id, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="教案不存在") from exc


@router.post("/generate", response_model=LessonPlanView, status_code=201)
def generate_lesson_plan(command: LessonPlanGenerationRequest) -> LessonPlanView:
    try:
        return get_lesson_plan_studio().create(command)
    except LessonPlanStudioError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LessonPlanProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/{lesson_plan_id}", response_model=LessonPlanView)
def get_lesson_plan(lesson_plan_id: str) -> LessonPlanView:
    try:
        return get_lesson_plan_studio().get(lesson_plan_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="教案不存在") from exc


@router.put("/{lesson_plan_id}/blocks/{block}/lock", response_model=LessonPlanView)
def set_lesson_plan_block_lock(
    lesson_plan_id: str,
    block: LessonPlanBlock,
    command: LessonPlanBlockLockCommand,
) -> LessonPlanView:
    try:
        return get_lesson_plan_studio().set_block_lock(
            lesson_plan_id, block, locked=command.locked
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="教案不存在") from exc


@router.post(
    "/{lesson_plan_id}/blocks/{block}/rewrite",
    response_model=LessonPlanBlockRewriteResult,
)
def rewrite_lesson_plan_block(
    lesson_plan_id: str,
    block: LessonPlanBlock,
    command: LessonPlanBlockRewriteCommand,
) -> LessonPlanBlockRewriteResult:
    try:
        return get_lesson_plan_studio().rewrite_block(lesson_plan_id, block, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="教案不存在") from exc
    except LessonPlanStudioError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LessonPlanProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/{lesson_plan_id}/export")
def export_lesson_plan(
    lesson_plan_id: str,
    format: Literal["docx", "pdf"] = Query(default="docx"),
) -> FileResponse:
    try:
        plan = get_lesson_plan_studio().get(lesson_plan_id)
        rendered = get_lesson_plan_renderer().render(plan, format)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="教案不存在") from exc
    except LessonPlanExportError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FileResponse(
        path=rendered.path,
        media_type=rendered.media_type,
        filename=rendered.download_name,
    )


@router.patch("/{lesson_plan_id}", response_model=LessonPlanView)
def update_lesson_plan(
    lesson_plan_id: str, command: LessonPlanUpdateCommand
) -> LessonPlanView:
    try:
        return get_lesson_plan_studio().update(lesson_plan_id, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="教案不存在") from exc
    except LessonPlanStudioError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
