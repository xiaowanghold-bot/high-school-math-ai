from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas

from app.main import app
from app.modules.pdf_imports import ImportBatchCommand, PdfImportError, PdfImportStudio


def pdf_bytes(*pages: list[str]) -> bytes:
    output = BytesIO()
    canvas = Canvas(output)
    for lines in pages:
        y = 780
        for line in lines:
            canvas.drawString(72, y, line)
            y -= 22
        canvas.showPage()
    canvas.save()
    return output.getvalue()


def command(**updates) -> ImportBatchCommand:
    values = {
        "title": "三文件结构化试点",
        "rights_basis": "question_content_user_declared_usable",
        "rights_statement": "仅处理题目事实，不复用原版式、讲义和原解析表述。",
        "rights_acknowledged": True,
        "owner_id": "owner_teacher",
    }
    values.update(updates)
    return ImportBatchCommand(**values)


def studio(tmp_path: Path) -> PdfImportStudio:
    return PdfImportStudio(tmp_path / "imports.sqlite3", tmp_path / "files")


def test_create_batch_preserves_sources_without_analyzing(tmp_path: Path) -> None:
    imports = studio(tmp_path)

    result = imports.create_batch(
        command(),
        [
            ("函数与导数.pdf", pdf_bytes(["1. Find derivative", "2. Prove monotonicity"])),
            ("概率统计.pdf", pdf_bytes(["1. Probability table"])),
        ],
    )

    assert result.batch.file_count == 2
    assert result.batch.registered_count == 2
    assert result.batch.ready_count == 0
    assert result.batch.page_count == 2
    workspace = imports.workspace()
    assert workspace.stats.batches == 1
    assert workspace.stats.files == 2
    assert workspace.stats.pages == 2
    source, file = imports.source_file(result.batch.files[0].file_id)
    assert source.parent == (tmp_path / "files").resolve()
    assert source.read_bytes().startswith(b"%PDF-")
    assert file.status == "registered"
    preview = imports.preview_page(file.file_id, 1, width=700)
    assert preview.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert imports.preview_page(file.file_id, 1, width=700) == preview


def test_analyze_extracts_page_metrics_and_is_idempotent(tmp_path: Path) -> None:
    imports = studio(tmp_path)
    created = imports.create_batch(
        command(),
        [
            (
                "立体几何.pdf",
                pdf_bytes(
                    ["1. Geometry question with enough searchable text", "2. Second question"],
                    [],
                ),
            )
        ],
    )
    file_id = created.batch.files[0].file_id

    first = imports.analyze(file_id).file
    second = imports.analyze(file_id).file

    assert first.status == "ready_for_segmentation"
    assert first.analyzed_page_count == 2
    assert first.text_page_count == 1
    assert first.scan_page_count == 1
    assert first.question_marker_count == 2
    assert len(first.pages) == 2
    assert first.pages[0].has_text_layer
    assert not first.pages[1].has_text_layer
    assert len(second.pages) == 2
    assert second.question_marker_count == 2


def test_duplicate_invalid_and_rights_gates(tmp_path: Path) -> None:
    imports = studio(tmp_path)
    content = pdf_bytes(["1. A valid question with enough text"])
    created = imports.create_batch(command(), [("sets.pdf", content)])

    with pytest.raises(PdfImportError, match="已登记"):
        imports.create_batch(command(title="重复批次"), [("copy.pdf", content)])
    with pytest.raises(PdfImportError, match="不是有效 PDF"):
        imports.create_batch(command(), [("payload.pdf", b"not pdf")])
    with pytest.raises(PdfImportError, match="必须确认"):
        imports.create_batch(
            command(rights_acknowledged=False), [("another.pdf", pdf_bytes(["1. Another"]))]
        )
    assert imports.workspace().stats.files == 1
    assert imports.inspect(created.batch.files[0].file_id).pages == []


def test_batch_analysis_and_http_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    imports = studio(tmp_path)
    monkeypatch.setattr("app.routes.imports.get_pdf_import_studio", lambda: imports)
    client = TestClient(app)

    response = client.post(
        "/api/v1/imports/batches",
        files=[
            ("files", ("functions.pdf", pdf_bytes(["1. Function question with enough text"]), "application/pdf")),
            ("files", ("probability.pdf", pdf_bytes(["1. Probability question with enough text"]), "application/pdf")),
        ],
        data={
            "title": "HTTP 导入批次",
            "rights_basis": "licensed",
            "rights_statement": "已获得用于产品加工和展示的明确授权。",
            "rights_acknowledged": "true",
            "owner_id": "owner_teacher",
        },
    )
    assert response.status_code == 201
    batch = response.json()["batch"]
    assert batch["file_count"] == 2

    analyzed = client.post(f"/api/v1/imports/batches/{batch['batch_id']}/analyze")
    assert analyzed.status_code == 200
    assert analyzed.json()["analyzed_count"] == 2

    workspace = client.get("/api/v1/imports")
    assert workspace.status_code == 200
    assert workspace.json()["stats"]["ready_files"] == 2

    file_id = batch["files"][0]["file_id"]
    detail = client.get(f"/api/v1/imports/files/{file_id}")
    source = client.get(f"/api/v1/imports/files/{file_id}/source")
    preview = client.get(f"/api/v1/imports/files/{file_id}/pages/1/preview")
    assert detail.status_code == 200
    assert detail.json()["pages"][0]["question_marker_count"] == 1
    assert source.status_code == 200
    assert source.headers["content-type"].startswith("application/pdf")
    assert source.content.startswith(b"%PDF-")
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/png")
    assert preview.content.startswith(b"\x89PNG")


def test_question_marker_supports_exam_source_style() -> None:
    text = "1(2024·浙江绍兴·二模) 已知函数，求其单调区间。\n2（2023·湖北武汉·模拟）证明不等式。"

    assert PdfImportStudio._marker_count(text) == 2
