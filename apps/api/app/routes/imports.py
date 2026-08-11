from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.modules.pdf_imports import (
    ImportAnalysisResult,
    ImportBatchAnalysisResult,
    ImportBatchCommand,
    ImportBatchResult,
    ImportFileDetail,
    ImportRightsBasis,
    ImportWorkspace,
    PdfImportError,
    PdfImportStudio,
)


router = APIRouter(prefix="/imports", tags=["pdf-imports"])


@lru_cache
def get_pdf_import_studio() -> PdfImportStudio:
    settings = get_settings()
    return PdfImportStudio(settings.pdf_import_db, settings.pdf_import_dir)


@router.get("", response_model=ImportWorkspace)
def import_workspace(limit: int = Query(default=30, ge=1, le=100)) -> ImportWorkspace:
    return get_pdf_import_studio().workspace(limit=limit)


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


@router.post("/files/{file_id}/analyze", response_model=ImportAnalysisResult)
def analyze_import_file(file_id: str) -> ImportAnalysisResult:
    try:
        return get_pdf_import_studio().analyze(file_id)
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
