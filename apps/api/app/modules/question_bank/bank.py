from __future__ import annotations

import json
import shutil
import sqlite3
from collections import Counter
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from app.modules.math_verifier import MathVerifier
from app.modules.question_bank.schemas import (
    CurationResult,
    ImportBatchView,
    ImportResult,
    PublishDecision,
    QuestionBankStats,
    QuestionDetail,
    QuestionImage,
    QuestionImageMetadataCommand,
    QuestionLibraryStateCommand,
    QuestionLibraryStateResult,
    QuestionRevisionCommand,
    QuestionRevisionResult,
    QuestionSearchPage,
    QuestionSummary,
    ReviewCommand,
    ReviewResult,
)


class QuestionBankError(ValueError):
    pass


MODULE_RULES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "sets_logic": (("集合", "逻辑用语", "充要条件"), ()),
    "trigonometry": (("三角函数", "解三角形"), ()),
    "sequences": (("数列",), ()),
    "vectors": (("向量",), ()),
    "solid_geometry": (("立体几何", "空间几何"), ()),
    "analytic_geometry": (("直线与圆", "圆锥曲线", "解析几何"), ()),
    "counting": (("计数原理", "排列", "组合", "二项式"), ()),
    "statistics_probability": (("统计", "概率", "随机变量", "成对数据", "线性回归"), ()),
    "functions_derivatives": (("函数", "导数"), ("三角函数",)),
}

WORK_QUEUE_KEYS = {
    "teacher_review",
    "verified_pending_teacher",
    "formula_review",
    "math_review",
    "source_conflict",
    "changes_requested",
    "publishable",
}


class QuestionBank:
    """Deep module for importing, reviewing, searching and publishing questions.

    SQLite and the source JSON shape stay behind this interface. Callers never
    write tables or derive publication rights themselves.
    """

    MAX_IMAGE_BYTES = 8 * 1024 * 1024
    MAX_IMAGES_PER_QUESTION = 8
    MAX_IMAGE_PIXELS = 25_000_000
    IMAGE_FORMATS = {
        "PNG": ("image/png", ".png"),
        "JPEG": ("image/jpeg", ".jpg"),
        "WEBP": ("image/webp", ".webp"),
    }

    def __init__(self, database_path: Path, media_root: Path | None = None) -> None:
        self.database_path = database_path
        self.media_root = (media_root or database_path.parent / "question-media").resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.media_root.mkdir(parents=True, exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS import_batches (
                    batch_id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    source_file TEXT NOT NULL,
                    publication_status TEXT NOT NULL,
                    declared_count INTEGER NOT NULL,
                    rights_basis TEXT NOT NULL,
                    imported_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS questions (
                    question_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL REFERENCES import_batches(batch_id),
                    status TEXT NOT NULL,
                    review_status TEXT NOT NULL DEFAULT 'pending',
                    visibility TEXT NOT NULL,
                    question_type TEXT NOT NULL,
                    stem_plain TEXT NOT NULL,
                    stem_latex TEXT,
                    answer_value TEXT,
                    volume TEXT,
                    chapter TEXT,
                    section TEXT,
                    knowledge_point_ids TEXT NOT NULL,
                    difficulty INTEGER NOT NULL,
                    verification_status TEXT NOT NULL,
                    source_document TEXT NOT NULL,
                    source_page_start INTEGER,
                    source_page_end INTEGER,
                    license_status TEXT NOT NULL,
                    attribution_required TEXT,
                    solution_approved INTEGER NOT NULL DEFAULT 0,
                    raw_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS question_reviews (
                    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question_id TEXT NOT NULL REFERENCES questions(question_id),
                    reviewer_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    note TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS question_revisions (
                    revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    package_id TEXT NOT NULL,
                    question_id TEXT NOT NULL REFERENCES questions(question_id),
                    previous_raw_json TEXT NOT NULL,
                    revised_raw_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(package_id, question_id)
                );

                CREATE TABLE IF NOT EXISTS verification_reports (
                    report_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    package_id TEXT NOT NULL,
                    question_id TEXT NOT NULL REFERENCES questions(question_id),
                    status TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(package_id, question_id)
                );

                CREATE TABLE IF NOT EXISTS question_images (
                    image_id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES questions(question_id),
                    placement TEXT NOT NULL CHECK (placement IN ('stem', 'solution')),
                    original_filename TEXT NOT NULL,
                    stored_filename TEXT NOT NULL UNIQUE,
                    mime_type TEXT NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    alt_text TEXT NOT NULL,
                    caption TEXT NOT NULL,
                    sort_order INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS question_image_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    image_id TEXT NOT NULL,
                    question_id TEXT NOT NULL REFERENCES questions(question_id),
                    action TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS question_generation_runs (
                    run_id TEXT PRIMARY KEY,
                    source_question_id TEXT NOT NULL REFERENCES questions(question_id),
                    output_question_id TEXT NOT NULL REFERENCES questions(question_id),
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    output_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_questions_chapter ON questions(chapter);
                CREATE INDEX IF NOT EXISTS idx_questions_review ON questions(review_status);
                CREATE INDEX IF NOT EXISTS idx_questions_verification ON questions(verification_status);
                CREATE INDEX IF NOT EXISTS idx_question_images_question ON question_images(question_id, placement, sort_order);
                CREATE INDEX IF NOT EXISTS idx_question_generation_source ON question_generation_runs(source_question_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS question_library_state (
                    question_id TEXT PRIMARY KEY REFERENCES questions(question_id),
                    state TEXT NOT NULL CHECK (state IN ('active', 'removed')),
                    reason TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    relation_candidate_id TEXT,
                    removed_at TEXT,
                    restored_at TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS question_library_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question_id TEXT NOT NULL REFERENCES questions(question_id),
                    action TEXT NOT NULL CHECK (action IN ('remove', 'restore')),
                    actor_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    relation_candidate_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_question_library_state
                    ON question_library_state(state, updated_at DESC);
                """
            )
            # Older prototypes allowed an approval before verification. Preserve
            # the audit row, but repair the derived state so it cannot bypass the
            # current invariant.
            connection.execute(
                """
                UPDATE questions
                SET review_status = 'pending', solution_approved = 0
                WHERE review_status = 'approved'
                  AND verification_status != 'passed'
                  AND status != 'published'
                """
            )

    def import_batch(self, source_file: Path) -> ImportResult:
        try:
            payload = json.loads(source_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise QuestionBankError(f"批次文件无法读取：{exc}") from exc

        questions = self._validate_batch(payload)
        batch_id = payload["batch_id"]
        imported_at = self._now()
        created = 0
        skipped = 0
        rights_basis = payload.get("rights_boundary", {}).get("basis", "")

        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO import_batches
                (batch_id, schema_version, source_file, publication_status,
                 declared_count, rights_basis, imported_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    str(payload.get("schema_version", "unknown")),
                    str(source_file.resolve()),
                    str(payload.get("publication_status", "private_not_publishable")),
                    len(questions),
                    rights_basis,
                    imported_at,
                ),
            )
            for question in questions:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO questions (
                        question_id, batch_id, status, visibility, question_type,
                        stem_plain, stem_latex, answer_value, volume, chapter, section,
                        knowledge_point_ids, difficulty, verification_status,
                        source_document, source_page_start, source_page_end,
                        license_status, attribution_required, solution_approved,
                        raw_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._question_row(batch_id, question, imported_at),
                )
                if cursor.rowcount == 1:
                    created += 1
                else:
                    skipped += 1

        return ImportResult(
            batch_id=batch_id,
            declared_count=len(questions),
            created_count=created,
            skipped_count=skipped,
        )

    def apply_curation_package(self, source_file: Path, verifier: MathVerifier) -> CurationResult:
        try:
            payload = json.loads(source_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise QuestionBankError(f"校正包无法读取：{exc}") from exc
        package_id = payload.get("package_id")
        candidates = payload.get("candidates")
        if not package_id or not isinstance(candidates, list):
            raise QuestionBankError("校正包缺少 package_id 或 candidates")

        applied = skipped = passed = inconsistent = 0
        now = self._now()
        with self._connect() as connection:
            for candidate in candidates:
                question_id = candidate.get("question_id")
                if not question_id:
                    raise QuestionBankError("校正候选缺少 question_id")
                if connection.execute(
                    "SELECT 1 FROM question_revisions WHERE package_id = ? AND question_id = ?",
                    (package_id, question_id),
                ).fetchone():
                    skipped += 1
                    continue
                row = connection.execute(
                    "SELECT * FROM questions WHERE question_id = ?", (question_id,)
                ).fetchone()
                if row is None:
                    raise QuestionBankError(f"校正候选对应题目不存在：{question_id}")

                report = verifier.verify(candidate)
                raw = json.loads(row["raw_json"])
                previous_raw = row["raw_json"]
                raw["stem"] = candidate["stem"]
                raw["options"] = candidate["options"]
                raw["solutions"] = [candidate["solution"]]
                raw["verification"] = report.model_dump()
                raw.setdefault("source", {}).update(candidate["source"])
                raw["curation"] = {
                    "package_id": package_id,
                    "disposition": candidate["disposition"],
                    "adaptation_candidate": candidate.get("adaptation_candidate"),
                }
                revised_raw = json.dumps(raw, ensure_ascii=False)
                status = "verified" if report.status == "passed" else "rejected"
                connection.execute(
                    """
                    INSERT INTO question_revisions
                    (package_id, question_id, previous_raw_json, revised_raw_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (package_id, question_id, previous_raw, revised_raw, now),
                )
                connection.execute(
                    """
                    INSERT INTO verification_reports
                    (package_id, question_id, status, report_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (package_id, question_id, report.status, report.model_dump_json(), now),
                )
                connection.execute(
                    """
                    UPDATE questions SET
                        status = ?, review_status = 'pending', stem_plain = ?, stem_latex = ?,
                        verification_status = ?, attribution_required = ?, solution_approved = 0,
                        raw_json = ?, updated_at = ?
                    WHERE question_id = ?
                    """,
                    (
                        status,
                        candidate["stem"]["plain_text"],
                        candidate["stem"]["latex"],
                        report.status,
                        candidate["source"].get("attribution_required", "confirmed"),
                        revised_raw,
                        now,
                        question_id,
                    ),
                )
                applied += 1
                if report.status == "passed":
                    passed += 1
                else:
                    inconsistent += 1

        return CurationResult(
            package_id=package_id,
            candidate_count=len(candidates),
            applied_count=applied,
            skipped_count=skipped,
            passed_count=passed,
            inconsistency_count=inconsistent,
        )

    def search(
        self,
        *,
        query: str = "",
        chapter: str | None = None,
        difficulty: int | None = None,
        verification_status: str | None = None,
        review_status: str | None = None,
        knowledge_point_id: str | None = None,
        module: str | None = None,
        work_queue: str | None = None,
        page: int = 1,
        page_size: int = 20,
        library_state: str = "active",
        usage_scope: str = "admin",
        usage_owner_id: str = "owner_teacher",
    ) -> QuestionSearchPage:
        clauses: list[str] = []
        values: list[Any] = []
        if library_state not in {"active", "removed", "all"}:
            raise QuestionBankError("未知的题库状态")
        if usage_scope not in {"admin", "teacher"}:
            raise QuestionBankError("未知的题库使用范围")
        if usage_scope == "teacher":
            if library_state == "removed":
                clauses.append(
                    "(question_id LIKE 'q_variant_%' AND "
                    "json_extract(raw_json, '$.generation_request.teacher_id') = ?)"
                )
            else:
                clauses.append(
                    "((verification_status = 'passed' AND question_id NOT LIKE 'q_variant_%') "
                    "OR (question_id LIKE 'q_variant_%' AND "
                    "json_extract(raw_json, '$.generation_request.teacher_id') = ?))"
                )
            values.append(usage_owner_id)
        if library_state == "active":
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM question_library_state qls "
                "WHERE qls.question_id = questions.question_id AND qls.state = 'removed')"
            )
        elif library_state == "removed":
            clauses.append(
                "EXISTS (SELECT 1 FROM question_library_state qls "
                "WHERE qls.question_id = questions.question_id AND qls.state = 'removed')"
            )
        if query.strip():
            pattern = f"%{query.strip()}%"
            clauses.append(
                "(question_id LIKE ? OR stem_plain LIKE ? OR chapter LIKE ? OR section LIKE ? OR source_document LIKE ?)"
            )
            values.extend([pattern, pattern, pattern, pattern, pattern])
        for column, value in (
            ("chapter", chapter),
            ("difficulty", difficulty),
            ("verification_status", verification_status),
            ("review_status", review_status),
        ):
            if value is not None and value != "":
                clauses.append(f"{column} = ?")
                values.append(value)
        if knowledge_point_id:
            clauses.append(
                "EXISTS (SELECT 1 FROM json_each(questions.knowledge_point_ids) WHERE value = ?)"
            )
            values.append(knowledge_point_id)
        if module:
            if module not in MODULE_RULES:
                raise QuestionBankError("未知的数学模块")
            includes, excludes = MODULE_RULES[module]
            include_sql = " OR ".join("chapter LIKE ?" for _ in includes)
            clauses.append(f"({include_sql})")
            values.extend(f"%{keyword}%" for keyword in includes)
            for keyword in excludes:
                clauses.append("chapter NOT LIKE ?")
                values.append(f"%{keyword}%")
        if work_queue:
            if work_queue not in WORK_QUEUE_KEYS:
                raise QuestionBankError("未知的审核队列")
            queue_clauses = {
                "teacher_review": "review_status = 'pending'",
                "verified_pending_teacher": (
                    "review_status = 'pending' AND verification_status = 'passed'"
                ),
                "formula_review": "verification_status = 'needs_formula_review'",
                "math_review": "verification_status = 'needs_math_review'",
                "source_conflict": (
                    "verification_status = 'source_inconsistency_detected'"
                ),
                "changes_requested": "review_status = 'changes_requested'",
                "publishable": (
                    "review_status = 'approved' AND verification_status = 'passed' "
                    "AND solution_approved = 1 AND status != 'rejected' AND ("
                    "license_status IN ('commercial_granted', 'public_permissive') OR ("
                    "license_status = 'question_content_user_declared_usable' AND "
                    "attribution_required IN ('false', 'confirmed', 'not_required')))"
                ),
            }
            clauses.append(f"({queue_clauses[work_queue]})")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        offset = (page - 1) * page_size
        with self._connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM questions {where}", values
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT questions.*,
                    COALESCE((SELECT state FROM question_library_state qls
                              WHERE qls.question_id = questions.question_id), 'active') AS library_state,
                    (SELECT removed_at FROM question_library_state qls
                     WHERE qls.question_id = questions.question_id) AS removed_at,
                    (SELECT reason FROM question_library_state qls
                     WHERE qls.question_id = questions.question_id) AS removal_reason
                FROM questions {where}
                ORDER BY updated_at DESC, question_id ASC
                LIMIT ? OFFSET ?
                """,
                [*values, page_size, offset],
            ).fetchall()
        return QuestionSearchPage(
            items=[self._summary(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    def import_batches(self) -> list[ImportBatchView]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT batch_id, schema_version, publication_status, declared_count, imported_at
                FROM import_batches ORDER BY imported_at DESC
                """
            ).fetchall()
        return [ImportBatchView(**dict(row)) for row in rows]

    def get_question(self, question_id: str) -> QuestionDetail:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT questions.*,
                    COALESCE(qls.state, 'active') AS library_state,
                    qls.removed_at, qls.reason AS removal_reason
                FROM questions LEFT JOIN question_library_state qls
                  ON qls.question_id = questions.question_id
                WHERE questions.question_id = ?
                """,
                (question_id,),
            ).fetchone()
            if row is None:
                raise KeyError(question_id)
            reviews = [
                dict(review)
                for review in connection.execute(
                    """
                    SELECT reviewer_id, decision, note, reviewed_at
                    FROM question_reviews WHERE question_id = ?
                    ORDER BY review_id DESC
                    """,
                    (question_id,),
                ).fetchall()
            ]
            images = self._list_images(connection, question_id)
            revision_count = connection.execute(
                "SELECT COUNT(*) FROM question_revisions WHERE question_id = ?",
                (question_id,),
            ).fetchone()[0]
        return QuestionDetail(
            **self._summary(row).model_dump(),
            raw=json.loads(row["raw_json"]),
            reviews=reviews,
            images=images,
            revision_count=revision_count,
        )

    def change_library_state(
        self, command: QuestionLibraryStateCommand
    ) -> QuestionLibraryStateResult:
        """Soft-remove or restore questions while preserving all question evidence."""
        question_ids = list(dict.fromkeys(command.question_ids))
        target_state = "removed" if command.action == "remove" else "active"
        now = self._now()
        changed: list[str] = []
        unchanged: list[str] = []
        with self._connect() as connection:
            placeholders = ",".join("?" for _ in question_ids)
            existing_rows = {
                row["question_id"]: row
                for row in connection.execute(
                    f"SELECT question_id, raw_json FROM questions WHERE question_id IN ({placeholders})",
                    question_ids,
                ).fetchall()
            }
            missing = [question_id for question_id in question_ids if question_id not in existing_rows]
            if missing:
                raise QuestionBankError(f"题目不存在：{', '.join(missing)}")
            if command.actor_role == "teacher":
                for question_id in question_ids:
                    if not question_id.startswith("q_variant_"):
                        raise QuestionBankError(
                            "教师只能移除或恢复自己创建的私人变式；正式题库原题仅管理员可以管理"
                        )
                    raw = json.loads(existing_rows[question_id]["raw_json"])
                    owner_id = str(
                        (raw.get("generation_request") or {}).get("teacher_id") or ""
                    )
                    if owner_id != command.actor_id:
                        raise QuestionBankError("不能处理其他教师创建的私人变式")
            states = {
                row["question_id"]: row["state"]
                for row in connection.execute(
                    f"SELECT question_id, state FROM question_library_state WHERE question_id IN ({placeholders})",
                    question_ids,
                ).fetchall()
            }
            for question_id in question_ids:
                current_state = states.get(question_id, "active")
                if current_state == target_state:
                    unchanged.append(question_id)
                    continue
                changed.append(question_id)
                removed_at = now if target_state == "removed" else None
                restored_at = now if target_state == "active" else None
                connection.execute(
                    """
                    INSERT INTO question_library_state
                    (question_id, state, reason, actor_id, relation_candidate_id,
                     removed_at, restored_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(question_id) DO UPDATE SET
                        state = excluded.state, reason = excluded.reason,
                        actor_id = excluded.actor_id,
                        relation_candidate_id = excluded.relation_candidate_id,
                        removed_at = excluded.removed_at,
                        restored_at = excluded.restored_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        question_id,
                        target_state,
                        command.reason,
                        command.actor_id,
                        command.relation_candidate_id,
                        removed_at,
                        restored_at,
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO question_library_events
                    (question_id, action, actor_id, reason, relation_candidate_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        question_id,
                        command.action,
                        command.actor_id,
                        command.reason,
                        command.relation_candidate_id,
                        now,
                    ),
                )
        verb = "移出正常题库" if command.action == "remove" else "恢复到正常题库"
        return QuestionLibraryStateResult(
            action=command.action,
            changed_question_ids=changed,
            unchanged_question_ids=unchanged,
            message=f"已将 {len(changed)} 道题{verb}",
        )

    def revise(self, question_id: str, command: QuestionRevisionCommand) -> QuestionRevisionResult:
        now = self._now()
        package_id = f"teacher-{uuid4().hex}"
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM questions WHERE question_id = ?", (question_id,)
            ).fetchone()
            if row is None:
                raise KeyError(question_id)
            self._ensure_editable(row)
            raw = json.loads(row["raw_json"])
            previous_raw = row["raw_json"]
            previous_options = raw.get("options") or []
            next_options = [
                {"key": item.key, "plain_text": item.text, "latex": None}
                for item in command.options
            ]
            previous_option_values = [
                (str(item.get("key", "")), str(item.get("latex") or item.get("plain_text") or "").strip())
                for item in previous_options
            ]
            next_option_values = [(item.key, item.text.strip()) for item in command.options]
            verification_reset = any(
                (
                    command.stem_plain.strip() != str(row["stem_plain"]).strip(),
                    (command.stem_latex or "").strip() != (row["stem_latex"] or "").strip(),
                    next_option_values != previous_option_values,
                    (command.answer_value or "").strip() != (row["answer_value"] or "").strip(),
                )
            )
            raw["stem"] = {
                **(raw.get("stem") or {}),
                "plain_text": command.stem_plain.strip(),
                "latex": command.stem_latex.strip() if command.stem_latex else None,
            }
            raw["options"] = next_options
            raw["answer"] = {**(raw.get("answer") or {}), "value": command.answer_value}
            raw["solutions"] = [{
                "method": command.solution_method.strip(),
                "steps_latex": [step.strip() for step in command.solution_steps if step.strip()],
                "final_answer": command.final_answer,
                "author_type": "teacher_authored",
                "review_status": "ready_for_teacher_review",
            }]
            raw["last_manual_revision"] = {
                "editor_id": command.editor_id,
                "note": command.note,
                "created_at": now,
            }
            verification_status = row["verification_status"]
            status = "verified" if verification_status == "passed" else "imported"
            if verification_reset:
                verification_status = "needs_math_review"
                status = "imported"
                raw["verification"] = {
                    "status": "needs_math_review",
                    "methods": ["teacher_revision_requires_reverification"],
                    "details": ["教师修改了题干、选项或答案，旧验证结论已失效。"],
                }
            revised_raw = json.dumps(raw, ensure_ascii=False)
            cursor = connection.execute(
                """
                INSERT INTO question_revisions
                (package_id, question_id, previous_raw_json, revised_raw_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (package_id, question_id, previous_raw, revised_raw, now),
            )
            connection.execute(
                """
                UPDATE questions SET status = ?, review_status = 'pending', stem_plain = ?,
                    stem_latex = ?, answer_value = ?, verification_status = ?,
                    solution_approved = 0, raw_json = ?, updated_at = ?
                WHERE question_id = ?
                """,
                (
                    status,
                    command.stem_plain.strip(),
                    command.stem_latex.strip() if command.stem_latex else None,
                    command.answer_value,
                    verification_status,
                    revised_raw,
                    now,
                    question_id,
                ),
            )
            revision_id = int(cursor.lastrowid)
        return QuestionRevisionResult(
            question=self.get_question(question_id),
            revision_id=revision_id,
            verification_reset=verification_reset,
        )

    def create_derived_question(
        self,
        source_question_id: str,
        candidate: dict[str, Any],
        *,
        generation: dict[str, Any],
    ) -> QuestionDetail:
        """Persist a generated variant as a private, auditable question draft."""
        now = self._now()
        question_id = f"q_variant_{uuid4().hex[:12]}"
        run_id = f"qrun_{uuid4().hex}"
        batch_id = "generated-question-variants-v1"
        created_files: list[Path] = []
        required = (
            "question_type",
            "stem_plain",
            "options",
            "answer_value",
            "solution_method",
            "solution_steps",
            "final_answer",
            "difficulty",
            "verification_status",
            "verification_details",
        )
        missing = [key for key in required if key not in candidate]
        if missing:
            raise QuestionBankError(f"变式草稿缺少字段：{', '.join(missing)}")
        try:
            difficulty = int(candidate["difficulty"])
        except (TypeError, ValueError) as exc:
            raise QuestionBankError("变式难度必须是 1 到 5 的整数") from exc
        if difficulty not in range(1, 6):
            raise QuestionBankError("变式难度必须是 1 到 5 的整数")
        if candidate["verification_status"] not in {"passed", "needs_math_review"}:
            raise QuestionBankError("变式验证状态无效")

        try:
            with self._connect() as connection:
                source_row = connection.execute(
                    "SELECT * FROM questions WHERE question_id = ?", (source_question_id,)
                ).fetchone()
                if source_row is None:
                    raise KeyError(source_question_id)
                if source_row["verification_status"] != "passed":
                    raise QuestionBankError("原题尚未通过独立数学验证，不能创建自动变式")
                source_raw = json.loads(source_row["raw_json"])
                source_rights = source_raw.get("source") or {}
                allowed_uses = set(source_rights.get("allowed_uses") or [])
                if (
                    "adapt_question" not in allowed_uses
                    and source_row["license_status"] not in {"commercial_granted", "public_permissive"}
                ):
                    raise QuestionBankError("原题权利记录未允许改编，不能生成变式")

                options = [
                    {"key": item["key"], "plain_text": item["text"], "latex": None}
                    for item in candidate["options"]
                ]
                verification = {
                    "status": candidate["verification_status"],
                    "methods": [
                        "verified_source_diagnostic_derivation"
                        if candidate["verification_status"] == "passed"
                        else "ai_generated_requires_independent_verification"
                    ],
                    "details": candidate["verification_details"],
                }
                source = {
                    **source_rights,
                    "document_name": f"{source_row['source_document']}（派生变式）",
                    "source_question_number": question_id,
                    "source_reference": f"基于题目 {source_question_id} 的私有变式",
                    "derived_from_question_id": source_question_id,
                }
                raw = {
                    "id": question_id,
                    "status": "verified" if candidate["verification_status"] == "passed" else "imported",
                    "visibility": "private",
                    "language": "zh-CN",
                    "stem": {
                        "plain_text": str(candidate["stem_plain"]).strip(),
                        "latex": candidate.get("stem_latex") or None,
                        "assets": [],
                    },
                    "question_type": candidate["question_type"],
                    "options": options,
                    "answer": {
                        "type": "option" if options else "text",
                        "value": candidate["answer_value"],
                        "status": "generated_draft",
                        "alternatives": [],
                    },
                    "solutions": [
                        {
                            "method": candidate["solution_method"],
                            "steps_latex": candidate["solution_steps"],
                            "final_answer": candidate["final_answer"],
                            "author_type": "rule_generated"
                            if generation.get("mode") == "local_rule"
                            else "ai_generated",
                            "review_status": "ready_for_teacher_review",
                        }
                    ],
                    "curriculum": source_raw.get("curriculum") or {},
                    "exam": {
                        "paper_family": "AI 变式草稿",
                        "region": None,
                        "year": None,
                        "original_score": None,
                        "competency_tags": (source_raw.get("exam") or {}).get("competency_tags", []),
                    },
                    "pedagogy": {
                        **(source_raw.get("pedagogy") or {}),
                        "difficulty": difficulty,
                        "difficulty_confidence": 0.5,
                        "usage_scenarios": ["教师私有变式", generation.get("request", {}).get("variant_kind", "")],
                    },
                    "verification": verification,
                    "source": source,
                    "provenance": {
                        "created_by": "question_variant_service",
                        "derived_from_question_ids": [source_question_id],
                        "model_run_id": run_id,
                        "provider": generation.get("provider"),
                        "model": generation.get("model"),
                    },
                    "generation_request": generation.get("request") or {},
                    "reviews": [],
                    "created_at": now,
                    "updated_at": now,
                }
                connection.execute(
                    """
                    INSERT OR IGNORE INTO import_batches
                    (batch_id, schema_version, source_file, publication_status,
                     declared_count, rights_basis, imported_at)
                    VALUES (?, '1.0', 'generated://question-variants', 'private_not_publishable',
                            0, '派生题继承母题权利边界并保持私有待审核', ?)
                    """,
                    (batch_id, now),
                )
                connection.execute(
                    """
                    INSERT INTO questions (
                        question_id, batch_id, status, review_status, visibility, question_type,
                        stem_plain, stem_latex, answer_value, volume, chapter, section,
                        knowledge_point_ids, difficulty, verification_status,
                        source_document, source_page_start, source_page_end,
                        license_status, attribution_required, solution_approved,
                        raw_json, created_at, updated_at
                    ) VALUES (?, ?, ?, 'pending', 'private', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                    """,
                    (
                        question_id,
                        batch_id,
                        raw["status"],
                        candidate["question_type"],
                        raw["stem"]["plain_text"],
                        raw["stem"]["latex"],
                        candidate["answer_value"],
                        source_row["volume"],
                        source_row["chapter"],
                        source_row["section"],
                        source_row["knowledge_point_ids"],
                        difficulty,
                        candidate["verification_status"],
                        source["document_name"],
                        source_row["source_page_start"],
                        source_row["source_page_end"],
                        source_row["license_status"],
                        source_row["attribution_required"],
                        json.dumps(raw, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                source_images = connection.execute(
                    """
                    SELECT * FROM question_images
                    WHERE question_id = ? AND placement = 'stem'
                    ORDER BY sort_order, created_at
                    """,
                    (source_question_id,),
                ).fetchall()
                for image in source_images:
                    source_path = self.media_root / image["stored_filename"]
                    if not source_path.is_file():
                        raise QuestionBankError(f"原题图片文件缺失：{image['original_filename']}")
                    image_id = f"img_{uuid4().hex}"
                    extension = Path(image["stored_filename"]).suffix
                    stored_filename = f"{image_id}{extension}"
                    target_path = self.media_root / stored_filename
                    shutil.copyfile(source_path, target_path)
                    created_files.append(target_path)
                    connection.execute(
                        """
                        INSERT INTO question_images
                        (image_id, question_id, placement, original_filename, stored_filename,
                         mime_type, width, height, alt_text, caption, sort_order, created_at, updated_at)
                        VALUES (?, ?, 'stem', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            image_id,
                            question_id,
                            image["original_filename"],
                            stored_filename,
                            image["mime_type"],
                            image["width"],
                            image["height"],
                            image["alt_text"],
                            image["caption"],
                            image["sort_order"],
                            now,
                            now,
                        ),
                    )
                    self._record_image_event(
                        connection,
                        image_id,
                        question_id,
                        "cloned_from_source_question",
                        str(generation.get("request", {}).get("teacher_id", "owner_teacher")),
                        {"source_question_id": source_question_id, "source_image_id": image["image_id"]},
                        now,
                    )
                connection.execute(
                    """
                    INSERT INTO question_generation_runs
                    (run_id, source_question_id, output_question_id, provider, model, mode,
                     request_json, output_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        source_question_id,
                        question_id,
                        str(generation.get("provider", "unknown")),
                        str(generation.get("model", "unknown")),
                        str(generation.get("mode", "unknown")),
                        json.dumps(generation.get("request") or {}, ensure_ascii=False),
                        json.dumps(candidate, ensure_ascii=False),
                        now,
                    ),
                )
                connection.execute(
                    """
                    UPDATE import_batches
                    SET declared_count = (
                        SELECT COUNT(*) FROM questions WHERE batch_id = ?
                    ) WHERE batch_id = ?
                    """,
                    (batch_id, batch_id),
                )
        except Exception:
            for path in created_files:
                path.unlink(missing_ok=True)
            raise
        return self.get_question(question_id)

    def create_private_resource_question(
        self, candidate: dict[str, Any], *, resource: dict[str, Any]
    ) -> QuestionDetail:
        """Import one reviewed resource candidate without bypassing question gates."""
        candidate_id = str(candidate.get("candidate_id", ""))
        stem = str(candidate.get("stem_plain", "")).strip()
        if not candidate_id or not stem:
            raise QuestionBankError("拆题候选缺少编号或题干")
        if candidate.get("status") == "discarded":
            raise QuestionBankError("已丢弃的拆题候选不能导入题库")
        question_id = f"q_resource_{candidate_id.removeprefix('cand_')}"
        try:
            return self.get_question(question_id)
        except KeyError:
            pass
        now = self._now()
        batch_id = "private-resource-drafts-v1"
        rights_basis = str(resource.get("rights_basis", "private_teaching_only"))
        license_status = {
            "original": "question_content_user_declared_usable",
            "licensed": "commercial_granted",
            "question_content_user_declared_usable": "question_content_user_declared_usable",
            "private_research_only": "research_only",
            "private_teaching_only": "private_use_only",
        }.get(rights_basis, "private_use_only")
        options = [
            {"key": item["key"], "plain_text": item.get("text", ""), "latex": None}
            for item in candidate.get("options", [])
        ]
        solution_steps = [str(step) for step in candidate.get("solution_steps", []) if str(step).strip()]
        answer = candidate.get("answer_value")
        raw = {
            "id": question_id,
            "status": "imported",
            "visibility": "private",
            "language": "zh-CN",
            "stem": {
                "plain_text": stem,
                "latex": candidate.get("stem_latex"),
                "assets": [],
            },
            "question_type": candidate.get("question_type", "open_response"),
            "options": options,
            "answer": {
                "type": "option" if options else "text",
                "value": answer,
                "status": "teacher_review_draft",
                "alternatives": [],
            },
            "solutions": [
                {
                    "method": candidate.get("solution_method") or "教师整理",
                    "steps_latex": solution_steps,
                    "final_answer": candidate.get("final_answer"),
                    "author_type": "resource_extraction",
                    "review_status": "ready_for_teacher_review",
                }
            ],
            "curriculum": {
                "standard_version": "普通高中数学课程标准（2017年版2020年修订）",
                "textbook_version": "人教A版",
                "volume": None,
                "chapter": None,
                "section": None,
                "knowledge_point_ids": [],
            },
            "exam": {"paper_family": None, "region": None, "year": None, "original_score": None, "competency_tags": []},
            "pedagogy": {
                "difficulty": int(candidate.get("difficulty", 3)),
                "difficulty_confidence": 0.2,
                "usage_scenarios": ["私人资料拆题草稿"],
            },
            "verification": {
                "status": "needs_math_review",
                "methods": ["teacher_confirmed_source_text_only"],
                "details": ["教师确认了资料文本，但题目答案与解析仍需独立数学核验。"],
            },
            "source": {
                "document_name": resource.get("title") or resource.get("original_filename") or "私人资料",
                "source_question_number": str(candidate.get("position", "")),
                "source_reference": candidate.get("source_reference") or f"私人资料 {resource.get('library_item_id')} · 文本版本 {candidate.get('source_version')}",
                "license_status": license_status,
                "attribution_required": "confirmed" if rights_basis in {"original", "licensed", "question_content_user_declared_usable"} else "not_confirmed",
                "rights_basis": rights_basis,
                "rights_statement": resource.get("rights_statement", ""),
                "allowed_uses": ["private_teaching"] + (["adapt_question"] if resource.get("adaptation_allowed") else []),
                "media_references": candidate.get("media_references", []),
            },
            "provenance": {
                "created_by": candidate.get("provenance_type") or "private_resource_question_pipeline",
                "library_item_id": resource.get("library_item_id"),
                "library_source_version": candidate.get("source_version"),
                "resource_candidate_id": candidate_id,
                "boundary_candidate_id": candidate.get("boundary_candidate_id"),
            },
            "reviews": [],
            "created_at": now,
            "updated_at": now,
        }
        difficulty = int(candidate.get("difficulty", 3))
        if difficulty not in range(1, 6):
            raise QuestionBankError("题目难度必须是 1 到 5 的整数")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO import_batches
                (batch_id, schema_version, source_file, publication_status,
                 declared_count, rights_basis, imported_at)
                VALUES (?, '1.0', 'private-library://confirmed-candidates',
                        'private_not_publishable', 0, '逐份继承教师权利声明', ?)
                """,
                (batch_id, now),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO questions (
                    question_id, batch_id, status, review_status, visibility, question_type,
                    stem_plain, stem_latex, answer_value, volume, chapter, section,
                    knowledge_point_ids, difficulty, verification_status,
                    source_document, source_page_start, source_page_end,
                    license_status, attribution_required, solution_approved,
                    raw_json, created_at, updated_at
                ) VALUES (?, ?, 'imported', 'pending', 'private', ?, ?, ?, ?, NULL, NULL, NULL,
                          '[]', ?, 'needs_math_review', ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    question_id, batch_id, raw["question_type"], stem, raw["stem"]["latex"],
                    answer, difficulty, raw["source"]["document_name"],
                    candidate.get("start_page"), candidate.get("end_page"), license_status,
                    raw["source"]["attribution_required"], json.dumps(raw, ensure_ascii=False), now, now,
                ),
            )
        return self.get_question(question_id)

    def apply_curriculum_mapping(
        self,
        question_id: str,
        *,
        node_id: str,
        volume: str,
        chapter: str,
        section: str,
        topic: str,
        actor_id: str,
    ) -> QuestionDetail:
        """Apply one teacher-confirmed primary knowledge point with revision history."""
        now = self._now()
        package_id = f"curriculum-{uuid4().hex}"
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM questions WHERE question_id = ?", (question_id,)
            ).fetchone()
            if row is None:
                raise KeyError(question_id)
            self._ensure_editable(row)
            previous_raw = row["raw_json"]
            raw = json.loads(previous_raw)
            raw["curriculum"] = {
                **(raw.get("curriculum") or {}),
                "textbook_version": "人教A版",
                "volume": volume,
                "chapter": chapter,
                "section": section,
                "topic": topic,
                "knowledge_point_ids": [node_id],
                "mapping_status": "teacher_confirmed",
                "mapped_by": actor_id,
                "mapped_at": now,
            }
            revised_raw = json.dumps(raw, ensure_ascii=False)
            connection.execute(
                """
                INSERT INTO question_revisions
                (package_id, question_id, previous_raw_json, revised_raw_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (package_id, question_id, previous_raw, revised_raw, now),
            )
            connection.execute(
                """
                UPDATE questions SET volume = ?, chapter = ?, section = ?,
                    knowledge_point_ids = ?, review_status = 'pending', raw_json = ?, updated_at = ?
                WHERE question_id = ?
                """,
                (volume, chapter, section, json.dumps([node_id], ensure_ascii=False), revised_raw, now, question_id),
            )
        return self.get_question(question_id)

    def record_manual_verification(
        self,
        question_id: str,
        *,
        conclusion: str,
        computed_answer: str,
        evidence_steps: list[str],
        note: str,
        verifier_id: str,
    ) -> str:
        """Record independent teacher evidence; answer mismatches can never pass."""
        if conclusion not in {"passed", "inconsistent", "inconclusive"}:
            raise QuestionBankError("独立核验结论无效")
        now = self._now()
        package_id = f"manual-verification-{uuid4().hex}"
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM questions WHERE question_id = ?", (question_id,)
            ).fetchone()
            if row is None:
                raise KeyError(question_id)
            self._ensure_editable(row)
            source_answer = str(row["answer_value"] or "").strip()
            independent_answer = computed_answer.strip()
            if conclusion == "passed" and (not source_answer or not independent_answer):
                raise QuestionBankError("核验通过前，当前答案和独立计算答案都不能为空")
            answers_match = bool(
                source_answer
                and independent_answer
                and self._normalize_answer(source_answer) == self._normalize_answer(independent_answer)
            )
            if conclusion == "passed" and not answers_match:
                status = "source_inconsistency_detected"
            elif conclusion == "passed":
                status = "passed"
            elif conclusion == "inconsistent":
                status = "source_inconsistency_detected"
            else:
                status = "needs_math_review"
            details = list(evidence_steps)
            if note:
                details.append(note)
            if conclusion == "passed" and not answers_match:
                details.append(f"独立答案“{independent_answer}”与当前答案“{source_answer}”不一致，系统拒绝标记通过。")
            raw = json.loads(row["raw_json"])
            raw["verification"] = {
                "status": status,
                "methods": ["teacher_independent_derivation"],
                "details": details,
                "computed_answer": independent_answer or None,
                "source_answer": source_answer or None,
                "answers_match": answers_match,
                "evidence": {"steps": evidence_steps, "note": note, "verifier_id": verifier_id},
                "verified_at": now,
            }
            report = raw["verification"]
            connection.execute(
                """
                INSERT INTO verification_reports
                (package_id, question_id, status, report_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (package_id, question_id, status, json.dumps(report, ensure_ascii=False), now),
            )
            connection.execute(
                """
                UPDATE questions SET status = ?, review_status = 'pending',
                    verification_status = ?, solution_approved = 0, raw_json = ?, updated_at = ?
                WHERE question_id = ?
                """,
                (
                    "verified" if status == "passed" else "imported",
                    status,
                    json.dumps(raw, ensure_ascii=False),
                    now,
                    question_id,
                ),
            )
        return status

    def add_image(
        self,
        question_id: str,
        content: bytes,
        original_filename: str,
        placement: str,
        alt_text: str,
        caption: str,
        actor_id: str = "owner_teacher",
    ) -> QuestionImage:
        if placement not in {"stem", "solution"}:
            raise QuestionBankError("图片位置只能是题干或解析")
        mime_type, extension, width, height = self._inspect_image(content)
        image_id = f"img_{uuid4().hex}"
        stored_filename = f"{image_id}{extension}"
        now = self._now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM questions WHERE question_id = ?", (question_id,)
            ).fetchone()
            if row is None:
                raise KeyError(question_id)
            self._ensure_editable(row)
            count = connection.execute(
                "SELECT COUNT(*) FROM question_images WHERE question_id = ?", (question_id,)
            ).fetchone()[0]
            if count >= self.MAX_IMAGES_PER_QUESTION:
                raise QuestionBankError(f"每道题最多上传 {self.MAX_IMAGES_PER_QUESTION} 张图片")
            sort_order = connection.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM question_images WHERE question_id = ? AND placement = ?",
                (question_id, placement),
            ).fetchone()[0]
            (self.media_root / stored_filename).write_bytes(content)
            connection.execute(
                """
                INSERT INTO question_images
                (image_id, question_id, placement, original_filename, stored_filename,
                 mime_type, width, height, alt_text, caption, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    image_id, question_id, placement, Path(original_filename).name,
                    stored_filename, mime_type, width, height, alt_text.strip(),
                    caption.strip(), sort_order, now, now,
                ),
            )
            self._record_image_event(
                connection, image_id, question_id, "added", actor_id,
                {"placement": placement, "filename": Path(original_filename).name}, now,
            )
            if placement == "stem":
                self._invalidate_verification(connection, question_id, "题干配图已新增，需重新验证。", now)
            image = connection.execute(
                "SELECT * FROM question_images WHERE image_id = ?", (image_id,)
            ).fetchone()
        return self._image_view(image)

    def update_image(
        self,
        question_id: str,
        image_id: str,
        command: QuestionImageMetadataCommand,
        actor_id: str = "owner_teacher",
    ) -> QuestionImage:
        now = self._now()
        with self._connect() as connection:
            question = connection.execute(
                "SELECT * FROM questions WHERE question_id = ?", (question_id,)
            ).fetchone()
            if question is None:
                raise KeyError(question_id)
            self._ensure_editable(question)
            image = self._get_image_row(connection, question_id, image_id)
            placement = command.placement or image["placement"]
            alt_text = image["alt_text"] if command.alt_text is None else command.alt_text.strip()
            caption = image["caption"] if command.caption is None else command.caption.strip()
            placement_changed = placement != image["placement"]
            connection.execute(
                """
                UPDATE question_images SET placement = ?, alt_text = ?, caption = ?, updated_at = ?
                WHERE image_id = ? AND question_id = ?
                """,
                (placement, alt_text, caption, now, image_id, question_id),
            )
            self._record_image_event(
                connection, image_id, question_id, "metadata_updated", actor_id,
                {"placement": placement, "alt_text": alt_text, "caption": caption}, now,
            )
            if placement_changed and "stem" in {placement, image["placement"]}:
                self._invalidate_verification(connection, question_id, "题干配图位置已变更，需重新验证。", now)
            updated = self._get_image_row(connection, question_id, image_id)
        return self._image_view(updated)

    def replace_image(
        self,
        question_id: str,
        image_id: str,
        content: bytes,
        original_filename: str,
        actor_id: str = "owner_teacher",
    ) -> QuestionImage:
        mime_type, extension, width, height = self._inspect_image(content)
        now = self._now()
        with self._connect() as connection:
            question = connection.execute(
                "SELECT * FROM questions WHERE question_id = ?", (question_id,)
            ).fetchone()
            if question is None:
                raise KeyError(question_id)
            self._ensure_editable(question)
            image = self._get_image_row(connection, question_id, image_id)
            old_path = self.media_root / image["stored_filename"]
            stored_filename = f"{image_id}-{uuid4().hex[:8]}{extension}"
            new_path = self.media_root / stored_filename
            new_path.write_bytes(content)
            connection.execute(
                """
                UPDATE question_images SET original_filename = ?, stored_filename = ?, mime_type = ?,
                    width = ?, height = ?, updated_at = ? WHERE image_id = ? AND question_id = ?
                """,
                (Path(original_filename).name, stored_filename, mime_type, width, height, now, image_id, question_id),
            )
            self._record_image_event(
                connection, image_id, question_id, "file_replaced", actor_id,
                {"filename": Path(original_filename).name}, now,
            )
            if image["placement"] == "stem":
                self._invalidate_verification(connection, question_id, "题干配图已替换，需重新验证。", now)
            updated = self._get_image_row(connection, question_id, image_id)
        if old_path.exists():
            old_path.unlink()
        return self._image_view(updated)

    def delete_image(
        self, question_id: str, image_id: str, actor_id: str = "owner_teacher"
    ) -> None:
        now = self._now()
        with self._connect() as connection:
            question = connection.execute(
                "SELECT * FROM questions WHERE question_id = ?", (question_id,)
            ).fetchone()
            if question is None:
                raise KeyError(question_id)
            self._ensure_editable(question)
            image = self._get_image_row(connection, question_id, image_id)
            path = self.media_root / image["stored_filename"]
            self._record_image_event(
                connection, image_id, question_id, "deleted", actor_id,
                {"filename": image["original_filename"], "placement": image["placement"]}, now,
            )
            connection.execute(
                "DELETE FROM question_images WHERE image_id = ? AND question_id = ?",
                (image_id, question_id),
            )
            if image["placement"] == "stem":
                self._invalidate_verification(connection, question_id, "题干配图已删除，需重新验证。", now)
        if path.exists():
            path.unlink()

    def reorder_images(
        self, question_id: str, image_ids: list[str], actor_id: str = "owner_teacher"
    ) -> list[QuestionImage]:
        now = self._now()
        with self._connect() as connection:
            question = connection.execute(
                "SELECT * FROM questions WHERE question_id = ?", (question_id,)
            ).fetchone()
            if question is None:
                raise KeyError(question_id)
            self._ensure_editable(question)
            rows = connection.execute(
                "SELECT image_id FROM question_images WHERE question_id = ? ORDER BY placement, sort_order",
                (question_id,),
            ).fetchall()
            existing = {row["image_id"] for row in rows}
            if len(image_ids) != len(set(image_ids)) or set(image_ids) != existing:
                raise QuestionBankError("排序必须包含该题当前的全部图片，且不能重复")
            for index, current_id in enumerate(image_ids):
                connection.execute(
                    "UPDATE question_images SET sort_order = ?, updated_at = ? WHERE image_id = ?",
                    (index, now, current_id),
                )
            self._record_image_event(
                connection, "collection", question_id, "reordered", actor_id,
                {"image_ids": image_ids}, now,
            )
            images = self._list_images(connection, question_id)
        return images

    def image_path(self, question_id: str, image_id: str) -> tuple[Path, str]:
        with self._connect() as connection:
            image = self._get_image_row(connection, question_id, image_id)
        path = (self.media_root / image["stored_filename"]).resolve()
        if self.media_root not in path.parents or not path.is_file():
            raise KeyError(image_id)
        return path, str(image["mime_type"])

    def review(self, question_id: str, command: ReviewCommand) -> ReviewResult:
        reviewed_at = self._now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status, verification_status, raw_json FROM questions WHERE question_id = ?",
                (question_id,),
            ).fetchone()
            if row is None:
                raise KeyError(question_id)
            if row["status"] == "published":
                raise QuestionBankError("已发布版本不可直接修改审核结论")
            solution_approved = 0
            if command.decision == "approved":
                if row["verification_status"] != "passed":
                    raise QuestionBankError("题目尚未通过独立数学验证，不能标记为教师通过")
                raw = json.loads(row["raw_json"])
                solution_approved = int(
                    any(
                        solution.get("review_status") == "ready_for_teacher_review"
                        for solution in raw.get("solutions", [])
                    )
                )
                status = "reviewed"
            elif command.decision == "rejected":
                status = "rejected"
            else:
                status = row["status"]
            connection.execute(
                """
                INSERT INTO question_reviews
                (question_id, reviewer_id, decision, note, reviewed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (question_id, command.reviewer_id, command.decision, command.note, reviewed_at),
            )
            connection.execute(
                """
                UPDATE questions SET review_status = ?, status = ?, solution_approved = ?, updated_at = ?
                WHERE question_id = ?
                """,
                (command.decision, status, solution_approved, reviewed_at, question_id),
            )
        return ReviewResult(
            question_id=question_id,
            decision=command.decision,
            status=status,
            review_status=command.decision,
            reviewed_at=reviewed_at,
        )

    def publish(self, question_id: str) -> PublishDecision:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT questions.*, COALESCE(qls.state, 'active') AS library_state
                FROM questions LEFT JOIN question_library_state qls
                  ON qls.question_id = questions.question_id
                WHERE questions.question_id = ?
                """,
                (question_id,),
            ).fetchone()
            if row is None:
                raise KeyError(question_id)
            blockers = self._publication_blockers(row)
            if not blockers:
                connection.execute(
                    """
                    UPDATE questions SET status = 'published', visibility = 'public', updated_at = ?
                    WHERE question_id = ?
                    """,
                    (self._now(), question_id),
                )
                status, visibility = "published", "public"
            else:
                status, visibility = row["status"], row["visibility"]
        return PublishDecision(
            question_id=question_id,
            allowed=not blockers,
            blockers=blockers,
            status=status,
            visibility=visibility,
        )

    def stats(self) -> QuestionBankStats:
        with self._connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
            rows = connection.execute(
                """
                SELECT questions.*, COALESCE(qls.state, 'active') AS library_state
                FROM questions LEFT JOIN question_library_state qls
                  ON qls.question_id = questions.question_id
                """
            ).fetchall()
        active_rows = [row for row in rows if row["library_state"] == "active"]
        review = dict(Counter(str(row["review_status"]) for row in active_rows))
        verification = dict(Counter(str(row["verification_status"]) for row in active_rows))
        chapters = dict(Counter(str(row["chapter"] or "未映射") for row in active_rows))
        publishable = sum(not self._publication_blockers(row) for row in active_rows)
        by_module = {key: 0 for key in MODULE_RULES}
        for row in active_rows:
            chapter = str(row["chapter"] or "")
            for key, (includes, excludes) in MODULE_RULES.items():
                if any(keyword in chapter for keyword in includes) and not any(
                    keyword in chapter for keyword in excludes
                ):
                    by_module[key] += 1
                    break
        by_work_queue = {
            "teacher_review": sum(row["review_status"] == "pending" for row in active_rows),
            "verified_pending_teacher": sum(
                row["review_status"] == "pending"
                and row["verification_status"] == "passed"
                for row in active_rows
            ),
            "formula_review": sum(
                row["verification_status"] == "needs_formula_review" for row in active_rows
            ),
            "math_review": sum(
                row["verification_status"] == "needs_math_review" for row in active_rows
            ),
            "source_conflict": sum(
                row["verification_status"] == "source_inconsistency_detected"
                for row in active_rows
            ),
            "changes_requested": sum(
                row["review_status"] == "changes_requested" for row in active_rows
            ),
            "publishable": publishable,
        }
        return QuestionBankStats(
            total=total,
            active=len(active_rows),
            removed=total - len(active_rows),
            by_review_status=review,
            by_verification_status=verification,
            by_chapter=chapters,
            by_work_queue=by_work_queue,
            by_module=by_module,
            publishable=publishable,
        )

    @staticmethod
    def _validate_batch(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            raise QuestionBankError("批次根节点必须是对象")
        required = ("batch_id", "questions", "question_count")
        missing = [key for key in required if key not in payload]
        if missing:
            raise QuestionBankError(f"批次缺少字段：{', '.join(missing)}")
        questions = payload["questions"]
        if not isinstance(questions, list) or payload["question_count"] != len(questions):
            raise QuestionBankError("question_count 与 questions 数量不一致")
        ids: set[str] = set()
        for index, question in enumerate(questions, start=1):
            try:
                question_id = question["id"]
                stem = question["stem"]["plain_text"]
                question["curriculum"]["knowledge_point_ids"]
                question["verification"]["status"]
                question["source"]["license_status"]
            except (KeyError, TypeError) as exc:
                raise QuestionBankError(f"第 {index} 题缺少必填字段：{exc}") from exc
            if not isinstance(question_id, str) or not question_id or not str(stem).strip():
                raise QuestionBankError(f"第 {index} 题的 ID 或题干无效")
            if question_id in ids:
                raise QuestionBankError(f"题目 ID 重复：{question_id}")
            ids.add(question_id)
        return questions

    @staticmethod
    def _question_row(batch_id: str, question: dict[str, Any], imported_at: str) -> tuple[Any, ...]:
        stem = question["stem"]
        curriculum = question["curriculum"]
        source = question["source"]
        solutions = question.get("solutions") or []
        solution_approved = any(item.get("review_status") == "approved" for item in solutions)
        answer_value = question.get("answer", {}).get("value")
        if answer_value is not None and not isinstance(answer_value, str):
            answer_value = json.dumps(answer_value, ensure_ascii=False)
        attribution = source.get("attribution_required")
        if not isinstance(attribution, str):
            attribution = json.dumps(attribution, ensure_ascii=False)
        return (
            question["id"], batch_id, question.get("status", "imported"),
            question.get("visibility", "private"), question.get("question_type", "unknown"),
            stem.get("plain_text", ""), stem.get("latex"), answer_value,
            curriculum.get("volume"), curriculum.get("chapter"), curriculum.get("section"),
            json.dumps(curriculum.get("knowledge_point_ids", []), ensure_ascii=False),
            int(question.get("pedagogy", {}).get("difficulty", 3)),
            question["verification"]["status"], source.get("document_name", "未命名来源"),
            source.get("source_page_start"), source.get("source_page_end"),
            source["license_status"], attribution, int(solution_approved),
            json.dumps(question, ensure_ascii=False), question.get("created_at", imported_at), imported_at,
        )

    def _summary(self, row: sqlite3.Row) -> QuestionSummary:
        keys = set(row.keys())
        library_state = row["library_state"] if "library_state" in keys else "active"
        removed_at = row["removed_at"] if "removed_at" in keys else None
        removal_reason = row["removal_reason"] if "removal_reason" in keys else None
        return QuestionSummary(
            question_id=row["question_id"], status=row["status"],
            review_status=row["review_status"], visibility=row["visibility"],
            question_type=row["question_type"], stem_plain=row["stem_plain"],
            answer_value=row["answer_value"], volume=row["volume"], chapter=row["chapter"],
            section=row["section"], knowledge_point_ids=json.loads(row["knowledge_point_ids"]),
            difficulty=row["difficulty"], verification_status=row["verification_status"],
            source_document=row["source_document"], source_page_start=row["source_page_start"],
            source_page_end=row["source_page_end"], license_status=row["license_status"],
            publication_blockers=self._publication_blockers(row),
            library_state=library_state, removed_at=removed_at,
            removal_reason=removal_reason,
        )

    @staticmethod
    def _ensure_editable(row: sqlite3.Row) -> None:
        if row["status"] == "published":
            raise QuestionBankError("已发布题目不可直接覆盖，请先创建新的私有版本")

    def _inspect_image(self, content: bytes) -> tuple[str, str, int, int]:
        if not content:
            raise QuestionBankError("图片文件为空")
        if len(content) > self.MAX_IMAGE_BYTES:
            raise QuestionBankError("图片不能超过 8 MB")
        try:
            with Image.open(BytesIO(content)) as image:
                image_format = image.format
                width, height = image.size
                if image_format not in self.IMAGE_FORMATS:
                    raise QuestionBankError("仅支持 PNG、JPEG 和 WebP 图片")
                if width < 1 or height < 1 or width * height > self.MAX_IMAGE_PIXELS:
                    raise QuestionBankError("图片尺寸无效或像素总量超过 2500 万")
                image.verify()
        except QuestionBankError:
            raise
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise QuestionBankError("文件不是有效的 PNG、JPEG 或 WebP 图片") from exc
        mime_type, extension = self.IMAGE_FORMATS[image_format]
        return mime_type, extension, width, height

    def _get_image_row(
        self, connection: sqlite3.Connection, question_id: str, image_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM question_images WHERE question_id = ? AND image_id = ?",
            (question_id, image_id),
        ).fetchone()
        if row is None:
            raise KeyError(image_id)
        return row

    def _list_images(
        self, connection: sqlite3.Connection, question_id: str
    ) -> list[QuestionImage]:
        rows = connection.execute(
            """
            SELECT * FROM question_images WHERE question_id = ?
            ORDER BY CASE placement WHEN 'stem' THEN 0 ELSE 1 END, sort_order, created_at
            """,
            (question_id,),
        ).fetchall()
        return [self._image_view(row) for row in rows]

    @staticmethod
    def _image_view(row: sqlite3.Row) -> QuestionImage:
        question_id = str(row["question_id"])
        image_id = str(row["image_id"])
        return QuestionImage(
            image_id=image_id,
            question_id=question_id,
            placement=row["placement"],
            original_filename=row["original_filename"],
            mime_type=row["mime_type"],
            width=row["width"],
            height=row["height"],
            alt_text=row["alt_text"],
            caption=row["caption"],
            sort_order=row["sort_order"],
            content_url=f"/api/v1/questions/{question_id}/images/{image_id}/content",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _record_image_event(
        connection: sqlite3.Connection,
        image_id: str,
        question_id: str,
        action: str,
        actor_id: str,
        payload: dict[str, Any],
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO question_image_events
            (image_id, question_id, action, actor_id, event_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (image_id, question_id, action, actor_id, json.dumps(payload, ensure_ascii=False), created_at),
        )

    @staticmethod
    def _invalidate_verification(
        connection: sqlite3.Connection, question_id: str, reason: str, updated_at: str
    ) -> None:
        row = connection.execute(
            "SELECT raw_json FROM questions WHERE question_id = ?", (question_id,)
        ).fetchone()
        if row is None:
            raise KeyError(question_id)
        raw = json.loads(row["raw_json"])
        raw["verification"] = {
            "status": "needs_math_review",
            "methods": ["question_media_changed"],
            "details": [reason],
        }
        connection.execute(
            """
            UPDATE questions SET status = 'imported', review_status = 'pending',
                verification_status = 'needs_math_review', solution_approved = 0,
                raw_json = ?, updated_at = ? WHERE question_id = ?
            """,
            (json.dumps(raw, ensure_ascii=False), updated_at, question_id),
        )

    @staticmethod
    def _publication_blockers(row: sqlite3.Row) -> list[str]:
        blockers: list[str] = []
        if "library_state" in row.keys() and row["library_state"] == "removed":
            blockers.append("题目已移出正常题库")
        if row["review_status"] != "approved":
            blockers.append("teacher_review_required")
        if row["verification_status"] != "passed":
            blockers.append("independent_verification_required")
        if not row["solution_approved"]:
            blockers.append("approved_original_solution_required")
        license_status = row["license_status"]
        if license_status in {"commercial_granted", "public_permissive"}:
            pass
        elif license_status == "question_content_user_declared_usable":
            if row["attribution_required"] not in {"false", "confirmed", "not_required"}:
                blockers.append("source_attribution_confirmation_required")
        else:
            blockers.append("commercial_rights_required")
        if row["status"] == "rejected":
            blockers.append("question_rejected")
        return blockers

    @staticmethod
    def _group_counts(connection: sqlite3.Connection, column: str) -> dict[str, int]:
        allowed = {"review_status", "verification_status", "chapter"}
        if column not in allowed:
            raise ValueError(column)
        return {
            str(row[0] or "未分类"): int(row[1])
            for row in connection.execute(
                f"SELECT {column}, COUNT(*) FROM questions GROUP BY {column} ORDER BY COUNT(*) DESC"
            ).fetchall()
        }

    @staticmethod
    def _normalize_answer(value: str) -> str:
        return "".join(value.replace("$", "").replace("\\,", "").split()).lower()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
