from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from pypdf import PdfReader
import pypdfium2 as pdfium

from .schemas import (
    BoundaryCandidateCreate,
    BoundaryCandidateList,
    BoundaryCandidateUpdate,
    BoundaryCandidateView,
    BoundaryProposalResult,
    ImportAnalysisResult,
    ImportBatchAnalysisResult,
    ImportBatchCommand,
    ImportBatchResult,
    ImportBatchSummary,
    ImportFileDetail,
    ImportFileSummary,
    ImportPageView,
    ImportWorkspace,
    ImportWorkspaceStats,
    StructuredDraftProposalResult,
    StructuredMediaReference,
    StructuredQuestionDraftList,
    StructuredQuestionDraftUpdate,
    StructuredQuestionDraftView,
    StructuredQuestionOption,
)


class PdfImportError(ValueError):
    pass


class PdfImportStudio:
    """Owns PDF batch intake, source integrity and page-level analysis."""

    MAX_FILES_PER_BATCH = 12
    MAX_FILE_BYTES = 100 * 1024 * 1024
    MAX_BATCH_BYTES = 350 * 1024 * 1024
    MAX_PDF_PAGES = 1200
    MIN_TEXT_LAYER_CHARS = 20

    _QUESTION_MARKERS = (
        re.compile(r"(?m)^\s*(?:例|题)?\s*\d{1,3}\s*[\.．、)]\s*"),
        re.compile(r"【\s*(?:例|题)\s*\d{1,3}\s*】"),
        re.compile(r"第\s*\d{1,3}\s*题"),
        re.compile(r"(?<!\d)\d{1,3}\s*[（(]\s*20\d{2}\s*[·•]")
    )

    def __init__(self, database_path: Path, file_root: Path) -> None:
        self.database_path = database_path.resolve()
        self.file_root = file_root.resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def create_batch(
        self,
        command: ImportBatchCommand,
        uploads: list[tuple[str, bytes]],
    ) -> ImportBatchResult:
        if not command.rights_acknowledged:
            raise PdfImportError("必须确认本批资料的来源与使用权声明")
        if not uploads:
            raise PdfImportError("请至少选择一份 PDF")
        if len(uploads) > self.MAX_FILES_PER_BATCH:
            raise PdfImportError(f"单个批次最多上传 {self.MAX_FILES_PER_BATCH} 份 PDF")
        if sum(len(content) for _, content in uploads) > self.MAX_BATCH_BYTES:
            raise PdfImportError("单个批次文件总量不能超过 350 MB")

        prepared = [self._prepare_upload(filename, content) for filename, content in uploads]
        digests = [item["sha256"] for item in prepared]
        if len(digests) != len(set(digests)):
            raise PdfImportError("本次选择中包含内容完全相同的重复 PDF")

        with self._connect() as connection:
            placeholders = ",".join("?" for _ in digests)
            duplicates = connection.execute(
                f"SELECT original_filename, sha256 FROM import_files WHERE sha256 IN ({placeholders})",
                digests,
            ).fetchall()
            if duplicates:
                names = "、".join(row["original_filename"] for row in duplicates)
                raise PdfImportError(f"以下 PDF 已登记，不能重复导入：{names}")

        batch_id = f"imp_batch_{uuid4().hex[:16]}"
        now = self._now()
        stored_paths: list[Path] = []
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO import_batches
                    (batch_id, title, rights_basis, rights_statement, owner_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id,
                        command.title.strip(),
                        command.rights_basis,
                        command.rights_statement.strip(),
                        command.owner_id,
                        now,
                        now,
                    ),
                )
                for item in prepared:
                    file_id = f"imp_file_{uuid4().hex[:16]}"
                    stored_name = f"{file_id}.pdf"
                    stored_path = self.file_root / stored_name
                    stored_path.write_bytes(item["content"])
                    stored_paths.append(stored_path)
                    connection.execute(
                        """
                        INSERT INTO import_files
                        (file_id, batch_id, original_filename, stored_name, size_bytes, sha256,
                         page_count, status, analyzed_page_count, text_page_count, scan_page_count,
                         extracted_character_count, question_marker_count, image_page_count,
                         embedded_image_count, warnings_json,
                         error_message, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'registered', 0, 0, 0, 0, 0, 0, 0, '[]', '', ?, ?)
                        """,
                        (
                            file_id,
                            batch_id,
                            item["filename"],
                            stored_name,
                            item["size_bytes"],
                            item["sha256"],
                            item["page_count"],
                            now,
                            now,
                        ),
                    )
        except Exception:
            for path in stored_paths:
                path.unlink(missing_ok=True)
            raise
        return ImportBatchResult(
            batch=self._batch(batch_id, include_files=True),
            message=f"已登记 {len(prepared)} 份 PDF；分析前不会生成拆题候选。",
        )

    def workspace(self, *, limit: int = 30) -> ImportWorkspace:
        with self._connect() as connection:
            batch_rows = connection.execute(
                "SELECT batch_id FROM import_batches ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            values = connection.execute(
                """
                SELECT COUNT(DISTINCT batch_id) AS batches, COUNT(*) AS files,
                       COALESCE(SUM(page_count), 0) AS pages,
                       COALESCE(SUM(CASE WHEN status = 'ready_for_segmentation' THEN 1 ELSE 0 END), 0) AS ready_files,
                       COALESCE(SUM(scan_page_count), 0) AS scan_pages,
                       COALESCE(SUM(question_marker_count), 0) AS question_markers
                FROM import_files
                """
            ).fetchone()
        return ImportWorkspace(
            stats=ImportWorkspaceStats(**dict(values)),
            batches=[self._batch(row["batch_id"], include_files=True) for row in batch_rows],
        )

    def inspect(self, file_id: str) -> ImportFileDetail:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM import_files WHERE file_id = ?", (file_id,)
            ).fetchone()
            if row is None:
                raise KeyError(file_id)
            pages = connection.execute(
                "SELECT * FROM import_pages WHERE file_id = ? ORDER BY page_number", (file_id,)
            ).fetchall()
        return ImportFileDetail(
            **self._file(row).model_dump(),
            pages=[self._page(page) for page in pages],
        )

    def analyze(self, file_id: str) -> ImportAnalysisResult:
        source_path, file = self.source_file(file_id)
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE import_files SET status = 'analyzing', error_message = '', updated_at = ? WHERE file_id = ?",
                (now, file_id),
            )
        try:
            reader = PdfReader(source_path)
            page_records = []
            text_pages = 0
            scan_pages = 0
            total_chars = 0
            total_markers = 0
            image_pages = 0
            total_images = 0
            file_warnings: list[str] = []
            for index, page in enumerate(reader.pages, start=1):
                text = (page.extract_text() or "").strip()
                char_count = len(text)
                markers = self._marker_count(text)
                try:
                    image_count = len(page.images)
                except Exception:
                    image_count = 0
                if image_count:
                    image_pages += 1
                    total_images += image_count
                has_text = char_count >= self.MIN_TEXT_LAYER_CHARS
                warnings: list[str] = []
                if has_text:
                    text_pages += 1
                else:
                    scan_pages += 1
                    warnings.append("本页文字层不足，需要 OCR 或人工转录")
                total_chars += char_count
                total_markers += markers
                box = page.mediabox
                page_records.append(
                    (
                        f"{file_id}_p{index:04d}",
                        file_id,
                        index,
                        float(box.width),
                        float(box.height),
                        text,
                        char_count,
                        markers,
                        image_count,
                        int(has_text),
                        json.dumps(warnings, ensure_ascii=False),
                    )
                )
            if scan_pages:
                file_warnings.append(f"{scan_pages} 页文字层不足，后续需要 OCR 或人工转录")
            if total_markers == 0:
                file_warnings.append("未识别到稳定题号，拆题时需要人工标记边界")
            with self._connect() as connection:
                connection.execute("DELETE FROM import_pages WHERE file_id = ?", (file_id,))
                connection.executemany(
                    """
                    INSERT INTO import_pages
                    (page_id, file_id, page_number, width_points, height_points, extracted_text,
                     character_count, question_marker_count, embedded_image_count,
                     has_text_layer, warnings_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    page_records,
                )
                connection.execute(
                    """
                    UPDATE import_files SET status = 'ready_for_segmentation', analyzed_page_count = ?,
                        text_page_count = ?, scan_page_count = ?, extracted_character_count = ?,
                        question_marker_count = ?, image_page_count = ?, embedded_image_count = ?,
                        warnings_json = ?, error_message = '', updated_at = ?
                    WHERE file_id = ?
                    """,
                    (
                        len(page_records), text_pages, scan_pages, total_chars, total_markers,
                        image_pages, total_images,
                        json.dumps(file_warnings, ensure_ascii=False), self._now(), file_id,
                    ),
                )
                connection.execute(
                    "UPDATE import_batches SET updated_at = ? WHERE batch_id = ?",
                    (self._now(), file.batch_id),
                )
        except Exception as exc:
            with self._connect() as connection:
                connection.execute(
                    "UPDATE import_files SET status = 'failed', error_message = ?, updated_at = ? WHERE file_id = ?",
                    (str(exc)[:1000], self._now(), file_id),
                )
            raise PdfImportError(f"PDF 分析失败：{exc}") from exc
        result = self.inspect(file_id)
        return ImportAnalysisResult(
            file=result,
            message=f"已分析 {result.analyzed_page_count} 页，识别 {result.question_marker_count} 个题号标记。",
        )

    def analyze_batch(self, batch_id: str) -> ImportBatchAnalysisResult:
        batch = self._batch(batch_id, include_files=True)
        analyzed = 0
        failed = 0
        for file in batch.files:
            try:
                self.analyze(file.file_id)
                analyzed += 1
            except PdfImportError:
                failed += 1
        refreshed = self._batch(batch_id, include_files=True)
        return ImportBatchAnalysisResult(
            batch=refreshed,
            analyzed_count=analyzed,
            failed_count=failed,
            message=f"批次分析完成：成功 {analyzed} 份，失败 {failed} 份。",
        )

    def boundary_candidates(self, file_id: str) -> BoundaryCandidateList:
        file = self.inspect(file_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM import_boundary_candidates
                WHERE file_id = ? ORDER BY position, created_at
                """,
                (file_id,),
            ).fetchall()
        items = [self._candidate(row) for row in rows]
        return BoundaryCandidateList(
            file_id=file_id,
            source_analysis_updated_at=file.updated_at,
            total=len(items),
            draft_count=sum(item.status == "draft" for item in items),
            confirmed_count=sum(item.status == "confirmed" for item in items),
            discarded_count=sum(item.status == "discarded" for item in items),
            items=items,
        )

    def propose_boundary_candidates(self, file_id: str) -> BoundaryProposalResult:
        file = self.inspect(file_id)
        if file.status != "ready_for_segmentation":
            raise PdfImportError("请先完成逐页分析，再生成题目边界候选")
        existing = self.boundary_candidates(file_id)
        if existing.total:
            return BoundaryProposalResult(
                candidates=existing,
                created_count=0,
                message="已有题目边界候选，为保护教师修改，本次未覆盖。",
            )

        records: list[dict] = []
        for page in file.pages:
            text = page.extracted_text.strip()
            if not text:
                continue
            spans = self._marker_spans(text)
            if not spans:
                if records:
                    records[-1]["stem_text"] = self._join_text(records[-1]["stem_text"], text)
                    records[-1]["end_page"] = page.page_number
                    records[-1]["end_offset"] = len(text)
                continue
            first_start = spans[0][0]
            if records and first_start:
                records[-1]["stem_text"] = self._join_text(
                    records[-1]["stem_text"], text[:first_start].strip()
                )
                records[-1]["end_page"] = page.page_number
                records[-1]["end_offset"] = first_start
            for index, (start, _marker_end) in enumerate(spans):
                end = spans[index + 1][0] if index + 1 < len(spans) else len(text)
                stem = text[start:end].strip()
                if stem:
                    records.append(
                        {
                            "start_page": page.page_number,
                            "end_page": page.page_number,
                            "start_offset": start,
                            "end_offset": end,
                            "stem_text": stem,
                        }
                    )

        now = self._now()
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO import_boundary_candidates
                (candidate_id, file_id, source_analysis_updated_at, position,
                 start_page, end_page, start_offset, end_offset, stem_text,
                 question_type, subquestion_count, status, note, editor_id,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', '',
                        'system_proposal', ?, ?)
                """,
                [
                    (
                        f"imp_boundary_{uuid4().hex[:16]}",
                        file_id,
                        file.updated_at,
                        position,
                        record["start_page"],
                        record["end_page"],
                        record["start_offset"],
                        record["end_offset"],
                        record["stem_text"],
                        self._infer_question_type(record["stem_text"]),
                        self._infer_subquestion_count(record["stem_text"]),
                        now,
                        now,
                    )
                    for position, record in enumerate(records, start=1)
                ],
            )
        candidates = self.boundary_candidates(file_id)
        return BoundaryProposalResult(
            candidates=candidates,
            created_count=len(records),
            message=f"已生成 {len(records)} 个题目边界候选，确认前不会进入正式题库。",
        )

    def create_boundary_candidate(
        self, file_id: str, command: BoundaryCandidateCreate
    ) -> BoundaryCandidateView:
        file = self.inspect(file_id)
        if file.status != "ready_for_segmentation":
            raise PdfImportError("请先完成逐页分析，再手动补充题目边界")
        self._validate_page_range(file.page_count, command.start_page, command.end_page)
        now = self._now()
        candidate_id = f"imp_boundary_{uuid4().hex[:16]}"
        with self._connect() as connection:
            position = connection.execute(
                """
                SELECT COALESCE(MAX(position), 0) + 1
                FROM import_boundary_candidates WHERE file_id = ?
                """,
                (file_id,),
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO import_boundary_candidates
                (candidate_id, file_id, source_analysis_updated_at, position,
                 start_page, end_page, start_offset, end_offset, stem_text,
                 question_type, subquestion_count, status, note, editor_id,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, 'draft', ?, ?, ?, ?)
                """,
                (
                    candidate_id, file_id, file.updated_at, position,
                    command.start_page, command.end_page, command.stem_text.strip(),
                    command.question_type, command.subquestion_count,
                    command.note.strip(), command.editor_id, now, now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM import_boundary_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        return self._candidate(row)

    def update_boundary_candidate(
        self, file_id: str, candidate_id: str, command: BoundaryCandidateUpdate
    ) -> BoundaryCandidateView:
        file = self.inspect(file_id)
        self._validate_page_range(file.page_count, command.start_page, command.end_page)
        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT candidate_id FROM import_boundary_candidates
                WHERE candidate_id = ? AND file_id = ?
                """,
                (candidate_id, file_id),
            ).fetchone()
            if existing is None:
                raise KeyError(candidate_id)
            connection.execute(
                """
                UPDATE import_boundary_candidates
                SET start_page = ?, end_page = ?, stem_text = ?, question_type = ?,
                    subquestion_count = ?, status = ?, note = ?, editor_id = ?, updated_at = ?
                WHERE candidate_id = ? AND file_id = ?
                """,
                (
                    command.start_page, command.end_page, command.stem_text.strip(),
                    command.question_type, command.subquestion_count, command.status,
                    command.note.strip(), command.editor_id, self._now(), candidate_id, file_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM import_boundary_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        return self._candidate(row)

    def structured_question_drafts(self, file_id: str) -> StructuredQuestionDraftList:
        self.inspect(file_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM import_structured_question_drafts
                WHERE file_id = ? ORDER BY position, created_at
                """,
                (file_id,),
            ).fetchall()
        items = [self._structured_draft(row) for row in rows]
        return StructuredQuestionDraftList(
            file_id=file_id,
            total=len(items),
            draft_count=sum(item.status == "draft" for item in items),
            confirmed_count=sum(item.status == "confirmed" for item in items),
            imported_count=sum(item.status == "imported" for item in items),
            items=items,
        )

    def propose_structured_question_drafts(self, file_id: str) -> StructuredDraftProposalResult:
        file = self.inspect(file_id)
        existing = self.structured_question_drafts(file_id)
        confirmed_boundary_ids = {
            item.candidate_id
            for item in self.boundary_candidates(file_id).items
            if item.status == "confirmed"
        }
        existing_boundary_ids = {item.boundary_candidate_id for item in existing.items}
        pending_ids = confirmed_boundary_ids - existing_boundary_ids
        if not confirmed_boundary_ids:
            raise PdfImportError("请先至少确认一道题的边界，再生成结构化草稿")
        if not pending_ids:
            return StructuredDraftProposalResult(
                drafts=existing,
                created_count=0,
                message="所有已确认边界都已有结构化草稿，本次未覆盖教师修改。",
            )

        boundaries = [
            item for item in self.boundary_candidates(file_id).items
            if item.candidate_id in pending_ids
        ]
        now = self._now()
        records = []
        for boundary in boundaries:
            parsed = self._structure_boundary_text(boundary.stem_text, boundary.question_type)
            image_pages = [
                page.page_number for page in file.pages
                if boundary.start_page <= page.page_number <= boundary.end_page
                and page.embedded_image_count > 0
            ]
            warnings = list(parsed["warnings"])
            media = []
            if image_pages:
                warnings.append("来源页包含图片，请确认图片归属并在题库审核台裁剪或替换")
                media = [
                    StructuredMediaReference(
                        page_number=page_number,
                        placement="stem",
                        note="来源页检测到内嵌图片，尚未完成题目级裁剪",
                    ).model_dump()
                    for page_number in image_pages
                ]
            records.append(
                (
                    f"imp_draft_{uuid4().hex[:16]}", file_id, boundary.candidate_id,
                    boundary.position, boundary.start_page, boundary.end_page,
                    boundary.stem_text, boundary.question_type, parsed["stem_plain"],
                    None, json.dumps(parsed["options"], ensure_ascii=False), None,
                    "待独立编写", "[]", None, 3, parsed["formula_status"],
                    json.dumps(media, ensure_ascii=False), "draft",
                    json.dumps(warnings, ensure_ascii=False), "", "system_proposal",
                    now, now,
                )
            )
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO import_structured_question_drafts
                (draft_id, file_id, boundary_candidate_id, position, start_page, end_page,
                 source_text, question_type, stem_plain, stem_latex, options_json,
                 answer_value, solution_method, solution_steps_json, final_answer,
                 difficulty, formula_status, media_references_json, status, warnings_json,
                 note, editor_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )
        drafts = self.structured_question_drafts(file_id)
        return StructuredDraftProposalResult(
            drafts=drafts,
            created_count=len(records),
            message=f"已从 {len(records)} 个确认边界生成结构化草稿；请逐题校对公式、选项和图片归属。",
        )

    def update_structured_question_draft(
        self, file_id: str, draft_id: str, command: StructuredQuestionDraftUpdate
    ) -> StructuredQuestionDraftView:
        file = self.inspect(file_id)
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM import_structured_question_drafts
                   WHERE file_id = ? AND draft_id = ?""",
                (file_id, draft_id),
            ).fetchone()
            if row is None:
                raise KeyError(draft_id)
            if row["status"] == "imported":
                raise PdfImportError("已导入题库的草稿不能在加工区继续修改，请前往题库审核台修订")
            self._validate_structured_draft(file.page_count, command)
            connection.execute(
                """
                UPDATE import_structured_question_drafts
                SET question_type = ?, stem_plain = ?, stem_latex = ?, options_json = ?,
                    answer_value = ?, solution_method = ?, solution_steps_json = ?,
                    final_answer = ?, difficulty = ?, formula_status = ?,
                    media_references_json = ?, status = ?, note = ?, editor_id = ?, updated_at = ?
                WHERE file_id = ? AND draft_id = ?
                """,
                (
                    command.question_type, command.stem_plain.strip(),
                    command.stem_latex.strip() if command.stem_latex else None,
                    json.dumps([item.model_dump() for item in command.options], ensure_ascii=False),
                    command.answer_value.strip() if command.answer_value else None,
                    command.solution_method.strip(),
                    json.dumps([step.strip() for step in command.solution_steps if step.strip()], ensure_ascii=False),
                    command.final_answer.strip() if command.final_answer else None,
                    command.difficulty, command.formula_status,
                    json.dumps([item.model_dump() for item in command.media_references], ensure_ascii=False),
                    command.status, command.note.strip(), command.editor_id, self._now(),
                    file_id, draft_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM import_structured_question_drafts WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
        return self._structured_draft(updated)

    def mark_structured_draft_imported(
        self, file_id: str, draft_id: str, question_id: str
    ) -> StructuredQuestionDraftView:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM import_structured_question_drafts
                   WHERE file_id = ? AND draft_id = ?""",
                (file_id, draft_id),
            ).fetchone()
            if row is None:
                raise KeyError(draft_id)
            if row["status"] not in {"confirmed", "imported"}:
                raise PdfImportError("结构化草稿必须先由教师确认，才能进入题库审核")
            existing_id = row["imported_question_id"]
            if existing_id and existing_id != question_id:
                raise PdfImportError("结构化草稿已经关联其他题库题目")
            connection.execute(
                """UPDATE import_structured_question_drafts
                   SET status = 'imported', imported_question_id = ?, updated_at = ?
                   WHERE file_id = ? AND draft_id = ?""",
                (question_id, self._now(), file_id, draft_id),
            )
            updated = connection.execute(
                "SELECT * FROM import_structured_question_drafts WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
        return self._structured_draft(updated)

    def source_file(self, file_id: str) -> tuple[Path, ImportFileSummary]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM import_files WHERE file_id = ?", (file_id,)
            ).fetchone()
        if row is None:
            raise KeyError(file_id)
        path = (self.file_root / row["stored_name"]).resolve()
        if path.parent != self.file_root or not path.exists():
            raise PdfImportError("PDF 原文件不存在或存储路径异常")
        return path, self._file(row)

    def preview_page(self, file_id: str, page_number: int, *, width: int = 1200) -> Path:
        source_path, file = self.source_file(file_id)
        if page_number < 1 or page_number > file.page_count:
            raise PdfImportError(f"页码必须在 1 到 {file.page_count} 之间")
        safe_width = min(1800, max(600, width))
        preview_root = (self.file_root / "previews" / file_id).resolve()
        if self.file_root not in preview_root.parents:
            raise PdfImportError("页面预览存储路径异常")
        preview_root.mkdir(parents=True, exist_ok=True)
        output = preview_root / f"page-{page_number:04d}-w{safe_width}.png"
        if output.exists() and output.stat().st_mtime >= source_path.stat().st_mtime:
            return output
        document = pdfium.PdfDocument(source_path)
        try:
            page = document[page_number - 1]
            page_width, _ = page.get_size()
            bitmap = page.render(scale=safe_width / max(1.0, page_width))
            bitmap.to_pil().save(output, format="PNG", optimize=True)
        except Exception as exc:
            output.unlink(missing_ok=True)
            raise PdfImportError(f"第 {page_number} 页预览生成失败：{exc}") from exc
        finally:
            document.close()
        return output

    def _prepare_upload(self, filename: str, content: bytes) -> dict:
        safe_filename = Path(filename or "未命名.pdf").name
        if not safe_filename.lower().endswith(".pdf") or not content.startswith(b"%PDF-"):
            raise PdfImportError(f"《{safe_filename}》不是有效 PDF")
        if not content:
            raise PdfImportError(f"《{safe_filename}》为空文件")
        if len(content) > self.MAX_FILE_BYTES:
            raise PdfImportError(f"《{safe_filename}》超过 100 MB")
        try:
            reader = PdfReader(BytesIO(content))
            if reader.is_encrypted:
                raise PdfImportError(f"《{safe_filename}》已加密，请先解除密码")
            page_count = len(reader.pages)
            if page_count < 1:
                raise PdfImportError(f"《{safe_filename}》没有可读取页面")
            if page_count > self.MAX_PDF_PAGES:
                raise PdfImportError(f"《{safe_filename}》超过 {self.MAX_PDF_PAGES} 页")
        except PdfImportError:
            raise
        except Exception as exc:
            raise PdfImportError(f"《{safe_filename}》损坏或无法读取：{exc}") from exc
        return {
            "filename": safe_filename,
            "content": content,
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "page_count": page_count,
        }

    def _batch(self, batch_id: str, *, include_files: bool) -> ImportBatchSummary:
        with self._connect() as connection:
            batch = connection.execute(
                "SELECT * FROM import_batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            if batch is None:
                raise KeyError(batch_id)
            rows = connection.execute(
                "SELECT * FROM import_files WHERE batch_id = ? ORDER BY created_at, original_filename",
                (batch_id,),
            ).fetchall()
        files = [self._file(row) for row in rows]
        return ImportBatchSummary(
            batch_id=batch_id,
            title=batch["title"],
            rights_basis=batch["rights_basis"],
            rights_statement=batch["rights_statement"],
            owner_id=batch["owner_id"],
            file_count=len(files),
            registered_count=sum(item.status == "registered" for item in files),
            ready_count=sum(item.status == "ready_for_segmentation" for item in files),
            failed_count=sum(item.status == "failed" for item in files),
            page_count=sum(item.page_count for item in files),
            question_marker_count=sum(item.question_marker_count for item in files),
            created_at=batch["created_at"],
            updated_at=batch["updated_at"],
            files=files if include_files else [],
        )

    @staticmethod
    def _file(row: sqlite3.Row) -> ImportFileSummary:
        return ImportFileSummary(
            file_id=row["file_id"], batch_id=row["batch_id"],
            original_filename=row["original_filename"], size_bytes=row["size_bytes"],
            sha256=row["sha256"], page_count=row["page_count"], status=row["status"],
            analyzed_page_count=row["analyzed_page_count"], text_page_count=row["text_page_count"],
            scan_page_count=row["scan_page_count"], extracted_character_count=row["extracted_character_count"],
            question_marker_count=row["question_marker_count"],
            image_page_count=row["image_page_count"],
            embedded_image_count=row["embedded_image_count"],
            warnings=json.loads(row["warnings_json"]), error_message=row["error_message"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    @staticmethod
    def _page(row: sqlite3.Row) -> ImportPageView:
        return ImportPageView(
            page_id=row["page_id"], page_number=row["page_number"],
            width_points=row["width_points"], height_points=row["height_points"],
            extracted_text=row["extracted_text"], character_count=row["character_count"],
            question_marker_count=row["question_marker_count"],
            embedded_image_count=row["embedded_image_count"],
            has_text_layer=bool(row["has_text_layer"]), warnings=json.loads(row["warnings_json"]),
        )

    @classmethod
    def _marker_count(cls, text: str) -> int:
        return max((len(pattern.findall(text)) for pattern in cls._QUESTION_MARKERS), default=0)

    @classmethod
    def _marker_spans(cls, text: str) -> list[tuple[int, int]]:
        matches = sorted(
            (match.start(), match.end())
            for pattern in cls._QUESTION_MARKERS
            for match in pattern.finditer(text)
        )
        deduplicated: list[tuple[int, int]] = []
        for start, end in matches:
            if deduplicated and start <= deduplicated[-1][1]:
                previous_start, previous_end = deduplicated[-1]
                deduplicated[-1] = (previous_start, max(previous_end, end))
            else:
                deduplicated.append((start, end))
        return deduplicated

    @staticmethod
    def _join_text(left: str, right: str) -> str:
        return "\n".join(part for part in (left.strip(), right.strip()) if part)

    @staticmethod
    def _infer_question_type(text: str) -> str:
        option_count = len(set(re.findall(r"(?m)(?:^|\s)([A-D])[\.．、)]", text)))
        if option_count >= 4:
            return "single_choice"
        if re.search(r"填空|横线上|_____", text):
            return "fill_blank"
        if re.search(r"证明|求证|解答|求|计算|说明理由", text):
            return "open_response"
        return "unknown"

    @staticmethod
    def _infer_subquestion_count(text: str) -> int:
        values = {
            int(value)
            for value in re.findall(r"(?<!\d)[（(]\s*(\d{1,2})\s*[）)]", text)
            if 0 < int(value) <= 20
        }
        return max(values, default=0)

    @staticmethod
    def _candidate(row: sqlite3.Row) -> BoundaryCandidateView:
        return BoundaryCandidateView(
            candidate_id=row["candidate_id"], file_id=row["file_id"],
            position=row["position"], start_page=row["start_page"], end_page=row["end_page"],
            stem_text=row["stem_text"], question_type=row["question_type"],
            subquestion_count=row["subquestion_count"], status=row["status"],
            note=row["note"], editor_id=row["editor_id"],
            source_analysis_updated_at=row["source_analysis_updated_at"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    @staticmethod
    def _structured_draft(row: sqlite3.Row) -> StructuredQuestionDraftView:
        return StructuredQuestionDraftView(
            draft_id=row["draft_id"], file_id=row["file_id"],
            boundary_candidate_id=row["boundary_candidate_id"], position=row["position"],
            start_page=row["start_page"], end_page=row["end_page"],
            source_text=row["source_text"], question_type=row["question_type"],
            stem_plain=row["stem_plain"], stem_latex=row["stem_latex"],
            options=[StructuredQuestionOption(**item) for item in json.loads(row["options_json"])],
            answer_value=row["answer_value"], solution_method=row["solution_method"],
            solution_steps=json.loads(row["solution_steps_json"]),
            final_answer=row["final_answer"], difficulty=row["difficulty"],
            formula_status=row["formula_status"],
            media_references=[
                StructuredMediaReference(**item)
                for item in json.loads(row["media_references_json"])
            ],
            status=row["status"], warnings=json.loads(row["warnings_json"]),
            note=row["note"], editor_id=row["editor_id"],
            imported_question_id=row["imported_question_id"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    @classmethod
    def _structure_boundary_text(cls, source_text: str, question_type: str) -> dict:
        text = source_text.strip()
        answer_marker = re.search(r"(?mi)^\s*(?:【?(?:答案|解析|分析|详解)】?|Answer)\s*[:：]?", text)
        question_text = text[:answer_marker.start()].strip() if answer_marker else text
        option_pattern = re.compile(
            r"(?ms)(?:^|\s)([A-H])\s*[\.．、)]\s*(.*?)(?=(?:\s+[A-H]\s*[\.．、)]\s)|\Z)"
        )
        matches = list(option_pattern.finditer(question_text))
        options = [
            {"key": match.group(1), "text": re.sub(r"\s+", " ", match.group(2)).strip()}
            for match in matches
        ]
        if matches:
            stem_plain = question_text[:matches[0].start()].strip()
        else:
            stem_plain = question_text
        stem_plain = re.sub(r"^\s*(?:例|题)?\s*\d{1,3}\s*[\.．、)]\s*", "", stem_plain).strip()
        warnings: list[str] = []
        if answer_marker:
            warnings.append("已将原答案或解析段隔离；解析需独立编写并核验")
        if question_type in {"single_choice", "multiple_choice"} and len(options) < 2:
            warnings.append("未稳定拆出选择题选项，请对照原页手工补充")
        if not stem_plain:
            stem_plain = question_text
            warnings.append("未稳定分离题干，请手工整理")
        formula_status = "needs_review" if re.search(r"[�□■]|[A-Za-z]\s*[=<>≤≥]|[∑√∞∈∪∩]", question_text) else "pending"
        if formula_status == "needs_review":
            warnings.append("检测到公式或异常字形，必须对照原页完成 LaTeX 校正")
        return {
            "stem_plain": stem_plain,
            "options": options,
            "formula_status": formula_status,
            "warnings": warnings,
        }

    @staticmethod
    def _validate_structured_draft(
        page_count: int, command: StructuredQuestionDraftUpdate
    ) -> None:
        if command.status == "imported":
            raise PdfImportError("不能通过编辑接口伪造已入库状态")
        keys = [item.key.strip().upper() for item in command.options]
        if any(not key for key in keys) or len(keys) != len(set(keys)):
            raise PdfImportError("选项编号不能为空或重复")
        if command.question_type in {"single_choice", "multiple_choice"} and len(keys) < 2:
            raise PdfImportError("选择题至少需要两个选项")
        if command.status == "confirmed":
            if command.question_type == "unknown":
                raise PdfImportError("确认结构化草稿前必须选择题型")
            if command.formula_status != "confirmed":
                raise PdfImportError("确认结构化草稿前必须完成公式校对")
        for item in command.media_references:
            if item.page_number > page_count:
                raise PdfImportError(f"图片来源页必须在 1 到 {page_count} 之间")

    @staticmethod
    def _validate_page_range(page_count: int, start_page: int, end_page: int) -> None:
        if start_page > end_page:
            raise PdfImportError("结束页不能早于起始页")
        if end_page > page_count:
            raise PdfImportError(f"页码必须在 1 到 {page_count} 之间")

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS import_batches (
                    batch_id TEXT PRIMARY KEY, title TEXT NOT NULL, rights_basis TEXT NOT NULL,
                    rights_statement TEXT NOT NULL, owner_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS import_files (
                    file_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, original_filename TEXT NOT NULL,
                    stored_name TEXT NOT NULL, size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL UNIQUE,
                    page_count INTEGER NOT NULL, status TEXT NOT NULL, analyzed_page_count INTEGER NOT NULL,
                    text_page_count INTEGER NOT NULL, scan_page_count INTEGER NOT NULL,
                    extracted_character_count INTEGER NOT NULL, question_marker_count INTEGER NOT NULL,
                    image_page_count INTEGER NOT NULL, embedded_image_count INTEGER NOT NULL,
                    warnings_json TEXT NOT NULL, error_message TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(batch_id) REFERENCES import_batches(batch_id)
                );
                CREATE INDEX IF NOT EXISTS idx_import_files_batch ON import_files(batch_id);
                CREATE TABLE IF NOT EXISTS import_pages (
                    page_id TEXT PRIMARY KEY, file_id TEXT NOT NULL, page_number INTEGER NOT NULL,
                    width_points REAL NOT NULL, height_points REAL NOT NULL, extracted_text TEXT NOT NULL,
                    character_count INTEGER NOT NULL, question_marker_count INTEGER NOT NULL,
                    embedded_image_count INTEGER NOT NULL,
                    has_text_layer INTEGER NOT NULL, warnings_json TEXT NOT NULL,
                    FOREIGN KEY(file_id) REFERENCES import_files(file_id), UNIQUE(file_id, page_number)
                );
                CREATE INDEX IF NOT EXISTS idx_import_pages_file ON import_pages(file_id, page_number);
                CREATE TABLE IF NOT EXISTS import_boundary_candidates (
                    candidate_id TEXT PRIMARY KEY, file_id TEXT NOT NULL,
                    source_analysis_updated_at TEXT NOT NULL, position INTEGER NOT NULL,
                    start_page INTEGER NOT NULL, end_page INTEGER NOT NULL,
                    start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL,
                    stem_text TEXT NOT NULL, question_type TEXT NOT NULL,
                    subquestion_count INTEGER NOT NULL, status TEXT NOT NULL,
                    note TEXT NOT NULL, editor_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(file_id) REFERENCES import_files(file_id),
                    UNIQUE(file_id, position)
                );
                CREATE INDEX IF NOT EXISTS idx_import_boundaries_file
                    ON import_boundary_candidates(file_id, position);
                CREATE TABLE IF NOT EXISTS import_structured_question_drafts (
                    draft_id TEXT PRIMARY KEY, file_id TEXT NOT NULL,
                    boundary_candidate_id TEXT NOT NULL UNIQUE, position INTEGER NOT NULL,
                    start_page INTEGER NOT NULL, end_page INTEGER NOT NULL,
                    source_text TEXT NOT NULL, question_type TEXT NOT NULL,
                    stem_plain TEXT NOT NULL, stem_latex TEXT,
                    options_json TEXT NOT NULL, answer_value TEXT,
                    solution_method TEXT NOT NULL, solution_steps_json TEXT NOT NULL,
                    final_answer TEXT, difficulty INTEGER NOT NULL,
                    formula_status TEXT NOT NULL, media_references_json TEXT NOT NULL,
                    status TEXT NOT NULL, warnings_json TEXT NOT NULL,
                    note TEXT NOT NULL, editor_id TEXT NOT NULL,
                    imported_question_id TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(file_id) REFERENCES import_files(file_id),
                    FOREIGN KEY(boundary_candidate_id) REFERENCES import_boundary_candidates(candidate_id),
                    UNIQUE(file_id, position)
                );
                CREATE INDEX IF NOT EXISTS idx_import_structured_drafts_file
                    ON import_structured_question_drafts(file_id, position);
                """
            )
            self._ensure_column(connection, "import_files", "image_page_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "import_files", "embedded_image_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "import_pages", "embedded_image_count", "INTEGER NOT NULL DEFAULT 0")

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
