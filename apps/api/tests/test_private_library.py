from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient
from PIL import Image
from reportlab.pdfgen.canvas import Canvas

from app.main import app
from app.modules.private_library import (
    LibraryIngestCommand,
    LibraryTextReviewCommand,
    PrivateLibrary,
    PrivateLibraryError,
)


def make_library(tmp_path: Path) -> PrivateLibrary:
    return PrivateLibrary(tmp_path / "library.sqlite3", tmp_path / "files")


def ingest_command(**updates) -> LibraryIngestCommand:
    values = {
        "title": "函数资料",
        "rights_basis": "private_teaching_only",
        "rights_statement": "本人确认该资料仅上传至私人空间用于日常教学。",
        "rights_acknowledged": True,
        "owner_id": "owner_teacher",
    }
    values.update(updates)
    return LibraryIngestCommand(**values)


def docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_heading("高中数学讲义", level=1)
    document.add_paragraph(text)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def pdf_bytes(text: str) -> bytes:
    output = BytesIO()
    canvas = Canvas(output)
    canvas.drawString(72, 760, text)
    canvas.save()
    return output.getvalue()


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (80, 60), "white").save(output, format="PNG")
    return output.getvalue()


def test_docx_is_extracted_but_remains_private(tmp_path: Path) -> None:
    library = make_library(tmp_path)

    item = library.ingest(
        ingest_command(),
        filename="函数讲义.docx",
        content=docx_bytes("函数单调性是本节课的核心内容。"),
    )

    assert item.file_kind == "docx"
    assert item.extraction_status == "extracted"
    assert "函数单调性" in item.extracted_text
    assert item.visibility == "private"
    assert not item.public_search_allowed
    assert not item.model_training_allowed
    assert not item.adaptation_allowed
    assert item.text_review_status == "pending"


def test_pdf_text_is_extracted_and_download_path_is_confined(tmp_path: Path) -> None:
    library = make_library(tmp_path)
    item = library.ingest(
        ingest_command(rights_basis="original"),
        filename="lesson.pdf",
        content=pdf_bytes("Function monotonicity and x^2"),
    )

    assert item.extraction_status == "extracted"
    assert "Function monotonicity" in item.extracted_text
    assert item.page_count == 1
    assert item.adaptation_allowed
    path, downloaded = library.file_for_download(item.library_item_id)
    assert path.parent == (tmp_path / "files").resolve()
    assert path.read_bytes().startswith(b"%PDF-")
    assert downloaded.original_filename == "lesson.pdf"


def test_image_waits_for_ocr_then_can_be_manually_confirmed(tmp_path: Path) -> None:
    library = make_library(tmp_path)
    item = library.ingest(
        ingest_command(title="立体几何题图"),
        filename="geometry.png",
        content=png_bytes(),
    )

    assert item.file_kind == "image"
    assert item.extraction_status == "needs_ocr"
    assert item.extracted_text == ""
    assert any("人工转录" in warning for warning in item.warnings)

    reviewed = library.review(
        item.library_item_id,
        LibraryTextReviewCommand(
            corrected_text="如图，在正方体 ABCD-A₁B₁C₁D₁ 中，求异面直线所成角。",
            note="教师根据原图完成转录",
            confirm=True,
        ),
    )

    assert reviewed.text_review_status == "confirmed"
    assert reviewed.version == 2
    assert "正方体" in reviewed.corrected_text


def test_rights_acknowledgement_and_duplicate_gate(tmp_path: Path) -> None:
    library = make_library(tmp_path)
    content = docx_bytes("集合与常用逻辑用语")

    with pytest.raises(PrivateLibraryError, match="必须确认"):
        library.ingest(
            ingest_command(rights_acknowledged=False),
            filename="sets.docx",
            content=content,
        )

    first = library.ingest(ingest_command(), filename="sets.docx", content=content)
    with pytest.raises(PrivateLibraryError, match=first.library_item_id):
        library.ingest(ingest_command(), filename="copy.docx", content=content)


def test_invalid_file_is_rejected_without_writing(tmp_path: Path) -> None:
    library = make_library(tmp_path)

    with pytest.raises(PrivateLibraryError, match="不支持的文件格式"):
        library.ingest(
            ingest_command(), filename="payload.exe", content=b"not-a-real-file"
        )

    assert library.stats().total == 0
    assert list((tmp_path / "files").iterdir()) == []


def test_private_library_http_upload_review_and_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = make_library(tmp_path)
    monkeypatch.setattr("app.routes.library.get_private_library", lambda: library)
    client = TestClient(app)

    response = client.post(
        "/api/v1/library",
        files={
            "file": (
                "函数讲义.docx",
                docx_bytes("函数的奇偶性与对称性。"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={
            "title": "函数奇偶性",
            "rights_basis": "private_teaching_only",
            "rights_statement": "本人确认该文件仅在私人空间用于教学备课。",
            "rights_acknowledged": "true",
        },
    )

    assert response.status_code == 201
    item = response.json()
    assert item["visibility"] == "private"
    assert "函数的奇偶性" in item["extracted_text"]

    review = client.patch(
        f"/api/v1/library/{item['library_item_id']}/review",
        json={
            "corrected_text": "函数的奇偶性可以借助图象对称性理解。",
            "note": "完成首轮校对",
            "confirm": True,
        },
    )
    download = client.get(f"/api/v1/library/{item['library_item_id']}/file")
    listing = client.get("/api/v1/library")

    assert review.status_code == 200
    assert review.json()["text_review_status"] == "confirmed"
    assert download.status_code == 200
    assert download.content.startswith(b"PK")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1


def test_http_rejects_short_rights_statement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = make_library(tmp_path)
    monkeypatch.setattr("app.routes.library.get_private_library", lambda: library)
    client = TestClient(app)

    response = client.post(
        "/api/v1/library",
        files={"file": ("lesson.docx", docx_bytes("函数"), "application/octet-stream")},
        data={
            "rights_basis": "private_teaching_only",
            "rights_statement": "太短",
            "rights_acknowledged": "true",
        },
    )

    assert response.status_code == 422
    assert library.stats().total == 0
