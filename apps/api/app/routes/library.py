from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.modules.private_library import (
    LibraryIngestCommand,
    LibraryItemList,
    LibraryItemView,
    LibraryStats,
    LibraryTextReviewCommand,
    PrivateLibrary,
    PrivateLibraryError,
    RightsBasis,
)


router = APIRouter(prefix="/library", tags=["private-library"])


@lru_cache
def get_private_library() -> PrivateLibrary:
    settings = get_settings()
    return PrivateLibrary(settings.private_library_db, settings.private_library_dir)


@router.get("", response_model=LibraryItemList)
def list_library_items(limit: int = Query(default=50, ge=1, le=100)) -> LibraryItemList:
    return get_private_library().list(limit=limit)


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


@router.get("/{item_id}/file")
def download_library_file(item_id: str) -> FileResponse:
    try:
        path, item = get_private_library().file_for_download(item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="私人资料不存在") from exc
    except PrivateLibraryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FileResponse(path, media_type=item.mime_type, filename=item.original_filename)
