from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.config import Settings, get_settings
from app.modules.curriculum import (
    CsvCurriculumCatalog,
    CurriculumGovernance,
    CurriculumNode,
    CurriculumReviewCommand,
    CurriculumReviewDetail,
    CurriculumReviewError,
    CurriculumReviewRepository,
    CurriculumReviewResult,
    CurriculumReviewWorkspace,
    CurriculumSearchResponse,
    CurriculumTreeNode,
    ReviewedCurriculumCatalog,
)


router = APIRouter(prefix="/curriculum", tags=["curriculum"])


@lru_cache
def _governance_for_paths(csv_path: str, review_db_path: str) -> CurriculumGovernance:
    base_catalog = CsvCurriculumCatalog(Path(csv_path))
    repository = CurriculumReviewRepository(Path(review_db_path))
    return CurriculumGovernance(base_catalog=base_catalog, repository=repository)


def get_governance(settings: Settings = Depends(get_settings)) -> CurriculumGovernance:
    return _governance_for_paths(
        str(settings.curriculum_csv.resolve()),
        str(settings.curriculum_review_db.resolve()),
    )


def get_catalog(
    governance: CurriculumGovernance = Depends(get_governance),
) -> ReviewedCurriculumCatalog:
    return governance.catalog


@router.get("/tree", response_model=CurriculumTreeNode)
def curriculum_tree(catalog: ReviewedCurriculumCatalog = Depends(get_catalog)) -> CurriculumTreeNode:
    return catalog.get_tree()


@router.get("/search", response_model=CurriculumSearchResponse)
def search_curriculum(
    query: str = Query(default="", max_length=120),
    volume: str | None = Query(default=None, max_length=80),
    node_type: str = Query(default="knowledge_point", max_length=40),
    limit: int = Query(default=30, ge=1, le=100),
    catalog: ReviewedCurriculumCatalog = Depends(get_catalog),
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


@router.get("/reviews", response_model=CurriculumReviewWorkspace)
def curriculum_review_workspace(
    volume: str | None = Query(default=None, max_length=80),
    query: str = Query(default="", max_length=120),
    review_status: Literal["pending", "draft", "approved", "changes_requested"] | None = None,
    node_type: Literal["textbook", "volume", "chapter", "section", "knowledge_point"] | None = None,
    limit: int = Query(default=500, ge=1, le=1000),
    governance: CurriculumGovernance = Depends(get_governance),
) -> CurriculumReviewWorkspace:
    return governance.workspace(
        volume=volume,
        query=query,
        review_status=review_status,
        node_type=node_type,
        limit=limit,
    )


@router.get("/reviews/{node_id}", response_model=CurriculumReviewDetail)
def curriculum_review_detail(
    node_id: str,
    governance: CurriculumGovernance = Depends(get_governance),
) -> CurriculumReviewDetail:
    try:
        return governance.inspect(node_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="教材节点不存在") from exc


@router.post("/reviews/{node_id}", response_model=CurriculumReviewResult)
def submit_curriculum_review(
    node_id: str,
    command: CurriculumReviewCommand,
    governance: CurriculumGovernance = Depends(get_governance),
) -> CurriculumReviewResult:
    try:
        return governance.submit(node_id, command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="教材节点不存在") from exc
    except CurriculumReviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/nodes/{node_id}", response_model=CurriculumNode)
def curriculum_node(node_id: str, catalog: ReviewedCurriculumCatalog = Depends(get_catalog)) -> CurriculumNode:
    try:
        return catalog.get_node(node_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
