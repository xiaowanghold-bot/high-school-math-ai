from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.modules.math_verifier import MathVerifier
from app.modules.question_bank import (
    QuestionBank,
    QuestionBankError,
    QuestionImage,
    QuestionImageMetadataCommand,
    QuestionImageOrderCommand,
    QuestionLibraryStateCommand,
    QuestionLibraryStateResult,
    QuestionRevisionCommand,
    QuestionRevisionResult,
    ReviewCommand,
)
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
from app.modules.question_variants import (
    DeepSeekQuestionVariantProvider,
    LocalDiagnosticVariantProvider,
    OpenAIQuestionVariantProvider,
    QuestionVariantGenerationRequest,
    QuestionVariantGenerationResult,
    QuestionVariantProviderError,
    QuestionVariantService,
    QuestionVariantServiceError,
    TeacherVariantDraftCommand,
)
from app.modules.question_quality import (
    BatchCurriculumActionResult,
    BatchCurriculumInspectCommand,
    BatchCurriculumMappingCommand,
    BatchCurriculumWorkspace,
    CurriculumMappingCommand,
    ManualVerificationCommand,
    QualityActionResult,
    QuestionQualityError,
    QuestionQualityWorkflow,
    QuestionQualityWorkspace,
)
from app.modules.curriculum import CsvCurriculumCatalog
from app.routes.model_operations import get_model_operations_registry


router = APIRouter(tags=["question-bank"])


@lru_cache
def get_question_bank() -> QuestionBank:
    settings = get_settings()
    bank = QuestionBank(settings.question_bank_db, settings.question_media_dir)
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


@lru_cache
def get_question_variant_service() -> QuestionVariantService:
    settings = get_settings()
    use_deepseek = settings.question_variant_provider == "deepseek" or (
        settings.question_variant_provider == "auto" and bool(settings.deepseek_api_key)
    )
    use_openai = not use_deepseek and (
        settings.question_variant_provider == "openai" or (
            settings.question_variant_provider == "auto" and bool(settings.openai_api_key)
        )
    )
    provider = DeepSeekQuestionVariantProvider(
        api_key=settings.deepseek_api_key,
        model=settings.deepseek_model,
        base_url=settings.deepseek_base_url,
        timeout_seconds=settings.deepseek_timeout_seconds,
        recorder=get_model_operations_registry(),
    ) if use_deepseek else (
        OpenAIQuestionVariantProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            reasoning_effort=settings.openai_reasoning_effort,
            timeout_seconds=settings.openai_timeout_seconds,
            recorder=get_model_operations_registry(),
        )
        if use_openai
        else LocalDiagnosticVariantProvider(recorder=get_model_operations_registry())
    )
    return QuestionVariantService(question_bank=get_question_bank(), provider=provider)


@lru_cache
def get_question_quality_workflow() -> QuestionQualityWorkflow:
    settings = get_settings()
    return QuestionQualityWorkflow(
        question_bank=get_question_bank(),
        curriculum_catalog=CsvCurriculumCatalog(settings.curriculum_csv),
    )


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
    knowledge_point_id: str | None = Query(default=None, max_length=160),
    module: str | None = None,
    work_queue: str | None = None,
    library_state: str = Query(default="active"),
    usage_scope: str = Query(default="admin"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> QuestionSearchPage:
    try:
        return get_question_bank().search(
            query=query,
            chapter=chapter,
            difficulty=difficulty,
            verification_status=verification_status,
            review_status=review_status,
            knowledge_point_id=knowledge_point_id,
            module=module,
            work_queue=work_queue,
            library_state=library_state,
            usage_scope=usage_scope,
            page=page,
            page_size=page_size,
        )
    except QuestionBankError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/questions/library-state", response_model=QuestionLibraryStateResult)
def change_question_library_state(
    command: QuestionLibraryStateCommand,
) -> QuestionLibraryStateResult:
    try:
        return get_question_bank().change_library_state(command)
    except QuestionBankError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/questions/{question_id}", response_model=QuestionDetail)
def get_question(question_id: str) -> QuestionDetail:
    try:
        return get_question_bank().get_question(question_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="题目不存在") from exc


@router.post(
    "/questions/{question_id}/variants",
    response_model=QuestionVariantGenerationResult,
    status_code=201,
)
def generate_question_variant(
    question_id: str, command: QuestionVariantGenerationRequest
) -> QuestionVariantGenerationResult:
    try:
        return get_question_variant_service().generate(question_id, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="题目不存在") from exc
    except (QuestionVariantServiceError, QuestionBankError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except QuestionVariantProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post(
    "/questions/{question_id}/teacher-variants",
    response_model=QuestionDetail,
    status_code=201,
)
def save_teacher_variant(question_id: str, command: TeacherVariantDraftCommand) -> QuestionDetail:
    try:
        return get_question_variant_service().save_teacher_draft(question_id, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="题目不存在") from exc
    except (QuestionVariantServiceError, QuestionBankError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/questions/{question_id}", response_model=QuestionRevisionResult)
def revise_question(
    question_id: str, command: QuestionRevisionCommand
) -> QuestionRevisionResult:
    try:
        return get_question_bank().revise(question_id, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="题目不存在") from exc
    except QuestionBankError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/questions/{question_id}/quality", response_model=QuestionQualityWorkspace
)
def question_quality_workspace(question_id: str) -> QuestionQualityWorkspace:
    try:
        return get_question_quality_workflow().inspect(question_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="题目不存在") from exc


@router.post(
    "/questions/quality/curriculum/batch/inspect",
    response_model=BatchCurriculumWorkspace,
)
def inspect_question_curriculum_batch(
    command: BatchCurriculumInspectCommand,
) -> BatchCurriculumWorkspace:
    try:
        return get_question_quality_workflow().inspect_curriculum_batch(command.question_ids)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"题目不存在：{exc.args[0]}") from exc
    except QuestionQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/questions/quality/curriculum/batch/apply",
    response_model=BatchCurriculumActionResult,
)
def apply_question_curriculum_batch(
    command: BatchCurriculumMappingCommand,
) -> BatchCurriculumActionResult:
    try:
        return get_question_quality_workflow().apply_curriculum_batch(command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"题目不存在：{exc.args[0]}") from exc
    except QuestionQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except QuestionBankError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/questions/{question_id}/quality/curriculum", response_model=QualityActionResult
)
def apply_question_curriculum(
    question_id: str, command: CurriculumMappingCommand
) -> QualityActionResult:
    try:
        return get_question_quality_workflow().apply_curriculum(question_id, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="题目不存在") from exc
    except QuestionQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except QuestionBankError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/questions/{question_id}/quality/verification", response_model=QualityActionResult
)
def record_question_verification(
    question_id: str, command: ManualVerificationCommand
) -> QualityActionResult:
    try:
        return get_question_quality_workflow().record_verification(question_id, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="题目不存在") from exc
    except QuestionQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/questions/{question_id}/images", response_model=QuestionImage, status_code=201)
async def upload_question_image(
    question_id: str,
    file: UploadFile = File(...),
    placement: str = Form("stem"),
    alt_text: str = Form(""),
    caption: str = Form(""),
    actor_id: str = Form("owner_teacher"),
) -> QuestionImage:
    try:
        return get_question_bank().add_image(
            question_id,
            await file.read(),
            file.filename or "image",
            placement,
            alt_text,
            caption,
            actor_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="题目不存在") from exc
    except QuestionBankError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch(
    "/questions/{question_id}/images/{image_id}", response_model=QuestionImage
)
def update_question_image(
    question_id: str, image_id: str, command: QuestionImageMetadataCommand
) -> QuestionImage:
    try:
        return get_question_bank().update_image(question_id, image_id, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="图片不存在") from exc
    except QuestionBankError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put(
    "/questions/{question_id}/images/{image_id}/file", response_model=QuestionImage
)
async def replace_question_image(
    question_id: str,
    image_id: str,
    file: UploadFile = File(...),
    actor_id: str = Form("owner_teacher"),
) -> QuestionImage:
    try:
        return get_question_bank().replace_image(
            question_id,
            image_id,
            await file.read(),
            file.filename or "image",
            actor_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="图片不存在") from exc
    except QuestionBankError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete(
    "/questions/{question_id}/images/{image_id}", status_code=204,
)
def delete_question_image(question_id: str, image_id: str) -> Response:
    try:
        get_question_bank().delete_image(question_id, image_id)
        return Response(status_code=204)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="图片不存在") from exc
    except QuestionBankError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/questions/{question_id}/images/order", response_model=list[QuestionImage])
def reorder_question_images(
    question_id: str, command: QuestionImageOrderCommand
) -> list[QuestionImage]:
    try:
        return get_question_bank().reorder_images(question_id, command.image_ids)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="题目不存在") from exc
    except QuestionBankError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/questions/{question_id}/images/{image_id}/content")
def question_image_content(question_id: str, image_id: str) -> FileResponse:
    try:
        path, mime_type = get_question_bank().image_path(question_id, image_id)
        return FileResponse(path, media_type=mime_type)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="图片不存在") from exc


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
