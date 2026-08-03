from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.modules.math_verifier import MathVerifier
from app.modules.question_bank.schemas import (
    CurationResult,
    ImportBatchView,
    ImportResult,
    PublishDecision,
    QuestionBankStats,
    QuestionDetail,
    QuestionSearchPage,
    QuestionSummary,
    ReviewCommand,
    ReviewResult,
)


class QuestionBankError(ValueError):
    pass


class QuestionBank:
    """Deep module for importing, reviewing, searching and publishing questions.

    SQLite and the source JSON shape stay behind this interface. Callers never
    write tables or derive publication rights themselves.
    """

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
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

                CREATE INDEX IF NOT EXISTS idx_questions_chapter ON questions(chapter);
                CREATE INDEX IF NOT EXISTS idx_questions_review ON questions(review_status);
                CREATE INDEX IF NOT EXISTS idx_questions_verification ON questions(verification_status);
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
        page: int = 1,
        page_size: int = 20,
    ) -> QuestionSearchPage:
        clauses: list[str] = []
        values: list[Any] = []
        if query.strip():
            pattern = f"%{query.strip()}%"
            clauses.append(
                "(stem_plain LIKE ? OR chapter LIKE ? OR section LIKE ? OR source_document LIKE ?)"
            )
            values.extend([pattern, pattern, pattern, pattern])
        for column, value in (
            ("chapter", chapter),
            ("difficulty", difficulty),
            ("verification_status", verification_status),
            ("review_status", review_status),
        ):
            if value is not None and value != "":
                clauses.append(f"{column} = ?")
                values.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        offset = (page - 1) * page_size
        with self._connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM questions {where}", values
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT * FROM questions {where}
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
                "SELECT * FROM questions WHERE question_id = ?", (question_id,)
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
        return QuestionDetail(
            **self._summary(row).model_dump(),
            raw=json.loads(row["raw_json"]),
            reviews=reviews,
        )

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
                "SELECT * FROM questions WHERE question_id = ?", (question_id,)
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
            review = self._group_counts(connection, "review_status")
            verification = self._group_counts(connection, "verification_status")
            chapters = self._group_counts(connection, "chapter")
            rows = connection.execute("SELECT * FROM questions").fetchall()
        publishable = sum(not self._publication_blockers(row) for row in rows)
        return QuestionBankStats(
            total=total,
            by_review_status=review,
            by_verification_status=verification,
            by_chapter=chapters,
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
        )

    @staticmethod
    def _publication_blockers(row: sqlite3.Row) -> list[str]:
        blockers: list[str] = []
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
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
