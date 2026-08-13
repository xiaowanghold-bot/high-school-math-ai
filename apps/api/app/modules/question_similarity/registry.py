from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

from app.modules.question_bank import QuestionBank
from app.modules.question_bank.schemas import QuestionDetail
from app.modules.question_similarity.schemas import (
    DuplicateCandidate,
    DuplicateRelation,
    DuplicateReviewCommand,
    DuplicateReviewResult,
    DuplicateScanResult,
    DuplicateWorkspace,
    DuplicateWorkspaceStats,
)


class QuestionSimilarityError(ValueError):
    pass


_SOURCE_PREFIX = re.compile(
    r"^\s*(?:\d{1,3}\s*[.、)]?\s*)?[（(][^()（）]{0,120}"
    r"(?:20\d{2}|高[一二三]|模拟|联考|月考|期中|期末)[^()（）]{0,120}[)）]\s*"
)
_LEADING_NUMBER = re.compile(r"^\s*\d{1,3}\s*[.、]\s*")
_NUMBER = re.compile(r"(?<![a-z])[-+]?\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?")
_NON_CONTENT = re.compile(r"[\s,，。；;：:、！？!?‘’“”\"'`·]")


def _plain(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).lower()


def _without_source_prefix(value: Any) -> str:
    text = _plain(value)
    previous = None
    while text != previous:
        previous = text
        text = _SOURCE_PREFIX.sub("", text, count=1)
        text = _LEADING_NUMBER.sub("", text, count=1)
    return text.strip()


def _normalize(value: Any) -> str:
    text = _without_source_prefix(value)
    for token in (r"\left", r"\right", "$", "\\(", "\\)", "\\[", "\\]"):
        text = text.replace(token, "")
    text = text.replace("−", "-").replace("×", "*").replace("÷", "/")
    return _NON_CONTENT.sub("", text)


def _skeleton(value: Any) -> str:
    return _NUMBER.sub("#", _normalize(value))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ngrams(value: str, size: int = 5) -> set[str]:
    if len(value) <= size:
        return {value} if value else set()
    return {value[index : index + size] for index in range(len(value) - size + 1)}


def _ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def _raw_parts(question: QuestionDetail) -> tuple[str, str, str, str]:
    raw = question.raw or {}
    options = "|".join(
        f"{item.get('key', '')}:{item.get('plain_text') or item.get('text') or item.get('latex') or ''}"
        for item in raw.get("options") or []
        if isinstance(item, dict)
    )
    solutions = raw.get("solutions") or []
    solution_text = "|".join(
        " ".join(
            [
                str(item.get("method") or ""),
                *[str(step) for step in item.get("steps_latex") or []],
                str(item.get("final_answer") or ""),
            ]
        )
        for item in solutions
        if isinstance(item, dict)
    )
    core = _normalize(f"{question.stem_plain}|{options}")
    return core, _skeleton(f"{question.stem_plain}|{options}"), _normalize(question.answer_value), _normalize(solution_text)


class QuestionSimilarityRegistry:
    """Persistent candidate registry; it never mutates, merges, or deletes questions."""

    def __init__(self, database_path: Path, *, question_bank: QuestionBank) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.question_bank = question_bank
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS duplicate_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    left_question_id TEXT NOT NULL,
                    right_question_id TEXT NOT NULL,
                    left_signature TEXT NOT NULL,
                    right_signature TEXT NOT NULL,
                    suggested_relation TEXT NOT NULL,
                    teacher_relation TEXT,
                    confidence REAL NOT NULL,
                    signals_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reviewer_id TEXT,
                    review_note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_duplicate_pair
                    ON duplicate_candidates(left_question_id, right_question_id, status);
                CREATE INDEX IF NOT EXISTS idx_duplicate_status
                    ON duplicate_candidates(status, confidence DESC);
                CREATE TABLE IF NOT EXISTS duplicate_reviews (
                    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    note TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL,
                    FOREIGN KEY(candidate_id) REFERENCES duplicate_candidates(candidate_id)
                );
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def scan(self) -> DuplicateScanResult:
        page = self.question_bank.search(page=1, page_size=100_000)
        questions = [
            self.question_bank.get_question(item.question_id)
            for item in page.items
            if item.status != "rejected"
        ]
        prepared = {question.question_id: (*_raw_parts(question), question) for question in questions}
        candidate_pairs = self._candidate_pairs(prepared)
        now = self._now()
        new_candidates = 0
        stale_candidates = 0
        active_ids: set[str] = set()

        with self._connect() as connection:
            for left_id, right_id in sorted(candidate_pairs):
                left_core, left_skeleton, left_answer, left_solution, left = prepared[left_id]
                right_core, right_skeleton, right_answer, right_solution, right = prepared[right_id]
                classified = self._classify(
                    left,
                    right,
                    left_core=left_core,
                    right_core=right_core,
                    left_skeleton=left_skeleton,
                    right_skeleton=right_skeleton,
                    left_answer=left_answer,
                    right_answer=right_answer,
                    left_solution=left_solution,
                    right_solution=right_solution,
                )
                if classified is None:
                    continue
                relation, confidence, signals = classified
                left_signature = _digest("|".join((left_core, left_answer, left_solution)))
                right_signature = _digest("|".join((right_core, right_answer, right_solution)))
                candidate_id = "dup_" + _digest(
                    "|".join((left_id, right_id, left_signature, right_signature))
                )[:20]
                active_ids.add(candidate_id)
                stale_candidates += connection.execute(
                    """
                    UPDATE duplicate_candidates SET status = 'stale', updated_at = ?
                    WHERE left_question_id = ? AND right_question_id = ?
                      AND candidate_id != ? AND status != 'stale'
                    """,
                    (now, left_id, right_id, candidate_id),
                ).rowcount
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO duplicate_candidates
                    (candidate_id, left_question_id, right_question_id, left_signature,
                     right_signature, suggested_relation, confidence, signals_json,
                     status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?)
                    """,
                    (
                        candidate_id,
                        left_id,
                        right_id,
                        left_signature,
                        right_signature,
                        relation,
                        confidence,
                        json.dumps(signals, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                new_candidates += cursor.rowcount

            active_rows = connection.execute(
                "SELECT candidate_id FROM duplicate_candidates WHERE status != 'stale'"
            ).fetchall()
            obsolete_ids = [row["candidate_id"] for row in active_rows if row["candidate_id"] not in active_ids]
            if obsolete_ids:
                placeholders = ",".join("?" for _ in obsolete_ids)
                stale_candidates += connection.execute(
                    f"UPDATE duplicate_candidates SET status = 'stale', updated_at = ? WHERE candidate_id IN ({placeholders})",
                    (now, *obsolete_ids),
                ).rowcount

        workspace = self.workspace()
        return DuplicateScanResult(
            scanned_questions=len(questions),
            compared_pairs=len(candidate_pairs),
            active_candidates=workspace.stats.proposed + workspace.stats.confirmed + workspace.stats.rejected,
            new_candidates=new_candidates,
            stale_candidates=stale_candidates,
            workspace=workspace,
        )

    def workspace(
        self,
        *,
        status: str | None = None,
        relation: str | None = None,
        limit: int = 200,
    ) -> DuplicateWorkspace:
        clauses: list[str] = []
        values: list[Any] = []
        if status:
            clauses.append("status = ?")
            values.append(status)
        if relation:
            clauses.append("COALESCE(teacher_relation, suggested_relation) = ?")
            values.append(relation)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM duplicate_candidates {where}
                ORDER BY CASE status WHEN 'proposed' THEN 0 WHEN 'confirmed' THEN 1
                                     WHEN 'rejected' THEN 2 ELSE 3 END,
                         confidence DESC, updated_at DESC LIMIT ?
                """,
                (*values, max(1, min(limit, 1000))),
            ).fetchall()
            all_rows = connection.execute("SELECT status, suggested_relation, teacher_relation FROM duplicate_candidates").fetchall()
        items: list[DuplicateCandidate] = []
        for row in rows:
            try:
                items.append(self._view(row))
            except KeyError:
                continue
        return DuplicateWorkspace(items=items, stats=self._stats(all_rows))

    def review(self, candidate_id: str, command: DuplicateReviewCommand) -> DuplicateReviewResult:
        now = self._now()
        status = "rejected" if command.relation == "not_duplicate" else "confirmed"
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM duplicate_candidates WHERE candidate_id = ?", (candidate_id,)
            ).fetchone()
            if row is None:
                raise KeyError(candidate_id)
            if row["status"] == "stale":
                raise QuestionSimilarityError("题目内容已变化，请重新扫描后再确认关系")
            connection.execute(
                """
                UPDATE duplicate_candidates SET teacher_relation = ?, status = ?,
                    reviewer_id = ?, review_note = ?, updated_at = ?
                WHERE candidate_id = ?
                """,
                (command.relation, status, command.reviewer_id, command.note, now, candidate_id),
            )
            connection.execute(
                """
                INSERT INTO duplicate_reviews
                (candidate_id, relation, reviewer_id, note, reviewed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (candidate_id, command.relation, command.reviewer_id, command.note, now),
            )
            updated = connection.execute(
                "SELECT * FROM duplicate_candidates WHERE candidate_id = ?", (candidate_id,)
            ).fetchone()
        label = "已排除重复关系" if status == "rejected" else "已保存教师确认关系"
        return DuplicateReviewResult(candidate=self._view(updated), message=label)

    def _view(self, row: sqlite3.Row) -> DuplicateCandidate:
        return DuplicateCandidate(
            candidate_id=row["candidate_id"],
            left=self.question_bank.get_question(row["left_question_id"]),
            right=self.question_bank.get_question(row["right_question_id"]),
            suggested_relation=row["suggested_relation"],
            teacher_relation=row["teacher_relation"],
            confidence=row["confidence"],
            signals=json.loads(row["signals_json"]),
            status=row["status"],
            reviewer_id=row["reviewer_id"],
            review_note=row["review_note"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _stats(rows: Iterable[sqlite3.Row]) -> DuplicateWorkspaceStats:
        rows = list(rows)
        status_counts = Counter(row["status"] for row in rows)
        relations = [row["teacher_relation"] or row["suggested_relation"] for row in rows if row["status"] != "stale"]
        return DuplicateWorkspaceStats(
            total=len(rows),
            proposed=status_counts["proposed"],
            confirmed=status_counts["confirmed"],
            rejected=status_counts["rejected"],
            stale=status_counts["stale"],
            exact_duplicate=relations.count("exact_duplicate"),
            same_problem=sum(value in {"same_problem_different_source", "same_problem_different_solution"} for value in relations),
            variant=relations.count("variant"),
        )

    @staticmethod
    def _candidate_pairs(prepared: dict[str, tuple[str, str, str, str, QuestionDetail]]) -> set[tuple[str, str]]:
        exact_groups: dict[str, list[str]] = defaultdict(list)
        skeleton_groups: dict[str, list[str]] = defaultdict(list)
        gram_index: dict[str, list[str]] = defaultdict(list)
        pairs: set[tuple[str, str]] = set()
        for question_id, (core, skeleton, _answer, _solution, question) in prepared.items():
            exact_groups[core].append(question_id)
            skeleton_groups[skeleton].append(question_id)
            for gram in _ngrams(skeleton):
                gram_index[gram].append(question_id)
            provenance = question.raw.get("provenance") or {}
            derived_ids = list(provenance.get("derived_from_question_ids") or [])
            source = question.raw.get("source") or {}
            if source.get("derived_from_question_id"):
                derived_ids.append(source["derived_from_question_id"])
            for source_id in derived_ids:
                if source_id in prepared and source_id != question_id:
                    pairs.add(tuple(sorted((question_id, source_id))))
        for groups in (exact_groups, skeleton_groups):
            for ids in groups.values():
                if len(ids) > 1:
                    pairs.update(tuple(sorted(pair)) for pair in combinations(sorted(ids), 2))
        shared: Counter[tuple[str, str]] = Counter()
        max_frequency = max(12, min(60, len(prepared) // 30 or 12))
        for ids in gram_index.values():
            unique_ids = sorted(set(ids))
            if 1 < len(unique_ids) <= max_frequency:
                shared.update(tuple(pair) for pair in combinations(unique_ids, 2))
        pairs.update(pair for pair, count in shared.items() if count >= 3)
        return pairs

    @staticmethod
    def _classify(
        left: QuestionDetail,
        right: QuestionDetail,
        *,
        left_core: str,
        right_core: str,
        left_skeleton: str,
        right_skeleton: str,
        left_answer: str,
        right_answer: str,
        left_solution: str,
        right_solution: str,
    ) -> tuple[DuplicateRelation, float, list[str]] | None:
        if not left_core or not right_core:
            return None
        same_core = left_core == right_core
        same_answer = bool(left_answer and left_answer == right_answer)
        same_solution = bool(left_solution and left_solution == right_solution)
        same_source = _normalize(left.source_document) == _normalize(right.source_document)
        signals: list[str] = []
        left_provenance = left.raw.get("provenance") or {}
        right_provenance = right.raw.get("provenance") or {}
        left_parents = set(left_provenance.get("derived_from_question_ids") or [])
        right_parents = set(right_provenance.get("derived_from_question_ids") or [])
        if right.question_id in left_parents or left.question_id in right_parents:
            return "variant", 0.99, ["题库生成记录明确标记了母题与派生题关系", "两道题均保留为独立题目"]
        if same_core:
            signals.append("去除题号与来源前缀后，题干和选项一致")
            if same_answer:
                signals.append("答案一致")
            elif left_answer or right_answer:
                signals.append("答案存在差异，需教师重点复核")
            if same_solution:
                signals.append("解析内容一致")
            if same_source:
                signals.append("来源记录一致")
        if same_core and same_answer and same_solution and same_source:
            return "exact_duplicate", 0.99, signals
        if same_core and left_solution and right_solution and not same_solution:
            signals.append("解析步骤不同")
            return "same_problem_different_solution", 0.97 if same_answer else 0.93, signals
        if same_core:
            if not same_source:
                signals.append("来源记录不同")
            return "same_problem_different_source", 0.98 if same_answer else 0.94, signals

        skeleton_ratio = _ratio(left_skeleton, right_skeleton)
        core_ratio = _ratio(left_core, right_core)
        knowledge_overlap = bool(set(left.knowledge_point_ids) & set(right.knowledge_point_ids))
        same_chapter = bool(left.chapter and left.chapter == right.chapter)
        if left_skeleton == right_skeleton:
            signals.extend(["题目结构一致", "仅数字或参数发生变化"])
            return "variant", 0.96, signals
        if skeleton_ratio >= 0.90 and core_ratio >= 0.76 and (knowledge_overlap or same_chapter):
            signals.append(f"结构相似度 {round(skeleton_ratio * 100)}%")
            signals.append("知识点相同" if knowledge_overlap else "教材章节相同")
            return "variant", round(min(0.95, 0.68 + skeleton_ratio * 0.25), 4), signals
        return None
