from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.modules.pdf_imports import (
    BoundaryCandidateCreate,
    BoundaryCandidateList,
    BoundaryCandidateUpdate,
    BoundaryCandidateView,
    BoundaryProposalResult,
    ImportAnalysisResult,
    ImportBatchAnalysisResult,
    ImportBatchQueueResult,
    ImportBatchCommand,
    ImportBatchResult,
    ImportFileDetail,
    ImportQueueStepResult,
    ImportRightsBasis,
    ImportWorkspace,
    PdfImportError,
    PdfImportStudio,
    SourcePairProposalResult,
    SourcePairReviewCommand,
    SourcePairingFileView,
    SourcePairView,
    StructuredDraftImportResult,
    StructuredDraftProposalResult,
    StructuredDraftRepairResult,
    StructuredFormulaReviewCommand,
    StructuredMediaCropCommand,
    StructuredMediaCropView,
    StructuredQuestionDraftList,
    StructuredQuestionDraftUpdate,
    StructuredQuestionDraftView,
)
from app.modules.question_bank import QuestionBank, QuestionBankError


router = APIRouter(prefix="/imports", tags=["pdf-imports"])


@lru_cache
def get_pdf_import_studio() -> PdfImportStudio:
    settings = get_settings()
    return PdfImportStudio(
        settings.pdf_import_db,
        settings.pdf_import_dir,
        settings.pdf_question_estimates_csv,
    )


@lru_cache
def get_import_question_bank() -> QuestionBank:
    settings = get_settings()
    return QuestionBank(settings.question_bank_db, settings.question_media_dir)


@router.get("", response_model=ImportWorkspace)
def import_workspace(limit: int = Query(default=30, ge=1, le=100)) -> ImportWorkspace:
    return get_pdf_import_studio().workspace(limit=limit)


@router.post("/source-pairs/propose", response_model=SourcePairProposalResult)
def propose_source_pairs() -> SourcePairProposalResult:
    return get_pdf_import_studio().propose_source_pairs()


@router.patch("/source-pairs/{pair_id}", response_model=SourcePairView)
def review_source_pair(
    pair_id: str, command: SourcePairReviewCommand
) -> SourcePairView:
    try:
        return get_pdf_import_studio().review_source_pair(pair_id, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="来源配对候选不存在") from exc


@router.post("/batches", response_model=ImportBatchResult, status_code=201)
async def create_import_batch(
    files: list[UploadFile] = File(...),
    title: str = Form(..., min_length=1, max_length=300),
    rights_basis: ImportRightsBasis = Form(...),
    rights_statement: str = Form(..., min_length=6, max_length=2000),
    rights_acknowledged: bool = Form(...),
    owner_id: str = Form(default="owner_teacher", min_length=1, max_length=120),
) -> ImportBatchResult:
    uploads: list[tuple[str, bytes]] = []
    try:
        if len(files) > PdfImportStudio.MAX_FILES_PER_BATCH:
            raise PdfImportError(
                f"单个批次最多上传 {PdfImportStudio.MAX_FILES_PER_BATCH} 份 PDF"
            )
        running_total = 0
        for upload in files:
            content = await upload.read(PdfImportStudio.MAX_FILE_BYTES + 1)
            running_total += len(content)
            if running_total > PdfImportStudio.MAX_BATCH_BYTES:
                raise PdfImportError("单个批次文件总量不能超过 350 MB")
            uploads.append((upload.filename or "未命名.pdf", content))
        return get_pdf_import_studio().create_batch(
            ImportBatchCommand(
                title=title,
                rights_basis=rights_basis,
                rights_statement=rights_statement,
                rights_acknowledged=rights_acknowledged,
                owner_id=owner_id,
            ),
            uploads,
        )
    except PdfImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/files/{file_id}", response_model=ImportFileDetail)
def import_file_detail(file_id: str) -> ImportFileDetail:
    try:
        return get_pdf_import_studio().inspect(file_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="导入文件不存在") from exc


@router.get("/files/{file_id}/source-pairing", response_model=SourcePairingFileView)
def import_file_source_pairing(file_id: str) -> SourcePairingFileView:
    try:
        return get_pdf_import_studio().source_pairing(file_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="导入文件不存在") from exc


@router.post("/files/{file_id}/analyze", response_model=ImportAnalysisResult)
def analyze_import_file(
    file_id: str,
    force: bool = Query(default=False),
    page_budget: int | None = Query(default=None, ge=1, le=200),
) -> ImportAnalysisResult:
    try:
        return get_pdf_import_studio().analyze(
            file_id, force=force, page_budget=page_budget
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="导入文件不存在") from exc
    except PdfImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/batches/{batch_id}/analyze", response_model=ImportBatchAnalysisResult
)
def analyze_import_batch(batch_id: str) -> ImportBatchAnalysisResult:
    try:
        return get_pdf_import_studio().analyze_batch(batch_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="导入批次不存在") from exc


@router.post(
    "/batches/{batch_id}/queue", response_model=ImportBatchQueueResult
)
def queue_import_batch(
    batch_id: str,
    retry_failed: bool = Query(default=True),
) -> ImportBatchQueueResult:
    try:
        return get_pdf_import_studio().queue_batch(batch_id, retry_failed=retry_failed)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="导入批次不存在") from exc


@router.post(
    "/batches/{batch_id}/pause", response_model=ImportBatchQueueResult
)
def pause_import_batch(batch_id: str) -> ImportBatchQueueResult:
    try:
        return get_pdf_import_studio().pause_batch(batch_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="导入批次不存在") from exc


@router.post(
    "/batches/{batch_id}/process-next", response_model=ImportQueueStepResult
)
def process_import_queue_step(
    batch_id: str,
    page_budget: int = Query(default=20, ge=1, le=100),
) -> ImportQueueStepResult:
    try:
        return get_pdf_import_studio().process_next(batch_id, page_budget=page_budget)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="导入批次不存在") from exc
    except PdfImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/files/{file_id}/source")
def import_source_file(file_id: str) -> FileResponse:
    try:
        path, file = get_pdf_import_studio().source_file(file_id)
        return FileResponse(path, media_type="application/pdf", filename=file.original_filename)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="导入文件不存在") from exc
    except PdfImportError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/files/{file_id}/pages/{page_number}/preview")
def import_page_preview(
    file_id: str,
    page_number: int,
    width: int = Query(default=1200, ge=600, le=1800),
) -> FileResponse:
    try:
        path = get_pdf_import_studio().preview_page(file_id, page_number, width=width)
        return FileResponse(path, media_type="image/png")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="导入文件不存在") from exc
    except PdfImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/files/{file_id}/boundary-candidates", response_model=BoundaryCandidateList
)
def list_boundary_candidates(file_id: str) -> BoundaryCandidateList:
    try:
        return get_pdf_import_studio().boundary_candidates(file_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="导入文件不存在") from exc


@router.post(
    "/files/{file_id}/boundary-candidates/propose",
    response_model=BoundaryProposalResult,
)
def propose_boundary_candidates(file_id: str) -> BoundaryProposalResult:
    try:
        return get_pdf_import_studio().propose_boundary_candidates(file_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="导入文件不存在") from exc
    except PdfImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/files/{file_id}/boundary-candidates",
    response_model=BoundaryCandidateView,
    status_code=201,
)
def create_boundary_candidate(
    file_id: str, command: BoundaryCandidateCreate
) -> BoundaryCandidateView:
    try:
        return get_pdf_import_studio().create_boundary_candidate(file_id, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="导入文件不存在") from exc
    except PdfImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch(
    "/files/{file_id}/boundary-candidates/{candidate_id}",
    response_model=BoundaryCandidateView,
)
def update_boundary_candidate(
    file_id: str, candidate_id: str, command: BoundaryCandidateUpdate
) -> BoundaryCandidateView:
    try:
        return get_pdf_import_studio().update_boundary_candidate(file_id, candidate_id, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="题目边界候选不存在") from exc
    except PdfImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/files/{file_id}/structured-drafts", response_model=StructuredQuestionDraftList
)
def list_structured_drafts(file_id: str) -> StructuredQuestionDraftList:
    try:
        return get_pdf_import_studio().structured_question_drafts(file_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="导入文件不存在") from exc


@router.post(
    "/files/{file_id}/structured-drafts/propose",
    response_model=StructuredDraftProposalResult,
)
def propose_structured_drafts(file_id: str) -> StructuredDraftProposalResult:
    try:
        return get_pdf_import_studio().propose_structured_question_drafts(file_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="导入文件不存在") from exc
    except PdfImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/files/{file_id}/structured-drafts/auto-repair",
    response_model=StructuredDraftRepairResult,
)
def auto_repair_structured_drafts(
    file_id: str, math_ocr: bool = Query(default=False)
) -> StructuredDraftRepairResult:
    try:
        return get_pdf_import_studio().auto_repair_structured_question_drafts(
            file_id, use_math_ocr=math_ocr
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="导入文件不存在") from exc
    except PdfImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch(
    "/files/{file_id}/structured-drafts/{draft_id}",
    response_model=StructuredQuestionDraftView,
)
def update_structured_draft(
    file_id: str, draft_id: str, command: StructuredQuestionDraftUpdate
) -> StructuredQuestionDraftView:
    try:
        return get_pdf_import_studio().update_structured_question_draft(
            file_id, draft_id, command
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="结构化题目草稿不存在") from exc
    except PdfImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/files/{file_id}/structured-drafts/{draft_id}/formula-review",
    response_model=StructuredQuestionDraftView,
)
def review_structured_formula(
    file_id: str, draft_id: str, command: StructuredFormulaReviewCommand
) -> StructuredQuestionDraftView:
    try:
        return get_pdf_import_studio().review_structured_formula(file_id, draft_id, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="结构化题目草稿不存在") from exc
    except PdfImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/files/{file_id}/structured-drafts/{draft_id}/media-crops",
    response_model=StructuredMediaCropView,
    status_code=201,
)
def create_structured_media_crop(
    file_id: str, draft_id: str, command: StructuredMediaCropCommand
) -> StructuredMediaCropView:
    try:
        return get_pdf_import_studio().create_media_crop(file_id, draft_id, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="文件或结构化草稿不存在") from exc
    except PdfImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/media-crops/{crop_id}/file")
def structured_media_crop_file(crop_id: str) -> FileResponse:
    try:
        path, crop = get_pdf_import_studio().media_crop_file(crop_id)
        return FileResponse(
            path,
            media_type="image/png",
            filename=f"第{crop.page_number}页-{crop.placement}-{crop.crop_id}.png",
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="裁剪图不存在") from exc
    except PdfImportError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete(
    "/files/{file_id}/structured-drafts/{draft_id}/media-crops/{crop_id}",
    status_code=204,
)
def delete_structured_media_crop(file_id: str, draft_id: str, crop_id: str) -> Response:
    try:
        get_pdf_import_studio().delete_media_crop(file_id, draft_id, crop_id)
        return Response(status_code=204)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="草稿或裁剪图不存在") from exc
    except PdfImportError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/files/{file_id}/structured-drafts/{draft_id}/import",
    response_model=StructuredDraftImportResult,
)
def import_structured_draft(file_id: str, draft_id: str) -> StructuredDraftImportResult:
    try:
        studio = get_pdf_import_studio()
        file = studio.inspect(file_id)
        batch = next(
            item for item in studio.workspace(limit=100).batches if item.batch_id == file.batch_id
        )
        draft = next(
            item for item in studio.structured_question_drafts(file_id).items
            if item.draft_id == draft_id
        )
        if draft.imported_question_id:
            return StructuredDraftImportResult(
                draft=draft,
                question_id=draft.imported_question_id,
                already_imported=True,
            )
        if draft.status != "confirmed":
            raise PdfImportError("结构化草稿必须先由教师确认，才能进入题库审核")
        candidate = {
            **draft.model_dump(),
            "candidate_id": f"cand_pdf_{draft.draft_id}",
            "source_version": 1,
            "provenance_type": "pdf_import_structured_pipeline",
            "source_reference": f"PDF 加工文件 {file_id} · 第 {draft.start_page}—{draft.end_page} 页",
        }
        resource = {
            "library_item_id": file_id,
            "title": file.original_filename,
            "original_filename": file.original_filename,
            "rights_basis": batch.rights_basis,
            "rights_statement": batch.rights_statement,
            "adaptation_allowed": batch.rights_basis != "private_research_only",
        }
        question = get_import_question_bank().create_private_resource_question(
            candidate, resource=resource
        )
        for crop in draft.media_crops:
            if crop.imported_image_id:
                continue
            crop_path, _ = studio.media_crop_file(crop.crop_id)
            image = get_import_question_bank().add_image(
                question.question_id,
                crop_path.read_bytes(),
                f"{file.original_filename}-第{crop.page_number}页-{crop.crop_id}.png",
                crop.placement,
                crop.note or f"来源 PDF 第 {crop.page_number} 页裁剪图",
                f"从《{file.original_filename}》第 {crop.page_number} 页框选；保留来源坐标证据。",
                "pdf_import_structured_pipeline",
            )
            studio.mark_media_crop_imported(crop.crop_id, image.image_id)
        marked = studio.mark_structured_draft_imported(file_id, draft_id, question.question_id)
        return StructuredDraftImportResult(draft=marked, question_id=question.question_id)
    except (KeyError, StopIteration) as exc:
        raise HTTPException(status_code=404, detail="文件、批次或结构化草稿不存在") from exc
    except (PdfImportError, QuestionBankError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
