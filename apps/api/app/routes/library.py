from __future__ import annotations

import json
import re
from functools import lru_cache
from threading import Lock
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.modules.private_library import (
    CandidateImportResult,
    LibraryIngestCommand,
    LibraryLifecycleCommand,
    LibraryOCRCommand,
    LibraryOCRResult,
    LibraryAIRepairCommand,
    LibraryAIRepairResult,
    LibraryItemList,
    LibraryItemView,
    LibraryStats,
    LibraryTextReviewCommand,
    OCRProviderError,
    OpenAIResourceOCRProvider,
    LocalMathOCRProvider,
    PrivateLibrary,
    PrivateLibraryError,
    QuestionCandidateList,
    QuestionCandidateUpdate,
    QuestionCandidateView,
    RightsBasis,
)
from app.modules.question_bank import QuestionBank, QuestionBankError
from app.modules.pdf_imports import ImportBatchCommand, ImportBatchResult, PdfImportError
from app.routes.imports import get_pdf_import_studio
from app.routes.model_operations import get_model_operations_registry
from app.modules.private_library.exports import LibraryExportError, LibraryTextRenderer
from app.modules.deepseek import DeepSeekClientError, DeepSeekJsonClient


router = APIRouter(prefix="/library", tags=["private-library"])
_local_math_ocr_lock = Lock()


@lru_cache
def get_private_library() -> PrivateLibrary:
    settings = get_settings()
    return PrivateLibrary(settings.private_library_db, settings.private_library_dir)


@lru_cache
def get_library_question_bank() -> QuestionBank:
    settings = get_settings()
    return QuestionBank(settings.question_bank_db, settings.question_media_dir)


def get_library_ocr_provider() -> OpenAIResourceOCRProvider:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("尚未配置 OCR 服务；可先人工转录，或配置 MATH_AI_OPENAI_API_KEY")
    return OpenAIResourceOCRProvider(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        timeout_seconds=settings.openai_timeout_seconds,
        recorder=get_model_operations_registry(),
    )


def get_local_math_ocr_provider() -> LocalMathOCRProvider:
    return LocalMathOCRProvider()


@lru_cache
def get_library_text_renderer() -> LibraryTextRenderer:
    return LibraryTextRenderer(get_settings().lesson_export_dir)


def get_library_ai_repair_client() -> DeepSeekJsonClient:
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise RuntimeError("尚未配置 DeepSeek API Key")
    return DeepSeekJsonClient(
        api_key=settings.deepseek_api_key,
        model=settings.deepseek_model,
        base_url=settings.deepseek_base_url,
        timeout_seconds=settings.deepseek_timeout_seconds,
    )


def _split_latex_repair_draft(text: str, *, max_chars: int = 7000) -> list[str]:
    """Split long papers on page boundaries so DeepSeek can return complete JSON."""
    page_parts = re.split(r"(?=【第\s*\d+\s*页】)", text)
    parts = [part for part in page_parts if part]
    if not parts:
        parts = [text]
    chunks: list[str] = []
    current = ""
    for part in parts:
        if current and len(current) + len(part) > max_chars:
            chunks.append(current)
            current = ""
        while len(part) > max_chars:
            split_at = part.rfind("\n", 0, max_chars)
            if split_at < max_chars // 2:
                split_at = max_chars
            if current:
                chunks.append(current)
                current = ""
            chunks.append(part[:split_at])
            part = part[split_at:]
        current += part
    if current:
        chunks.append(current)
    return chunks


@router.get("", response_model=LibraryItemList)
def list_library_items(
    limit: int = Query(default=50, ge=1, le=100),
    lifecycle_state: str = Query(default="active"),
) -> LibraryItemList:
    try:
        return get_private_library().list(limit=limit, lifecycle_state=lifecycle_state)
    except PrivateLibraryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/stats", response_model=LibraryStats)
def library_stats() -> LibraryStats:
    return get_private_library().stats()


@router.post("", response_model=LibraryItemView, status_code=201)
async def upload_library_item(
    file: UploadFile = File(...),
    title: str = Form("", max_length=300),
    rights_basis: RightsBasis = Form(...),
    rights_statement: str = Form(..., min_length=6, max_length=2000),
    rights_acknowledged: bool = Form(...),
    owner_id: str = Form("owner_teacher", min_length=1, max_length=120),
) -> LibraryItemView:
    try:
        content = await file.read(PrivateLibrary.MAX_FILE_BYTES + 1)
        return get_private_library().ingest(
            LibraryIngestCommand(
                title=title,
                rights_basis=rights_basis,
                rights_statement=rights_statement,
                rights_acknowledged=rights_acknowledged,
                owner_id=owner_id,
            ),
            filename=file.filename or "未命名资料",
            content=content,
        )
    except PrivateLibraryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{item_id}", response_model=LibraryItemView)
def get_library_item(item_id: str) -> LibraryItemView:
    try:
        return get_private_library().get(item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="私人资料不存在") from exc


@router.patch("/{item_id}/review", response_model=LibraryItemView)
def review_library_text(
    item_id: str, command: LibraryTextReviewCommand
) -> LibraryItemView:
    try:
        return get_private_library().review(item_id, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="私人资料不存在") from exc
    except PrivateLibraryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{item_id}/lifecycle", response_model=LibraryItemView)
def change_library_item_lifecycle(
    item_id: str, command: LibraryLifecycleCommand
) -> LibraryItemView:
    try:
        return get_private_library().change_lifecycle(item_id, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="私人资料不存在") from exc


@router.post("/{item_id}/ocr", response_model=LibraryOCRResult)
def run_library_ocr(item_id: str, command: LibraryOCRCommand) -> LibraryOCRResult:
    try:
        provider = get_library_ocr_provider()
        item, provider_name, warnings = get_private_library().apply_ocr(
            item_id,
            provider=provider,
            consent=command.external_processing_consent,
            teacher_id=command.teacher_id,
        )
        return LibraryOCRResult(item=item, provider=provider_name, warnings=warnings)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="私人资料不存在") from exc
    except OCRProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PrivateLibraryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{item_id}/local-math-ocr", response_model=LibraryOCRResult)
def run_local_math_ocr(item_id: str) -> LibraryOCRResult:
    if not _local_math_ocr_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="本地数学 OCR 正在处理另一份资料，请等待当前任务完成后再试")
    try:
        item, provider_name, warnings = get_private_library().apply_local_ocr(
            item_id,
            provider=get_local_math_ocr_provider(),
            teacher_id="owner_teacher",
        )
        return LibraryOCRResult(item=item, provider=provider_name, warnings=warnings)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="私人资料不存在") from exc
    except OCRProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except PrivateLibraryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        _local_math_ocr_lock.release()


@router.post("/{item_id}/ai-repair", response_model=LibraryAIRepairResult)
def repair_library_latex(item_id: str, command: LibraryAIRepairCommand) -> LibraryAIRepairResult:
    if not command.external_processing_consent:
        raise HTTPException(
            status_code=422,
            detail="使用 DeepSeek 修复前必须明确同意发送当前校对草稿；原 PDF 不会发送",
        )
    try:
        item = get_private_library().get(item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="私人资料不存在") from exc
    if item.lifecycle_state == "trashed":
        raise HTTPException(status_code=409, detail="回收站中的资料不能运行 AI 修复")
    settings = get_settings()
    try:
        client = get_library_ai_repair_client()
        chunks = _split_latex_repair_draft(command.draft_text)
        repaired_chunks: list[str] = []
        warnings: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            raw = client.request(
                instructions=(
                    "你是高中数学试卷 LaTeX 校对助手。修复 OCR 文本中的数学公式、上下标、分式、"
                    "集合符号、向量、题号和选项排版。保留原有中文、页码、题目顺序、答案和解析，"
                    "不得补造原文没有的题目、答案、数值或图形。数学表达式统一放在单个美元符号中。"
                    "无法可靠判断的内容原样保留，并写入 warnings。"
                ),
                input_text=json.dumps(
                    {
                        "teacher_instruction": command.instruction,
                        "chunk_position": f"{index}/{len(chunks)}",
                        "draft_text": chunk,
                    },
                    ensure_ascii=False,
                ),
                action="私人资料 LaTeX 校对",
                output_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "repaired_text": {"type": "string"},
                        "warnings": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["repaired_text", "warnings"],
                },
            )
            content = json.loads(raw["output"][0]["content"][0]["text"])
            repaired_chunk = str(content["repaired_text"]).strip()
            if not repaired_chunk:
                raise ValueError(f"第 {index}/{len(chunks)} 段修复结果为空")
            repaired_chunks.append(repaired_chunk)
            warnings.extend(str(value) for value in content.get("warnings", []))
        repaired = "\n\n".join(repaired_chunks)
        if not repaired:
            raise ValueError("修复结果为空")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (
        DeepSeekClientError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise HTTPException(status_code=503, detail=f"DeepSeek LaTeX 修复失败：{exc}") from exc
    return LibraryAIRepairResult(
        repaired_text=repaired,
        provider="deepseek",
        model=settings.deepseek_model,
        warnings=warnings,
    )


@router.post("/{item_id}/send-to-structured-import", response_model=ImportBatchResult)
def send_library_item_to_structured_import(item_id: str) -> ImportBatchResult:
    try:
        path, item = get_private_library().file_for_download(item_id)
        if item.file_kind != "pdf":
            raise PrivateLibraryError("只有 PDF 可以转入逐页可视化结构化加工")
        rights_basis = {
            "original": "original",
            "licensed": "licensed",
            "private_teaching_only": "private_research_only",
        }[item.rights_basis]
        return get_pdf_import_studio().create_batch(
            ImportBatchCommand(
                title=f"{item.title} · 可视化重建",
                rights_basis=rights_basis,
                rights_statement=item.rights_statement,
                rights_acknowledged=True,
                owner_id="owner_teacher",
            ),
            [(item.original_filename, path.read_bytes())],
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="私人资料不存在") from exc
    except (PrivateLibraryError, PdfImportError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{item_id}/question-candidates", response_model=QuestionCandidateList)
def list_question_candidates(item_id: str) -> QuestionCandidateList:
    try:
        return get_private_library().list_question_candidates(item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="私人资料不存在") from exc


@router.post("/{item_id}/question-candidates", response_model=QuestionCandidateList)
def propose_question_candidates(item_id: str) -> QuestionCandidateList:
    try:
        return get_private_library().propose_questions(item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="私人资料不存在") from exc
    except PrivateLibraryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch(
    "/{item_id}/question-candidates/{candidate_id}", response_model=QuestionCandidateView
)
def update_question_candidate(
    item_id: str, candidate_id: str, command: QuestionCandidateUpdate
) -> QuestionCandidateView:
    try:
        return get_private_library().update_question_candidate(item_id, candidate_id, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="拆题候选不存在") from exc
    except PrivateLibraryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete(
    "/{item_id}/question-candidates/{candidate_id}", response_model=QuestionCandidateView
)
def discard_question_candidate(item_id: str, candidate_id: str) -> QuestionCandidateView:
    try:
        return get_private_library().discard_question_candidate(item_id, candidate_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="拆题候选不存在") from exc
    except PrivateLibraryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/{item_id}/question-candidates/{candidate_id}/import",
    response_model=CandidateImportResult,
)
def import_question_candidate(item_id: str, candidate_id: str) -> CandidateImportResult:
    try:
        library = get_private_library()
        candidate, resource = library.get_question_candidate(item_id, candidate_id)
        if candidate.imported_question_id:
            return CandidateImportResult(
                candidate=candidate,
                question_id=candidate.imported_question_id,
                already_imported=True,
            )
        question_bank = get_library_question_bank()
        question = question_bank.create_private_resource_question(
            candidate.model_dump(), resource=resource.model_dump()
        )
        if resource.file_kind == "image" and not question.images:
            source_path, _ = library.file_for_download(item_id)
            question_bank.add_image(
                question.question_id,
                source_path.read_bytes(),
                resource.original_filename,
                "stem",
                f"来源于私人资料《{resource.title}》的原题图片",
                "拆题时保留的原始题图；请教师确认裁剪范围与题目对应关系。",
                "private_resource_question_pipeline",
            )
        marked = library.mark_candidate_imported(item_id, candidate_id, question.question_id)
        return CandidateImportResult(candidate=marked, question_id=question.question_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="资料或拆题候选不存在") from exc
    except (PrivateLibraryError, QuestionBankError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{item_id}/file")
def download_library_file(item_id: str) -> FileResponse:
    try:
        path, item = get_private_library().file_for_download(item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="私人资料不存在") from exc
    except PrivateLibraryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type=item.mime_type,
        filename=item.original_filename,
        content_disposition_type="inline",
    )


@router.get("/{item_id}/export")
def export_library_text(
    item_id: str, format: Literal["docx", "pdf"] = Query(default="docx")
) -> FileResponse:
    try:
        item = get_private_library().get(item_id)
        rendered = get_library_text_renderer().render(item, format)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="私人资料不存在") from exc
    except LibraryExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FileResponse(rendered.path, media_type=rendered.media_type, filename=rendered.download_name)
