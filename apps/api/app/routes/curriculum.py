from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import Settings, get_settings
from app.modules.curriculum import CsvCurriculumCatalog, CurriculumNode, CurriculumTreeNode


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


@router.get("/nodes/{node_id}", response_model=CurriculumNode)
def curriculum_node(node_id: str, catalog: CsvCurriculumCatalog = Depends(get_catalog)) -> CurriculumNode:
    try:
        return catalog.get_node(node_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
