from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.modules.exam_exports import ExamPaperDocumentRenderer, ExamPaperExportError
from app.modules.exam_papers import (
    ExamPaperComposer,
    ExamPaperComposeCommand,
    ExamPaperComposeError,
    ExamPaperCreateCommand,
    ExamPaperEdition,
    ExamPaperExportFormat,
    ExamPaperList,
    ExamPaperProposal,
    ExamPaperStudio,
    ExamPaperStudioError,
    ExamPaperTemplateCatalog,
    ExamPaperTemplateComposeCommand,
    ExamPaperTemplateError,
    ExamPaperTemplateList,
    ExamPaperUpdateCommand,
    ExamPaperView,
)
from app.routes.questions import get_question_bank


router = APIRouter(prefix="/exam-papers", tags=["exam-papers"])


@lru_cache
def get_exam_paper_studio() -> ExamPaperStudio:
    settings = get_settings()
    return ExamPaperStudio(
        database_path=settings.exam_paper_db,
        asset_root=settings.exam_paper_asset_dir,
        question_bank=get_question_bank(),
    )


@lru_cache
def get_exam_paper_composer() -> ExamPaperComposer:
    return ExamPaperComposer(
        question_bank=get_question_bank(),
        template_catalog=get_exam_paper_template_catalog(),
    )


@lru_cache
def get_exam_paper_template_catalog() -> ExamPaperTemplateCatalog:
    return ExamPaperTemplateCatalog()


@lru_cache
def get_exam_paper_renderer() -> ExamPaperDocumentRenderer:
    settings = get_settings()
    return ExamPaperDocumentRenderer(
        output_root=settings.lesson_export_dir,
        asset_root=settings.exam_paper_asset_dir,
        cjk_font_regular=settings.cjk_font_regular,
        cjk_font_bold=settings.cjk_font_bold,
    )


@router.get("", response_model=ExamPaperList)
def list_exam_papers(limit: int = Query(default=30, ge=1, le=100)) -> ExamPaperList:
    return get_exam_paper_studio().list(limit=limit)


@router.post("", response_model=ExamPaperView, status_code=201)
def create_exam_paper(command: ExamPaperCreateCommand) -> ExamPaperView:
    try:
        return get_exam_paper_studio().create(command)
    except ExamPaperStudioError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/compose", response_model=ExamPaperProposal)
def compose_exam_paper(command: ExamPaperComposeCommand) -> ExamPaperProposal:
    try:
        return get_exam_paper_composer().compose(command)
    except ExamPaperComposeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/templates", response_model=ExamPaperTemplateList)
def list_exam_paper_templates() -> ExamPaperTemplateList:
    return get_exam_paper_template_catalog().list()


@router.post("/compose-template", response_model=ExamPaperProposal)
def compose_exam_paper_template(
    command: ExamPaperTemplateComposeCommand,
) -> ExamPaperProposal:
    try:
        return get_exam_paper_composer().compose_template(command)
    except (ExamPaperComposeError, ExamPaperTemplateError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{paper_id}", response_model=ExamPaperView)
def get_exam_paper(paper_id: str) -> ExamPaperView:
    try:
        return get_exam_paper_studio().get(paper_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="试卷不存在") from exc


@router.put("/{paper_id}", response_model=ExamPaperView)
def update_exam_paper(
    paper_id: str, command: ExamPaperUpdateCommand
) -> ExamPaperView:
    try:
        return get_exam_paper_studio().update(paper_id, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="试卷不存在") from exc
    except ExamPaperStudioError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{paper_id}/export")
def export_exam_paper(
    paper_id: str,
    format: ExamPaperExportFormat = Query(default="docx"),
    edition: ExamPaperEdition = Query(default="student"),
) -> FileResponse:
    try:
        paper = get_exam_paper_studio().get(paper_id)
        rendered = get_exam_paper_renderer().render(paper, format, edition)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="试卷不存在") from exc
    except ExamPaperExportError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FileResponse(
        path=rendered.path,
        media_type=rendered.media_type,
        filename=rendered.download_name,
    )
