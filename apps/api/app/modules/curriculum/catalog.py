from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

from .schemas import CurriculumNode, CurriculumTreeNode


class CurriculumDataError(ValueError):
    """The curriculum source violates the module invariants."""


class InMemoryCurriculumCatalog:
    """Deep curriculum module with an in-memory adapter used by tests."""

    def __init__(self, nodes: Iterable[CurriculumNode]):
        node_list = list(nodes)
        self._nodes = {node.node_id: node for node in node_list}
        if len(self._nodes) != len(node_list):
            raise CurriculumDataError("Duplicate curriculum node_id")
        self._validate_references()

    def get_node(self, node_id: str) -> CurriculumNode:
        try:
            return self._nodes[node_id]
        except KeyError as exc:
            raise KeyError(f"Unknown curriculum node: {node_id}") from exc

    def get_tree(self) -> CurriculumTreeNode:
        roots = [node for node in self._nodes.values() if node.parent_id is None]
        if len(roots) != 1:
            raise CurriculumDataError(f"Expected exactly one root; got {len(roots)}")

        children_by_parent: dict[str, list[CurriculumNode]] = {}
        for node in self._nodes.values():
            if node.parent_id:
                children_by_parent.setdefault(node.parent_id, []).append(node)

        def build(node: CurriculumNode) -> CurriculumTreeNode:
            children = sorted(children_by_parent.get(node.node_id, []), key=self._sort_key)
            return CurriculumTreeNode(**node.model_dump(), children=[build(child) for child in children])

        return build(roots[0])

    def _validate_references(self) -> None:
        for node in self._nodes.values():
            if node.parent_id and node.parent_id not in self._nodes:
                raise CurriculumDataError(f"Missing parent {node.parent_id} for {node.node_id}")
            missing = [item for item in node.prerequisite_node_ids if item not in self._nodes]
            if missing:
                raise CurriculumDataError(f"Missing prerequisites for {node.node_id}: {missing}")

    @staticmethod
    def _sort_key(node: CurriculumNode) -> tuple[int, ...]:
        parts = []
        for part in node.code.split("."):
            try:
                parts.append(int(part))
            except ValueError:
                parts.append(999)
        return tuple(parts)


class CsvCurriculumCatalog(InMemoryCurriculumCatalog):
    """Production adapter that loads the reviewed curriculum CSV."""

    def __init__(self, path: Path):
        if not path.exists():
            raise CurriculumDataError(f"Curriculum file not found: {path}")
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        super().__init__(self._from_row(row) for row in rows)

    @staticmethod
    def _from_row(row: dict[str, str]) -> CurriculumNode:
        def split(field: str) -> list[str]:
            return [item for item in row.get(field, "").split("|") if item]

        return CurriculumNode(
            node_id=row["node_id"],
            parent_id=row["parent_id"] or None,
            volume=row["volume"],
            node_type=row["node_type"],
            code=row["code"],
            name=row["name"],
            description=row["description"],
            prerequisite_node_ids=split("prerequisite_node_ids"),
            primary_competencies=split("primary_competencies"),
            typical_question_types=split("typical_question_types"),
            common_errors=split("common_errors"),
            gaokao_priority=row["gaokao_priority"],
            status=row["status"],
            reviewed_by=row["reviewed_by"],
        )
