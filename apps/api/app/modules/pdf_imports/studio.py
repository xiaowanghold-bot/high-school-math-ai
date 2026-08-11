from __future__ import annotations

import hashlib
import csv
import json
import re
import sqlite3
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

from pypdf import PdfReader
import pypdfium2 as pdfium
from PIL import Image

from .schemas import (
    BoundaryCandidateCreate,
    BoundaryCandidateList,
    BoundaryCandidateUpdate,
    BoundaryCandidateView,
    BoundaryProposalResult,
    ImportAnalysisResult,
    ImportBatchAnalysisResult,
    ImportBatchQueueResult,
    ImportBatchCommand,
    ImportBatchResult,
    ImportBatchSummary,
    ImportFileDetail,
    ImportFileSummary,
    ImportPageView,
    ImportQueueStepResult,
    ImportWorkspace,
    ImportWorkspaceStats,
    StructuredDraftProposalResult,
    StructuredDraftRepairResult,
    StructuredFormulaCheck,
    StructuredFormulaIssue,
    StructuredFormulaReviewCommand,
    StructuredMediaCropCommand,
    StructuredMediaCropView,
    StructuredMediaReference,
    StructuredQuestionDraftList,
    StructuredQuestionDraftUpdate,
    StructuredQuestionDraftView,
    StructuredQuestionOption,
)
from .text_repair import needs_math_ocr, repair_structured_text


class PdfImportError(ValueError):
    pass


class PdfImportStudio:
    """Owns PDF batch intake, source integrity and page-level analysis."""

    MAX_FILES_PER_BATCH = 12
    MAX_FILE_BYTES = 100 * 1024 * 1024
    MAX_BATCH_BYTES = 350 * 1024 * 1024
    MAX_PDF_PAGES = 1200
    MIN_TEXT_LAYER_CHARS = 20
    MAX_CROPS_PER_DRAFT = 8
    CROP_RENDER_WIDTH = 1800

    _QUESTION_MARKERS = (
        re.compile(r"(?m)^\s*(?:例|题)?\s*\d{1,3}\s*[\.．、)]\s*"),
        re.compile(r"【\s*(?:例|题)\s*\d{1,3}\s*】"),
        re.compile(r"第\s*\d{1,3}\s*题"),
        re.compile(r"(?<!\d)\d{1,3}\s*[（(]\s*20\d{2}\s*[·•]")
    )

    def __init__(
        self,
        database_path: Path,
        file_root: Path,
        question_estimates_path: Path | None = None,
    ) -> None:
        self.database_path = database_path.resolve()
        self.file_root = file_root.resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_root.mkdir(parents=True, exist_ok=True)
        self.question_estimates = self._load_question_estimates(question_estimates_path)
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
                         page_count, status, analysis_attempts, estimated_question_count,
                         analyzed_page_count, text_page_count, scan_page_count,
                         extracted_character_count, question_marker_count, image_page_count,
                         embedded_image_count, warnings_json,
                         error_message, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'registered', 0, ?, 0, 0, 0, 0, 0, 0, 0, '[]', '', ?, ?)
                        """,
                        (
                            file_id,
                            batch_id,
                            item["filename"],
                            stored_name,
                            item["size_bytes"],
                            item["sha256"],
                            item["page_count"],
                            self.question_estimates.get(item["filename"], 0),
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
                       COALESCE(SUM(analyzed_page_count), 0) AS analyzed_pages,
                       COALESCE(SUM(CASE WHEN status = 'ready_for_segmentation' THEN 1 ELSE 0 END), 0) AS ready_files,
                       COALESCE(SUM(CASE WHEN status IN ('queued', 'analyzing') THEN 1 ELSE 0 END), 0) AS queued_files,
                       COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_files,
                       COALESCE(SUM(scan_page_count), 0) AS scan_pages,
                       COALESCE(SUM(question_marker_count), 0) AS question_markers,
                       COALESCE(SUM(estimated_question_count), 0) AS estimated_questions
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

    def analyze(
        self,
        file_id: str,
        *,
        page_budget: int | None = None,
        force: bool = False,
    ) -> ImportAnalysisResult:
        """Analyze a PDF with durable page checkpoints and safe resume semantics."""
        source_path, file = self.source_file(file_id)
        if page_budget is not None and not 1 <= page_budget <= 200:
            raise PdfImportError("单次分析页数必须在 1 到 200 之间")
        if file.status == "ready_for_segmentation" and not force:
            return ImportAnalysisResult(
                file=self.inspect(file_id),
                message="该文件已经完成逐页分析，本次未重复处理。",
            )

        if force:
            with self._connect() as connection:
                connection.execute("DELETE FROM import_pages WHERE file_id = ?", (file_id,))
                connection.execute(
                    """
                    UPDATE import_files SET status = 'registered', analyzed_page_count = 0,
                        text_page_count = 0, scan_page_count = 0,
                        extracted_character_count = 0, question_marker_count = 0,
                        image_page_count = 0, embedded_image_count = 0,
                        warnings_json = '[]', error_message = '', updated_at = ?
                    WHERE file_id = ?
                    """,
                    (self._now(), file_id),
                )
            file = self.inspect(file_id)

        with self._connect() as connection:
            last_page = connection.execute(
                "SELECT COALESCE(MAX(page_number), 0) AS value FROM import_pages WHERE file_id = ?",
                (file_id,),
            ).fetchone()["value"]
            connection.execute(
                """
                UPDATE import_files SET status = 'analyzing', analysis_attempts = analysis_attempts + 1,
                    error_message = '', updated_at = ? WHERE file_id = ?
                """,
                (self._now(), file_id),
            )

        processed_this_run = 0
        try:
            reader = PdfReader(source_path)
            for index, page in enumerate(reader.pages, start=1):
                if index <= last_page:
                    continue
                self._checkpoint_page(file_id, index, page)
                processed_this_run += 1
                if page_budget is not None and processed_this_run >= page_budget:
                    break

            current = self.inspect(file_id)
            completed = current.analyzed_page_count >= current.page_count
            if completed:
                file_warnings: list[str] = []
                if current.scan_page_count:
                    file_warnings.append(
                        f"{current.scan_page_count} 页文字层不足，后续需要 OCR 或人工转录"
                    )
                if current.question_marker_count == 0:
                    file_warnings.append("未识别到稳定题号，拆题时需要人工标记边界")
                next_status = "ready_for_segmentation"
            else:
                file_warnings = current.warnings
                next_status = "queued" if file.status in {"queued", "analyzing"} else "paused"
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE import_files SET status = ?, warnings_json = ?, error_message = '',
                        updated_at = ? WHERE file_id = ?
                    """,
                    (
                        next_status,
                        json.dumps(file_warnings, ensure_ascii=False),
                        self._now(),
                        file_id,
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
        if result.status == "ready_for_segmentation":
            message = (
                f"已分析 {result.analyzed_page_count} 页，识别 "
                f"{result.question_marker_count} 个题号标记。"
            )
        else:
            message = (
                f"本轮完成 {processed_this_run} 页；总进度 "
                f"{result.analyzed_page_count}/{result.page_count} 页，可从第 {result.resume_page} 页继续。"
            )
        return ImportAnalysisResult(file=result, message=message)

    def queue_batch(self, batch_id: str, *, retry_failed: bool = True) -> ImportBatchQueueResult:
        self._batch(batch_id, include_files=False)
        statuses = ["registered", "paused", "analyzing"]
        if retry_failed:
            statuses.append("failed")
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as connection:
            queued = connection.execute(
                f"""
                UPDATE import_files SET status = 'queued', error_message = '', updated_at = ?
                WHERE batch_id = ? AND status IN ({placeholders})
                """,
                (self._now(), batch_id, *statuses),
            ).rowcount
            connection.execute(
                "UPDATE import_batches SET updated_at = ? WHERE batch_id = ?",
                (self._now(), batch_id),
            )
        batch = self._batch(batch_id, include_files=True)
        return ImportBatchQueueResult(
            batch=batch,
            queued_count=queued,
            message=(
                f"已将 {queued} 份文件加入处理队列；已完成文件不会重复分析。"
                if queued
                else "没有需要加入队列的文件。"
            ),
        )

    def pause_batch(self, batch_id: str) -> ImportBatchQueueResult:
        self._batch(batch_id, include_files=False)
        with self._connect() as connection:
            paused = connection.execute(
                """
                UPDATE import_files SET status = 'paused', updated_at = ?
                WHERE batch_id = ? AND status = 'queued'
                """,
                (self._now(), batch_id),
            ).rowcount
        batch = self._batch(batch_id, include_files=True)
        return ImportBatchQueueResult(
            batch=batch,
            queued_count=0,
            message=f"已暂停 {paused} 份尚未开始或等待续跑的文件。",
        )

    def process_next(self, batch_id: str, *, page_budget: int = 20) -> ImportQueueStepResult:
        self._batch(batch_id, include_files=False)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT file_id FROM import_files
                WHERE batch_id = ? AND status = 'queued'
                ORDER BY created_at, original_filename LIMIT 1
                """,
                (batch_id,),
            ).fetchone()
        if row is None:
            batch = self._batch(batch_id, include_files=True)
            return ImportQueueStepResult(
                batch=batch,
                remaining_count=0,
                message="当前队列没有待处理文件。",
            )

        file_id = row["file_id"]
        before = self.inspect(file_id).analyzed_page_count
        try:
            result = self.analyze(file_id, page_budget=page_budget)
            file = result.file
            message = result.message
        except PdfImportError as exc:
            file = self.inspect(file_id)
            message = str(exc)
        batch = self._batch(batch_id, include_files=True)
        remaining = batch.queued_count + batch.analyzing_count
        return ImportQueueStepResult(
            batch=batch,
            file=file,
            processed_pages=max(0, file.analyzed_page_count - before),
            remaining_count=remaining,
            message=message,
        )

    def analyze_batch(self, batch_id: str) -> ImportBatchAnalysisResult:
        batch = self._batch(batch_id, include_files=True)
        analyzed = 0
        failed = 0
        for file in batch.files:
            if file.status == "ready_for_segmentation":
                continue
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
            crop_rows = connection.execute(
                """
                SELECT * FROM import_structured_media_crops
                WHERE file_id = ? ORDER BY created_at, crop_id
                """,
                (file_id,),
            ).fetchall()
        crops_by_draft: dict[str, list[StructuredMediaCropView]] = {}
        for crop_row in crop_rows:
            crop = self._media_crop(crop_row)
            crops_by_draft.setdefault(crop.draft_id, []).append(crop)
        items = [
            self._structured_draft(row, crops_by_draft.get(row["draft_id"], []))
            for row in rows
        ]
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
                    parsed["stem_latex"], json.dumps(parsed["options"], ensure_ascii=False), None,
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

    def auto_repair_structured_question_drafts(
        self, file_id: str, *, use_math_ocr: bool = False
    ) -> StructuredDraftRepairResult:
        self.inspect(file_id)
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM import_structured_question_drafts
                   WHERE file_id = ? ORDER BY position""",
                (file_id,),
            ).fetchall()
            if not rows:
                raise PdfImportError("当前文件还没有结构化草稿，请先同步确认后的题目边界")

            repaired_count = 0
            skipped_teacher_edits = 0
            skipped_imported = 0
            review_required_count = 0
            unresolved_glyph_count = 0
            now = self._now()
            for row in rows:
                if row["status"] == "imported":
                    skipped_imported += 1
                    continue
                if row["editor_id"] not in {"system_proposal", "auto_formula_repair"}:
                    # Do not replace teacher-authored content with the original
                    # source. Safe deterministic formula cleanup may still run
                    # against the teacher version itself; ordinary teacher text
                    # remains byte-for-byte untouched.
                    current_text = row["stem_plain"]
                    current_repair = repair_structured_text(
                        current_text, row["question_type"]
                    )
                    from .math_ocr import compose_readable_candidate

                    current_latex = row["stem_latex"] or ""
                    composed_latex = (
                        compose_readable_candidate(current_text, current_latex)
                        if current_latex else current_latex
                    )
                    if (
                        not re.search(r"[�□■\uf000-\uf8ff]", current_text)
                        and not current_repair.auto_repaired
                        and composed_latex == current_latex
                    ):
                        skipped_teacher_edits += 1
                        continue
                    repair_source = current_text
                    editor_id = row["editor_id"]
                else:
                    repair_source = row["source_text"]
                    editor_id = "auto_formula_repair"

                repaired = repair_structured_text(repair_source, row["question_type"])
                preserved_latex = (
                    row["stem_latex"]
                    if row["editor_id"] == "auto_formula_repair" and row["stem_latex"]
                    else repaired.stem_latex
                )
                if row["stem_latex"] and not preserved_latex:
                    preserved_latex = row["stem_latex"]
                if preserved_latex:
                    from .math_ocr import compose_readable_candidate

                    preserved_latex = compose_readable_candidate(
                        repaired.stem_plain, preserved_latex
                    )
                repaired_warnings = list(repaired.warnings)
                if preserved_latex:
                    repaired_warnings.extend(
                        warning
                        for warning in json.loads(row["warnings_json"])
                        if warning.startswith("数学 OCR 已从第")
                    )
                if repaired.formula_status == "needs_review":
                    review_required_count += 1
                unresolved_glyph_count += sum(
                    0xF000 <= ord(char) <= 0xF8FF for char in repaired.stem_plain
                )
                connection.execute(
                    """
                    UPDATE import_structured_question_drafts
                    SET stem_plain = ?, stem_latex = ?, options_json = ?,
                        formula_status = ?, formula_check_json = NULL,
                        formula_checked_signature = '', status = 'draft',
                        warnings_json = ?, editor_id = ?, updated_at = ?
                    WHERE draft_id = ?
                    """,
                    (
                        repaired.stem_plain,
                        preserved_latex,
                        json.dumps(repaired.options, ensure_ascii=False),
                        repaired.formula_status,
                        json.dumps(repaired_warnings, ensure_ascii=False),
                        editor_id,
                        now,
                        row["draft_id"],
                    ),
                )
                repaired_count += 1

        math_ocr_count = 0
        math_ocr_failed_count = 0
        if use_math_ocr:
            from .math_ocr import compose_readable_candidate, recognize_question_candidates

            source_path, _ = self.source_file(file_id)
            with self._connect() as connection:
                ocr_rows = connection.execute(
                    """SELECT * FROM import_structured_question_drafts
                       WHERE file_id = ? AND status != 'imported'
                       ORDER BY position""",
                    (file_id,),
                ).fetchall()
            requests = [
                (
                    row["draft_id"], row["source_text"], row["start_page"], row["end_page"]
                )
                for row in ocr_rows
                if not (row["stem_latex"] or "").strip()
                and needs_math_ocr(row["stem_plain"])
            ]
            if requests:
                try:
                    recognized = recognize_question_candidates(source_path, requests)
                except Exception:  # preserve fast repair when OCR is unavailable
                    recognized = {}
                    math_ocr_failed_count = len(requests)
                else:
                    math_ocr_failed_count = len(requests) - len(recognized)
                with self._connect() as connection:
                    for row in ocr_rows:
                        candidate = recognized.get(row["draft_id"])
                        if candidate is None:
                            continue
                        warnings = json.loads(row["warnings_json"])
                        warnings.append(
                            f"数学 OCR 已从第 {candidate.page_number} 页生成公式候选"
                            f"（匹配度 {candidate.score:.0%}）；请对照原页抽查。"
                        )
                        connection.execute(
                            """
                            UPDATE import_structured_question_drafts
                            SET stem_latex = ?, formula_status = 'needs_review',
                                formula_check_json = NULL, formula_checked_signature = '',
                                warnings_json = ?, updated_at = ?
                            WHERE draft_id = ?
                            """,
                            (
                                compose_readable_candidate(row["stem_plain"], candidate.text),
                                json.dumps(warnings, ensure_ascii=False),
                                self._now(),
                                row["draft_id"],
                            ),
                        )
                        math_ocr_count += 1

        drafts = self.structured_question_drafts(file_id)
        review_required_count = sum(
            item.formula_status == "needs_review" for item in drafts.items
        )
        math_ocr_count = sum(bool((item.stem_latex or "").strip()) for item in drafts.items)
        return StructuredDraftRepairResult(
            drafts=drafts,
            repaired_count=repaired_count,
            skipped_teacher_edits=skipped_teacher_edits,
            skipped_imported=skipped_imported,
            review_required_count=review_required_count,
            unresolved_glyph_count=unresolved_glyph_count,
            math_ocr_count=math_ocr_count,
            math_ocr_failed_count=math_ocr_failed_count,
            message=(
                f"已自动整理 {repaired_count} 道题的正文和公式字符；"
                f"数学 OCR 已生成 {math_ocr_count} 道公式候选；"
                f"{review_required_count} 道含数学表达式，请对照原页抽查。"
            ),
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
            previous_signature = self._formula_signature(self._formula_payload_from_row(row))
            next_signature = self._formula_signature(self._formula_payload_from_command(command))
            formula_changed = previous_signature != next_signature
            effective_formula_status = "needs_review" if formula_changed else row["formula_status"]
            formula_check_json = None if formula_changed else row["formula_check_json"]
            formula_checked_signature = "" if formula_changed else row["formula_checked_signature"]
            if command.status == "confirmed" and effective_formula_status != "confirmed":
                raise PdfImportError("确认结构化草稿前必须检查并由教师确认当前版本公式")
            self._validate_structured_draft(file.page_count, command)
            connection.execute(
                """
                UPDATE import_structured_question_drafts
                SET question_type = ?, stem_plain = ?, stem_latex = ?, options_json = ?,
                    answer_value = ?, solution_method = ?, solution_steps_json = ?,
                    final_answer = ?, difficulty = ?, formula_status = ?,
                    formula_check_json = ?, formula_checked_signature = ?,
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
                    command.difficulty, effective_formula_status,
                    formula_check_json, formula_checked_signature,
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

    def review_structured_formula(
        self, file_id: str, draft_id: str, command: StructuredFormulaReviewCommand
    ) -> StructuredQuestionDraftView:
        self.inspect(file_id)
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM import_structured_question_drafts
                   WHERE file_id = ? AND draft_id = ?""",
                (file_id, draft_id),
            ).fetchone()
            if row is None:
                raise KeyError(draft_id)
            if row["status"] == "imported":
                raise PdfImportError("已入库草稿请在题库审核台继续校对公式")
            check = self._analyze_formula(row, reviewer_id=command.reviewer_id)
            blocking = any(issue.severity == "blocking" for issue in check.issues)
            teacher_confirmed = command.confirm and not blocking
            check = check.model_copy(update={"teacher_confirmed": teacher_confirmed})
            formula_status = (
                "confirmed" if teacher_confirmed else "needs_review" if blocking else "pending"
            )
            connection.execute(
                """
                UPDATE import_structured_question_drafts
                SET formula_status = ?, formula_check_json = ?,
                    formula_checked_signature = ?, editor_id = ?, updated_at = ?
                WHERE file_id = ? AND draft_id = ?
                """,
                (
                    formula_status, check.model_dump_json(), check.content_signature,
                    command.reviewer_id, self._now(), file_id, draft_id,
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

    def create_media_crop(
        self, file_id: str, draft_id: str, command: StructuredMediaCropCommand
    ) -> StructuredMediaCropView:
        file = self.inspect(file_id)
        with self._connect() as connection:
            draft = connection.execute(
                """SELECT * FROM import_structured_question_drafts
                   WHERE file_id = ? AND draft_id = ?""",
                (file_id, draft_id),
            ).fetchone()
            if draft is None:
                raise KeyError(draft_id)
            if draft["status"] == "imported":
                raise PdfImportError("已入库草稿不能继续新增裁剪图，请前往题库审核台管理图片")
            count = connection.execute(
                "SELECT COUNT(*) FROM import_structured_media_crops WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()[0]
        if count >= self.MAX_CROPS_PER_DRAFT:
            raise PdfImportError(f"每道题最多保留 {self.MAX_CROPS_PER_DRAFT} 张裁剪图")
        if command.page_number < draft["start_page"] or command.page_number > draft["end_page"]:
            raise PdfImportError(
                f"裁剪页必须位于本题边界第 {draft['start_page']} 到 {draft['end_page']} 页"
            )
        self._validate_crop(command)
        preview = self.preview_page(
            file.file_id, command.page_number, width=self.CROP_RENDER_WIDTH
        )
        crop_id = f"imp_crop_{uuid4().hex[:16]}"
        crop_root = (self.file_root / "crops" / file_id / draft_id).resolve()
        if self.file_root not in crop_root.parents:
            raise PdfImportError("裁剪图存储路径异常")
        crop_root.mkdir(parents=True, exist_ok=True)
        output = crop_root / f"{crop_id}.png"
        try:
            with Image.open(preview) as image:
                image.load()
                left = round(command.x_ratio * image.width)
                top = round(command.y_ratio * image.height)
                right = round((command.x_ratio + command.width_ratio) * image.width)
                bottom = round((command.y_ratio + command.height_ratio) * image.height)
                left = max(0, min(left, image.width - 1))
                top = max(0, min(top, image.height - 1))
                right = max(left + 1, min(right, image.width))
                bottom = max(top + 1, min(bottom, image.height))
                cropped = image.crop((left, top, right, bottom)).convert("RGB")
                cropped.save(output, format="PNG", optimize=True)
                pixel_width, pixel_height = cropped.size
        except Exception as exc:
            output.unlink(missing_ok=True)
            raise PdfImportError(f"PDF 图片裁剪失败：{exc}") from exc
        now = self._now()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO import_structured_media_crops
                    (crop_id, draft_id, file_id, page_number, placement,
                     x_ratio, y_ratio, width_ratio, height_ratio, note, editor_id,
                     stored_name, pixel_width, pixel_height, imported_image_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                    """,
                    (
                        crop_id, draft_id, file_id, command.page_number, command.placement,
                        command.x_ratio, command.y_ratio, command.width_ratio,
                        command.height_ratio, command.note.strip(), command.editor_id,
                        str(output.relative_to(self.file_root)), pixel_width, pixel_height, now,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM import_structured_media_crops WHERE crop_id = ?", (crop_id,)
                ).fetchone()
        except Exception:
            output.unlink(missing_ok=True)
            raise
        return self._media_crop(row)

    def media_crop_file(self, crop_id: str) -> tuple[Path, StructuredMediaCropView]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM import_structured_media_crops WHERE crop_id = ?", (crop_id,)
            ).fetchone()
        if row is None:
            raise KeyError(crop_id)
        path = (self.file_root / row["stored_name"]).resolve()
        crop_root = (self.file_root / "crops").resolve()
        if crop_root not in path.parents or not path.exists():
            raise PdfImportError("裁剪图不存在或存储路径异常")
        return path, self._media_crop(row)

    def delete_media_crop(self, file_id: str, draft_id: str, crop_id: str) -> None:
        with self._connect() as connection:
            draft = connection.execute(
                """SELECT status FROM import_structured_question_drafts
                   WHERE file_id = ? AND draft_id = ?""",
                (file_id, draft_id),
            ).fetchone()
            if draft is None:
                raise KeyError(draft_id)
            if draft["status"] == "imported":
                raise PdfImportError("已入库草稿的图片只能在题库审核台删除")
            row = connection.execute(
                """SELECT * FROM import_structured_media_crops
                   WHERE file_id = ? AND draft_id = ? AND crop_id = ?""",
                (file_id, draft_id, crop_id),
            ).fetchone()
            if row is None:
                raise KeyError(crop_id)
            connection.execute(
                "DELETE FROM import_structured_media_crops WHERE crop_id = ?", (crop_id,)
            )
        path = (self.file_root / row["stored_name"]).resolve()
        crop_root = (self.file_root / "crops").resolve()
        if crop_root in path.parents:
            path.unlink(missing_ok=True)

    def mark_media_crop_imported(self, crop_id: str, image_id: str) -> StructuredMediaCropView:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM import_structured_media_crops WHERE crop_id = ?", (crop_id,)
            ).fetchone()
            if row is None:
                raise KeyError(crop_id)
            existing = row["imported_image_id"]
            if existing and existing != image_id:
                raise PdfImportError("裁剪图已经关联其他题库图片")
            connection.execute(
                """UPDATE import_structured_media_crops SET imported_image_id = ?
                   WHERE crop_id = ?""",
                (image_id, crop_id),
            )
            updated = connection.execute(
                "SELECT * FROM import_structured_media_crops WHERE crop_id = ?", (crop_id,)
            ).fetchone()
        return self._media_crop(updated)

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

    def _checkpoint_page(self, file_id: str, page_number: int, page: Any) -> None:
        text = (page.extract_text() or "").strip()
        char_count = len(text)
        markers = self._marker_count(text)
        try:
            image_count = len(page.images)
        except Exception:
            image_count = 0
        has_text = char_count >= self.MIN_TEXT_LAYER_CHARS
        warnings = [] if has_text else ["本页文字层不足，需要 OCR 或人工转录"]
        box = page.mediabox
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO import_pages
                (page_id, file_id, page_number, width_points, height_points, extracted_text,
                 character_count, question_marker_count, embedded_image_count,
                 has_text_layer, warnings_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_id, page_number) DO UPDATE SET
                    width_points = excluded.width_points,
                    height_points = excluded.height_points,
                    extracted_text = excluded.extracted_text,
                    character_count = excluded.character_count,
                    question_marker_count = excluded.question_marker_count,
                    embedded_image_count = excluded.embedded_image_count,
                    has_text_layer = excluded.has_text_layer,
                    warnings_json = excluded.warnings_json
                """,
                (
                    f"{file_id}_p{page_number:04d}", file_id, page_number,
                    float(box.width), float(box.height), text, char_count, markers,
                    image_count, int(has_text), json.dumps(warnings, ensure_ascii=False),
                ),
            )
            connection.execute(
                """
                UPDATE import_files SET
                    analyzed_page_count = (SELECT COUNT(*) FROM import_pages WHERE file_id = ?),
                    text_page_count = (SELECT COALESCE(SUM(has_text_layer), 0) FROM import_pages WHERE file_id = ?),
                    scan_page_count = (SELECT COALESCE(SUM(CASE WHEN has_text_layer = 0 THEN 1 ELSE 0 END), 0) FROM import_pages WHERE file_id = ?),
                    extracted_character_count = (SELECT COALESCE(SUM(character_count), 0) FROM import_pages WHERE file_id = ?),
                    question_marker_count = (SELECT COALESCE(SUM(question_marker_count), 0) FROM import_pages WHERE file_id = ?),
                    image_page_count = (SELECT COALESCE(SUM(CASE WHEN embedded_image_count > 0 THEN 1 ELSE 0 END), 0) FROM import_pages WHERE file_id = ?),
                    embedded_image_count = (SELECT COALESCE(SUM(embedded_image_count), 0) FROM import_pages WHERE file_id = ?),
                    updated_at = ?
                WHERE file_id = ?
                """,
                (file_id, file_id, file_id, file_id, file_id, file_id, file_id, self._now(), file_id),
            )

    @staticmethod
    def _load_question_estimates(path: Path | None) -> dict[str, int]:
        if path is None or not path.exists():
            return {}
        estimates: dict[str, int] = {}
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                for row in csv.DictReader(stream):
                    filename = str(row.get("filename") or "").strip()
                    value = str(row.get("preliminary_question_estimate") or "0").strip()
                    if filename:
                        estimates[filename] = max(0, int(value or 0))
        except (OSError, ValueError):
            return {}
        return estimates

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
        page_count = sum(item.page_count for item in files)
        analyzed_page_count = sum(item.analyzed_page_count for item in files)
        return ImportBatchSummary(
            batch_id=batch_id,
            title=batch["title"],
            rights_basis=batch["rights_basis"],
            rights_statement=batch["rights_statement"],
            owner_id=batch["owner_id"],
            file_count=len(files),
            registered_count=sum(item.status == "registered" for item in files),
            queued_count=sum(item.status == "queued" for item in files),
            analyzing_count=sum(item.status == "analyzing" for item in files),
            paused_count=sum(item.status == "paused" for item in files),
            ready_count=sum(item.status == "ready_for_segmentation" for item in files),
            failed_count=sum(item.status == "failed" for item in files),
            page_count=page_count,
            analyzed_page_count=analyzed_page_count,
            progress_percent=round(analyzed_page_count / page_count * 100, 1) if page_count else 0,
            question_marker_count=sum(item.question_marker_count for item in files),
            estimated_question_count=sum(item.estimated_question_count for item in files),
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
            analysis_attempts=row["analysis_attempts"],
            analyzed_page_count=row["analyzed_page_count"], text_page_count=row["text_page_count"],
            progress_percent=(
                round(row["analyzed_page_count"] / row["page_count"] * 100, 1)
                if row["page_count"] else 0
            ),
            resume_page=(
                row["analyzed_page_count"] + 1
                if row["analyzed_page_count"] < row["page_count"] else None
            ),
            scan_page_count=row["scan_page_count"], extracted_character_count=row["extracted_character_count"],
            question_marker_count=row["question_marker_count"],
            estimated_question_count=row["estimated_question_count"],
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
    def _structured_draft(
        row: sqlite3.Row, media_crops: list[StructuredMediaCropView] | None = None
    ) -> StructuredQuestionDraftView:
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
            media_crops=media_crops or [],
            formula_check=(
                StructuredFormulaCheck.model_validate_json(row["formula_check_json"])
                if row["formula_check_json"] else None
            ),
            note=row["note"], editor_id=row["editor_id"],
            imported_question_id=row["imported_question_id"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    @staticmethod
    def _media_crop(row: sqlite3.Row) -> StructuredMediaCropView:
        return StructuredMediaCropView(
            crop_id=row["crop_id"], draft_id=row["draft_id"], file_id=row["file_id"],
            page_number=row["page_number"], placement=row["placement"],
            x_ratio=row["x_ratio"], y_ratio=row["y_ratio"],
            width_ratio=row["width_ratio"], height_ratio=row["height_ratio"],
            note=row["note"], editor_id=row["editor_id"],
            pixel_width=row["pixel_width"], pixel_height=row["pixel_height"],
            imported_image_id=row["imported_image_id"], created_at=row["created_at"],
        )

    @classmethod
    def _structure_boundary_text(cls, source_text: str, question_type: str) -> dict:
        repaired = repair_structured_text(source_text, question_type)
        return {
            "stem_plain": repaired.stem_plain,
            "stem_latex": repaired.stem_latex,
            "options": repaired.options,
            "formula_status": repaired.formula_status,
            "warnings": repaired.warnings,
        }

    @staticmethod
    def _formula_payload_from_row(row: sqlite3.Row) -> dict:
        return {
            "stem_plain": row["stem_plain"],
            "stem_latex": row["stem_latex"] or "",
            "options": json.loads(row["options_json"]),
            "answer_value": row["answer_value"] or "",
            "solution_method": row["solution_method"],
            "solution_steps": json.loads(row["solution_steps_json"]),
            "final_answer": row["final_answer"] or "",
        }

    @staticmethod
    def _formula_payload_from_command(command: StructuredQuestionDraftUpdate) -> dict:
        return {
            "stem_plain": command.stem_plain.strip(),
            "stem_latex": (command.stem_latex or "").strip(),
            "options": [item.model_dump() for item in command.options],
            "answer_value": (command.answer_value or "").strip(),
            "solution_method": command.solution_method.strip(),
            "solution_steps": [step.strip() for step in command.solution_steps if step.strip()],
            "final_answer": (command.final_answer or "").strip(),
        }

    @staticmethod
    def _formula_signature(payload: dict) -> str:
        normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @classmethod
    def _analyze_formula(
        cls, row: sqlite3.Row, *, reviewer_id: str
    ) -> StructuredFormulaCheck:
        payload = cls._formula_payload_from_row(row)
        fields: list[tuple[str, str]] = [
            ("题干正文", payload["stem_plain"]),
            ("LaTeX 题干", payload["stem_latex"]),
            *[
                (f"选项 {item.get('key', index + 1)}", str(item.get("text", "")))
                for index, item in enumerate(payload["options"])
            ],
            ("参考答案", payload["answer_value"]),
            *[
                (f"解析步骤 {index + 1}", str(step))
                for index, step in enumerate(payload["solution_steps"])
            ],
            ("最终答案", payload["final_answer"]),
        ]
        issues: list[StructuredFormulaIssue] = []
        suspicious = re.compile(r"[�□■\uf000-\uf8ff]")
        for field, text in fields:
            match = suspicious.search(text)
            if match:
                start = max(0, match.start() - 16)
                end = min(len(text), match.start() + 17)
                issues.append(
                    StructuredFormulaIssue(
                        code="unreadable_glyph", severity="blocking", field=field,
                        message="含有 PDF 字体映射产生的不可读字符，必须对照原页重建。",
                        excerpt=text[start:end],
                    )
                )
            dollar_count = len(re.findall(r"(?<!\\)\$", text))
            if dollar_count % 2:
                issues.append(
                    StructuredFormulaIssue(
                        code="unbalanced_math_delimiter", severity="blocking", field=field,
                        message="数学定界符 $ 数量为奇数，公式无法稳定渲染。", excerpt=text[:80],
                    )
                )
            balance = 0
            for token in re.findall(r"(?<!\\)[{}]", text):
                balance += 1 if token == "{" else -1
                if balance < 0:
                    break
            if balance != 0:
                issues.append(
                    StructuredFormulaIssue(
                        code="unbalanced_braces", severity="blocking", field=field,
                        message="LaTeX 花括号不成对，请检查分式、根式或上下标。", excerpt=text[:80],
                    )
                )
            begins = re.findall(r"\\begin\{([^}]+)\}", text)
            ends = re.findall(r"\\end\{([^}]+)\}", text)
            if sorted(begins) != sorted(ends):
                issues.append(
                    StructuredFormulaIssue(
                        code="unbalanced_environment", severity="blocking", field=field,
                        message="LaTeX 环境的 begin/end 不匹配。", excerpt=text[:80],
                    )
                )
        math_signal = re.compile(r"[=<>≤≥∑√∞∈∪∩]|[A-Za-z]\s*\(")
        stem_latex = payload["stem_latex"]
        if math_signal.search(payload["stem_plain"]) and not stem_latex:
            issues.append(
                StructuredFormulaIssue(
                    code="latex_not_rebuilt", severity="warning", field="LaTeX 题干",
                    message="题干含数学表达式但尚未填写 LaTeX 版本，建议对照原页重建。",
                )
            )
        if stem_latex and math_signal.search(stem_latex) and "$" not in stem_latex:
            issues.append(
                StructuredFormulaIssue(
                    code="missing_math_delimiter", severity="blocking", field="LaTeX 题干",
                    message="LaTeX 题干包含数学表达式，但没有使用 $...$ 定界。",
                    excerpt=stem_latex[:80],
                )
            )
        blocking = any(issue.severity == "blocking" for issue in issues)
        return StructuredFormulaCheck(
            status="blocked" if blocking else "passed",
            content_signature=cls._formula_signature(payload), issues=issues,
            checked_at=cls._now(), checked_by=reviewer_id,
        )

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
        for item in command.media_references:
            if item.page_number > page_count:
                raise PdfImportError(f"图片来源页必须在 1 到 {page_count} 之间")

    @staticmethod
    def _validate_crop(command: StructuredMediaCropCommand) -> None:
        if command.x_ratio + command.width_ratio > 1.000001:
            raise PdfImportError("裁剪框超出页面右边界")
        if command.y_ratio + command.height_ratio > 1.000001:
            raise PdfImportError("裁剪框超出页面下边界")
        if command.width_ratio < 0.01 or command.height_ratio < 0.01:
            raise PdfImportError("裁剪区域过小，请重新框选")

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
                    page_count INTEGER NOT NULL, status TEXT NOT NULL,
                    analysis_attempts INTEGER NOT NULL DEFAULT 0,
                    estimated_question_count INTEGER NOT NULL DEFAULT 0,
                    analyzed_page_count INTEGER NOT NULL,
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
                    formula_status TEXT NOT NULL, formula_check_json TEXT,
                    formula_checked_signature TEXT NOT NULL DEFAULT '',
                    media_references_json TEXT NOT NULL,
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
                CREATE TABLE IF NOT EXISTS import_structured_media_crops (
                    crop_id TEXT PRIMARY KEY, draft_id TEXT NOT NULL,
                    file_id TEXT NOT NULL, page_number INTEGER NOT NULL,
                    placement TEXT NOT NULL, x_ratio REAL NOT NULL, y_ratio REAL NOT NULL,
                    width_ratio REAL NOT NULL, height_ratio REAL NOT NULL,
                    note TEXT NOT NULL, editor_id TEXT NOT NULL,
                    stored_name TEXT NOT NULL UNIQUE, pixel_width INTEGER NOT NULL,
                    pixel_height INTEGER NOT NULL, imported_image_id TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(draft_id) REFERENCES import_structured_question_drafts(draft_id),
                    FOREIGN KEY(file_id) REFERENCES import_files(file_id)
                );
                CREATE INDEX IF NOT EXISTS idx_import_media_crops_draft
                    ON import_structured_media_crops(draft_id, created_at);
                """
            )
            self._ensure_column(connection, "import_files", "image_page_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "import_files", "embedded_image_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "import_files", "analysis_attempts", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "import_files", "estimated_question_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "import_pages", "embedded_image_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "import_structured_question_drafts", "formula_check_json", "TEXT")
            self._ensure_column(connection, "import_structured_question_drafts", "formula_checked_signature", "TEXT NOT NULL DEFAULT ''")
            for filename, estimate in self.question_estimates.items():
                connection.execute(
                    """
                    UPDATE import_files SET estimated_question_count = ?
                    WHERE original_filename = ? AND estimated_question_count = 0
                    """,
                    (estimate, filename),
                )
            connection.execute(
                """
                UPDATE import_structured_question_drafts
                SET formula_status = 'needs_review',
                    status = CASE WHEN status = 'confirmed' THEN 'draft' ELSE status END
                WHERE formula_status = 'confirmed'
                  AND formula_checked_signature = ''
                  AND status != 'imported'
                """
            )

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
