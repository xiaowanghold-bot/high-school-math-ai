from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.config import Settings, get_settings
from app.modules.curriculum import (
    CsvCurriculumCatalog,
    CurriculumNode,
    CurriculumSearchResponse,
    CurriculumTreeNode,
)


router = APIRouter(prefix="/curriculum", tags=["curriculum"])


@lru_cache
def _catalog_for_path(path: str) -> CsvCurriculumCatalog:
    from pathlib import Path

    return CsvCurriculumCatalog(Path(path))


def get_catalog(settings: Settings = Depends(get_settings)) -> CsvCurriculumCatalog:
    return _catalog_for_path(str(settings.curriculum_csv.resolve()))


@router.get("/tree", response_model=CurriculumTreeNode)
def curriculum_tree(catalog: CsvCurriculumCatalog = Depends(get_catalog)) -> CurriculumTreeNode:
    return catalog.get_tree()


@router.get("/search", response_model=CurriculumSearchResponse)
def search_curriculum(
    query: str = Query(default="", max_length=120),
    volume: str | None = Query(default=None, max_length=80),
    node_type: str = Query(default="knowledge_point", max_length=40),
    limit: int = Query(default=30, ge=1, le=100),
    catalog: CsvCurriculumCatalog = Depends(get_catalog),
) -> CurriculumSearchResponse:
    allowed_types = {"volume", "chapter", "section", "knowledge_point"}
    if node_type not in allowed_types:
        raise HTTPException(status_code=422, detail="不支持的教材节点类型")
    matches = catalog.search(
        query,
        volume=volume,
        node_types={node_type},
        limit=None,
    )
    return CurriculumSearchResponse(query=query.strip(), total=len(matches), items=matches[:limit])


@router.get("/nodes/{node_id}", response_model=CurriculumNode)
def curriculum_node(node_id: str, catalog: CsvCurriculumCatalog = Depends(get_catalog)) -> CurriculumNode:
    try:
        return catalog.get_node(node_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
