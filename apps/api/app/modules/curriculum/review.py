from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .catalog import InMemoryCurriculumCatalog
from .schemas import (
    CurriculumNode,
    CurriculumNodePatch,
    CurriculumReviewCommand,
    CurriculumReviewCounts,
    CurriculumReviewDetail,
    CurriculumReviewRecord,
    CurriculumReviewResult,
    CurriculumReviewSummary,
    CurriculumReviewWorkspace,
)


class CurriculumReviewError(ValueError):
    pass


class CurriculumReviewRepository:
    """Append-only SQLite adapter for teacher review decisions."""

    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def latest(self) -> dict[str, CurriculumReviewRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM curriculum_reviews ORDER BY rowid ASC"
            ).fetchall()
        latest: dict[str, CurriculumReviewRecord] = {}
        for row in rows:
            record = self._record(row)
            latest[record.node_id] = record
        return latest

    def history(self, node_id: str) -> list[CurriculumReviewRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM curriculum_reviews WHERE node_id = ? ORDER BY rowid DESC",
                (node_id,),
            ).fetchall()
        return [self._record(row) for row in rows]

    def append_many(self, records: list[CurriculumReviewRecord]) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO curriculum_reviews
                (review_id, node_id, decision, changes_json, note, reviewer_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        record.review_id,
                        record.node_id,
                        record.decision,
                        json.dumps(record.changes.model_dump(exclude_none=True), ensure_ascii=False),
                        record.note,
                        record.reviewer_id,
                        record.created_at,
                    )
                    for record in records
                ],
            )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS curriculum_reviews (
                    review_id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    changes_json TEXT NOT NULL,
                    note TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_curriculum_reviews_node ON curriculum_reviews(node_id)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _record(row: sqlite3.Row) -> CurriculumReviewRecord:
        return CurriculumReviewRecord(
            review_id=row["review_id"],
            node_id=row["node_id"],
            decision=row["decision"],
            changes=CurriculumNodePatch(**json.loads(row["changes_json"])),
            note=row["note"],
            reviewer_id=row["reviewer_id"],
            created_at=row["created_at"],
        )


class ReviewedCurriculumCatalog:
    """Dynamic adapter that overlays the latest teacher decisions on the base catalog."""

    def __init__(
        self,
        base_catalog: InMemoryCurriculumCatalog,
        repository: CurriculumReviewRepository,
    ) -> None:
        self.base_catalog = base_catalog
        self.repository = repository

    def list_nodes(self) -> list[CurriculumNode]:
        latest = self.repository.latest()
        return [self._apply(node, latest.get(node.node_id)) for node in self.base_catalog.list_nodes()]

    def get_node(self, node_id: str) -> CurriculumNode:
        return self._current().get_node(node_id)

    def get_tree(self):
        return self._current().get_tree()

    def search(self, *args, **kwargs):
        return self._current().search(*args, **kwargs)

    def path_for(self, node_id: str) -> dict[str, str]:
        return self._current().path_for(node_id)

    def _current(self) -> InMemoryCurriculumCatalog:
        return InMemoryCurriculumCatalog(self.list_nodes())

    @staticmethod
    def _apply(
        node: CurriculumNode, record: CurriculumReviewRecord | None
    ) -> CurriculumNode:
        if record is None:
            return node.model_copy(deep=True)
        values = node.model_dump()
        changes = record.changes.model_dump(exclude_none=True)
        if record.decision in {"draft", "approved"}:
            values.update(changes)
        values["status"] = {
            "draft": "draft_for_teacher_review",
            "approved": "teacher_approved",
            "changes_requested": "changes_requested",
        }[record.decision]
        values["reviewed_by"] = record.reviewer_id
        return CurriculumNode(**values)


class CurriculumGovernance:
    """Deep module for inspecting and recording curriculum review decisions."""

    def __init__(
        self,
        *,
        base_catalog: InMemoryCurriculumCatalog,
        repository: CurriculumReviewRepository,
    ) -> None:
        self.base_catalog = base_catalog
        self.repository = repository
        self.catalog = ReviewedCurriculumCatalog(base_catalog, repository)

    def workspace(
        self,
        *,
        volume: str | None = None,
        query: str = "",
        review_status: str | None = None,
        node_type: str | None = None,
        limit: int = 500,
    ) -> CurriculumReviewWorkspace:
        latest = self.repository.latest()
        effective = {node.node_id: node for node in self.catalog.list_nodes()}
        children = self._children()
        scoped = [
            node
            for node in self.base_catalog.list_nodes()
            if (not volume or node.volume == volume)
        ]
        counts = CurriculumReviewCounts(total=len(scoped))
        summaries: list[CurriculumReviewSummary] = []
        normalized_query = self._normalize(query)
        volume_node_id = next(
            (
                node.node_id
                for node in scoped
                if node.node_type == "volume" and node.name == volume
            ),
            None,
        )
        for base in scoped:
            record = latest.get(base.node_id)
            status = record.decision if record else "pending"
            setattr(counts, status, getattr(counts, status) + 1)
            current = effective[base.node_id]
            if review_status and status != review_status:
                continue
            if node_type and current.node_type != node_type:
                continue
            searchable = self._normalize(
                f"{current.code} {current.name} {current.description} {current.volume}"
            )
            if normalized_query and normalized_query not in searchable:
                continue
            summaries.append(
                CurriculumReviewSummary(
                    node_id=current.node_id,
                    parent_id=current.parent_id,
                    volume=current.volume,
                    node_type=current.node_type,
                    code=current.code,
                    name=current.name,
                    description=current.description,
                    review_status=status,
                    latest_reviewed_at=record.created_at if record else None,
                    descendant_count=len(self._descendants(current.node_id, children)),
                )
            )
        return CurriculumReviewWorkspace(
            volume=volume,
            volume_node_id=volume_node_id,
            counts=counts,
            items=summaries[:limit],
        )

    def inspect(self, node_id: str) -> CurriculumReviewDetail:
        base = self.base_catalog.get_node(node_id)
        history = self.repository.history(node_id)
        return CurriculumReviewDetail(
            base_node=base,
            effective_node=self.catalog.get_node(node_id),
            review_status=history[0].decision if history else "pending",
            descendant_count=len(self._descendants(node_id, self._children())),
            history=history,
        )

    def submit(
        self, node_id: str, command: CurriculumReviewCommand
    ) -> CurriculumReviewResult:
        node = self.base_catalog.get_node(node_id)
        if command.decision == "changes_requested" and not command.note.strip():
            raise CurriculumReviewError("退回修改时必须填写审核意见")
        if command.cascade and node.node_type == "knowledge_point":
            raise CurriculumReviewError("知识点没有下级节点，不能使用级联审核")
        target_ids = [node_id]
        if command.cascade:
            target_ids.extend(self._descendants(node_id, self._children()))
        now = datetime.now(timezone.utc).isoformat()
        records = []
        for target_id in target_ids:
            records.append(
                CurriculumReviewRecord(
                    review_id=f"curriculum-review-{uuid4().hex}",
                    node_id=target_id,
                    decision=command.decision,
                    changes=command.changes if target_id == node_id else CurriculumNodePatch(),
                    note=command.note.strip(),
                    reviewer_id=command.reviewer_id,
                    created_at=now,
                )
            )
        self.repository.append_many(records)
        action = {
            "draft": "草稿已保存",
            "approved": "目录节点已批准",
            "changes_requested": "目录节点已退回修改",
        }[command.decision]
        return CurriculumReviewResult(
            detail=self.inspect(node_id),
            affected_count=len(records),
            message=f"{action}，共影响 {len(records)} 个节点。",
        )

    def _children(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for node in self.base_catalog.list_nodes():
            if node.parent_id:
                result.setdefault(node.parent_id, []).append(node.node_id)
        return result

    @staticmethod
    def _descendants(node_id: str, children: dict[str, list[str]]) -> list[str]:
        result: list[str] = []
        pending = list(children.get(node_id, []))
        while pending:
            current = pending.pop(0)
            result.append(current)
            pending.extend(children.get(current, []))
        return result

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.lower())
