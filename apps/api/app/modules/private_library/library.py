from __future__ import annotations

import hashlib
import json
import sqlite3
from zipfile import BadZipFile, ZipFile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from docx import Document
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

from app.modules.private_library.schemas import (
    LibraryIngestCommand,
    LibraryItemList,
    LibraryItemSummary,
    LibraryItemView,
    LibraryStats,
    LibraryTextReviewCommand,
)


class PrivateLibraryError(ValueError):
    pass


class PrivateLibrary:
    """Owns private-file validation, extraction, rights and text review."""

    MAX_FILE_BYTES = 50 * 1024 * 1024
    MAX_TEXT_CHARS = 2_000_000
    MAX_PDF_PAGES = 1000
    MAX_DOCX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
    MAX_IMAGE_PIXELS = 25_000_000

    def __init__(self, database_path: Path, file_root: Path) -> None:
        self.database_path = database_path.resolve()
        self.file_root = file_root.resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def ingest(
        self,
        command: LibraryIngestCommand,
        *,
        filename: str,
        content: bytes,
    ) -> LibraryItemView:
        if not command.rights_acknowledged:
            raise PrivateLibraryError("必须确认资料来源与使用权声明")
        if not content:
            raise PrivateLibraryError("上传文件不能为空")
        if len(content) > self.MAX_FILE_BYTES:
            raise PrivateLibraryError("单个资料文件不能超过 50 MB")
        safe_filename = Path(filename or "未命名资料").name
        if safe_filename in {"", ".", ".."}:
            safe_filename = "未命名资料"
        extraction = self._extract(safe_filename, content)
        digest = hashlib.sha256(content).hexdigest()
        now = self._now()
        item_id = f"lib_{uuid4().hex[:16]}"
        title = command.title.strip() or Path(safe_filename).stem[:300] or "未命名资料"
        adaptation_allowed = command.rights_basis in {"original", "licensed"}
        with self._connect() as connection:
            duplicate = connection.execute(
                "SELECT library_item_id FROM library_items WHERE owner_id = ? AND source_sha256 = ?",
                (command.owner_id, digest),
            ).fetchone()
            if duplicate:
                raise PrivateLibraryError(
                    f"该文件已经上传，资料编号为 {duplicate['library_item_id']}"
                )
            stored_name = f"{item_id}{extraction['suffix']}"
            stored_path = self.file_root / stored_name
            stored_path.write_bytes(content)
            try:
                connection.execute(
                    """
                    INSERT INTO library_items (
                        library_item_id, owner_id, title, original_filename, stored_name,
                        file_kind, mime_type, size_bytes, source_sha256, page_count,
                        extraction_status, extracted_text, corrected_text, text_review_status,
                        rights_basis, rights_statement, adaptation_allowed, warnings_json,
                        review_note, version, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', 'pending', ?, ?, ?, ?, '', 1, ?, ?)
                    """,
                    (
                        item_id,
                        command.owner_id,
                        title,
                        safe_filename,
                        stored_name,
                        extraction["file_kind"],
                        extraction["mime_type"],
                        len(content),
                        digest,
                        extraction["page_count"],
                        extraction["status"],
                        extraction["text"],
                        command.rights_basis,
                        command.rights_statement.strip(),
                        int(adaptation_allowed),
                        json.dumps(extraction["warnings"], ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            except Exception:
                stored_path.unlink(missing_ok=True)
                raise
        return self.get(item_id)

    def list(self, *, limit: int = 50) -> LibraryItemList:
        with self._connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM library_items").fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM library_items ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return LibraryItemList(items=[self._summary(row) for row in rows], total=total)

    def get(self, item_id: str) -> LibraryItemView:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM library_items WHERE library_item_id = ?", (item_id,)
            ).fetchone()
        if row is None:
            raise KeyError(item_id)
        return self._view(row)

    def review(self, item_id: str, command: LibraryTextReviewCommand) -> LibraryItemView:
        corrected = command.corrected_text.strip()
        if command.confirm and not corrected:
            raise PrivateLibraryError("确认校对前必须提供可用文本")
        now = self._now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM library_items WHERE library_item_id = ?", (item_id,)
            ).fetchone()
            if row is None:
                raise KeyError(item_id)
            new_version = row["version"] + 1
            status = "confirmed" if command.confirm else "pending"
            connection.execute(
                """
                INSERT INTO library_text_revisions (
                    library_item_id, version, previous_text, revised_text,
                    review_status, reviewer_id, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    new_version,
                    row["corrected_text"],
                    corrected,
                    status,
                    command.reviewer_id,
                    command.note.strip(),
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE library_items SET corrected_text = ?, text_review_status = ?,
                    review_note = ?, version = ?, updated_at = ?
                WHERE library_item_id = ?
                """,
                (corrected, status, command.note.strip(), new_version, now, item_id),
            )
        return self.get(item_id)

    def stats(self) -> LibraryStats:
        with self._connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM library_items").fetchone()[0]
            pending = connection.execute(
                "SELECT COUNT(*) FROM library_items WHERE text_review_status = 'pending'"
            ).fetchone()[0]
            confirmed = connection.execute(
                "SELECT COUNT(*) FROM library_items WHERE text_review_status = 'confirmed'"
            ).fetchone()[0]
            needs_ocr = connection.execute(
                "SELECT COUNT(*) FROM library_items WHERE extraction_status = 'needs_ocr'"
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT file_kind, COUNT(*) AS count FROM library_items GROUP BY file_kind"
            ).fetchall()
        return LibraryStats(
            total=total,
            pending_review=pending,
            confirmed=confirmed,
            needs_ocr=needs_ocr,
            by_file_kind={row["file_kind"]: row["count"] for row in rows},
        )

    def file_for_download(self, item_id: str) -> tuple[Path, LibraryItemView]:
        item = self.get(item_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT stored_name FROM library_items WHERE library_item_id = ?", (item_id,)
            ).fetchone()
        path = (self.file_root / row["stored_name"]).resolve()
        if path.parent != self.file_root or not path.is_file():
            raise PrivateLibraryError("资料原文件不存在或存储路径异常")
        return path, item

    def _extract(self, filename: str, content: bytes) -> dict:
        if content.startswith(b"%PDF-"):
            return self._extract_pdf(content)
        if content.startswith(b"PK\x03\x04"):
            return self._extract_docx(content)
        try:
            with Image.open(BytesIO(content)) as image:
                image.verify()
            with Image.open(BytesIO(content)) as image:
                image_format = (image.format or "").upper()
                mime = Image.MIME.get(image_format)
                suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(
                    image_format
                )
                if not mime or not suffix:
                    raise PrivateLibraryError("图片仅支持 PNG、JPEG 和 WebP")
                width, height = image.size
                if width * height > self.MAX_IMAGE_PIXELS:
                    raise PrivateLibraryError("图片像素总量不能超过 2500 万")
            return {
                "file_kind": "image",
                "mime_type": mime,
                "suffix": suffix,
                "page_count": 1,
                "status": "needs_ocr",
                "text": "",
                "warnings": [
                    f"图片尺寸为 {width} × {height}；当前等待 OCR 或教师人工转录。",
                    "图片内容未经识别，不会自动进入题库或模型训练。",
                ],
            }
        except Image.DecompressionBombError as exc:
            raise PrivateLibraryError("图片像素规模异常，已拒绝解析") from exc
        except (UnidentifiedImageError, OSError):
            raise PrivateLibraryError(
                f"不支持的文件格式：{Path(filename).suffix or '无法识别'}；仅支持 PDF、DOCX、PNG、JPEG、WebP"
            ) from None

    def _extract_pdf(self, content: bytes) -> dict:
        warnings: list[str] = []
        try:
            reader = PdfReader(BytesIO(content), strict=False)
            if reader.is_encrypted and reader.decrypt("") == 0:
                raise PrivateLibraryError("PDF 已加密，无法提取文本；请先解除密码后上传")
            if len(reader.pages) > self.MAX_PDF_PAGES:
                raise PrivateLibraryError(f"PDF 页数不能超过 {self.MAX_PDF_PAGES} 页")
            pages: list[str] = []
            extracted_chars = 0
            for index, page in enumerate(reader.pages, start=1):
                page_text = (page.extract_text() or "").strip()
                if page_text:
                    pages.append(f"【第 {index} 页】\n{page_text}")
                    extracted_chars += len(page_text)
                if extracted_chars > self.MAX_TEXT_CHARS:
                    warnings.append("提取文本超过 200 万字符，已截断等待人工分批处理。")
                    break
            text = "\n\n".join(pages)[: self.MAX_TEXT_CHARS]
            status = "extracted" if text.strip() else "needs_ocr"
            if status == "needs_ocr":
                warnings.append("未检测到可复制文本，该 PDF 可能是扫描件，需要 OCR 或人工转录。")
            return {
                "file_kind": "pdf",
                "mime_type": "application/pdf",
                "suffix": ".pdf",
                "page_count": len(reader.pages),
                "status": status,
                "text": text,
                "warnings": warnings,
            }
        except PrivateLibraryError:
            raise
        except Exception as exc:
            raise PrivateLibraryError(f"PDF 文件损坏或无法读取：{exc}") from exc

    def _extract_docx(self, content: bytes) -> dict:
        try:
            with ZipFile(BytesIO(content)) as archive:
                entries = archive.infolist()
                if len(entries) > 10_000:
                    raise PrivateLibraryError("DOCX 内部文件数量异常，已拒绝解析")
                if sum(entry.file_size for entry in entries) > self.MAX_DOCX_UNCOMPRESSED_BYTES:
                    raise PrivateLibraryError("DOCX 解压后超过 200 MB，已拒绝解析")
                if "word/document.xml" not in archive.namelist():
                    raise PrivateLibraryError("上传的 ZIP 文件不是有效 DOCX 文档")
        except BadZipFile as exc:
            raise PrivateLibraryError("DOCX 压缩结构损坏") from exc
        try:
            document = Document(BytesIO(content))
        except Exception as exc:
            raise PrivateLibraryError(f"DOCX 文件损坏或无法读取：{exc}") from exc
        blocks = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
        for table in document.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    blocks.append("\t".join(cells))
        text = "\n".join(blocks)[: self.MAX_TEXT_CHARS]
        warnings: list[str] = []
        status = "extracted" if text.strip() else "needs_ocr"
        if status == "needs_ocr":
            warnings.append("DOCX 中未检测到正文，可能仅包含图片，需要 OCR 或人工转录。")
        if document.inline_shapes:
            warnings.append("文档包含图片；当前仅提取文字，图片中的题目仍需 OCR 或人工核对。")
        return {
            "file_kind": "docx",
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "suffix": ".docx",
            "page_count": None,
            "status": status,
            "text": text,
            "warnings": warnings,
        }

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS library_items (
                    library_item_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    stored_name TEXT NOT NULL UNIQUE,
                    file_kind TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    page_count INTEGER,
                    extraction_status TEXT NOT NULL,
                    extracted_text TEXT NOT NULL,
                    corrected_text TEXT NOT NULL,
                    text_review_status TEXT NOT NULL,
                    rights_basis TEXT NOT NULL,
                    rights_statement TEXT NOT NULL,
                    adaptation_allowed INTEGER NOT NULL,
                    warnings_json TEXT NOT NULL,
                    review_note TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(owner_id, source_sha256)
                );
                CREATE TABLE IF NOT EXISTS library_text_revisions (
                    revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    library_item_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    previous_text TEXT NOT NULL,
                    revised_text TEXT NOT NULL,
                    review_status TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(library_item_id) REFERENCES library_items(library_item_id),
                    UNIQUE(library_item_id, version)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _summary(row: sqlite3.Row) -> LibraryItemSummary:
        return LibraryItemSummary(
            library_item_id=row["library_item_id"],
            title=row["title"],
            original_filename=row["original_filename"],
            file_kind=row["file_kind"],
            mime_type=row["mime_type"],
            size_bytes=row["size_bytes"],
            page_count=row["page_count"],
            extraction_status=row["extraction_status"],
            text_review_status=row["text_review_status"],
            extracted_char_count=len(row["extracted_text"]),
            corrected_char_count=len(row["corrected_text"]),
            rights_basis=row["rights_basis"],
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @classmethod
    def _view(cls, row: sqlite3.Row) -> LibraryItemView:
        return LibraryItemView(
            **cls._summary(row).model_dump(),
            source_sha256=row["source_sha256"],
            extracted_text=row["extracted_text"],
            corrected_text=row["corrected_text"],
            rights_statement=row["rights_statement"],
            adaptation_allowed=bool(row["adaptation_allowed"]),
            warnings=json.loads(row["warnings_json"]),
            review_note=row["review_note"],
        )
