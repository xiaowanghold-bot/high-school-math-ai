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
