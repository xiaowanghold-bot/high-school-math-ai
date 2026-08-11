from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from reportlab.pdfgen.canvas import Canvas

from app.main import app
from app.modules.pdf_imports import (
    BoundaryCandidateCreate,
    BoundaryCandidateUpdate,
    ImportBatchCommand,
    PdfImportError,
    PdfImportStudio,
    StructuredMediaReference,
    StructuredMediaCropCommand,
    StructuredFormulaReviewCommand,
    StructuredQuestionDraftUpdate,
)
from app.modules.question_bank import QuestionBank


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


def test_batch_queue_pauses_and_resumes_from_page_checkpoints(tmp_path: Path) -> None:
    imports = studio(tmp_path)
    created = imports.create_batch(
        command(),
        [
            (
                "函数与导数.pdf",
                pdf_bytes(
                    ["1. First page with enough searchable text"],
                    ["2. Second page with enough searchable text"],
                    ["3. Third page with enough searchable text"],
                ),
            )
        ],
    )
    batch_id = created.batch.batch_id
    file_id = created.batch.files[0].file_id

    queued = imports.queue_batch(batch_id)
    assert queued.queued_count == 1
    assert queued.batch.queued_count == 1

    first_step = imports.process_next(batch_id, page_budget=1)
    assert first_step.processed_pages == 1
    assert first_step.file is not None
    assert first_step.file.status == "queued"
    assert first_step.file.progress_percent == pytest.approx(33.3)
    assert first_step.file.resume_page == 2

    paused = imports.pause_batch(batch_id)
    assert paused.batch.paused_count == 1
    resumed = imports.queue_batch(batch_id)
    assert resumed.batch.queued_count == 1

    imports.process_next(batch_id, page_budget=1)
    completed = imports.process_next(batch_id, page_budget=1)
    assert completed.file is not None
    assert completed.file.status == "ready_for_segmentation"
    assert completed.file.analyzed_page_count == 3
    assert completed.file.resume_page is None
    assert completed.remaining_count == 0
    assert imports.inspect(file_id).question_marker_count == 3


def test_failed_analysis_preserves_pages_and_retries_from_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    imports = studio(tmp_path)
    created = imports.create_batch(
        command(),
        [("概率统计.pdf", pdf_bytes(["1. First valid page"], ["2. Second valid page"]))],
    )
    batch_id = created.batch.batch_id
    file_id = created.batch.files[0].file_id
    original_checkpoint = imports._checkpoint_page

    def fail_second_page(target_file_id: str, page_number: int, page: object) -> None:
        if page_number == 2:
            raise RuntimeError("synthetic page failure")
        original_checkpoint(target_file_id, page_number, page)

    monkeypatch.setattr(imports, "_checkpoint_page", fail_second_page)
    with pytest.raises(PdfImportError, match="synthetic page failure"):
        imports.analyze(file_id)

    failed = imports.inspect(file_id)
    assert failed.status == "failed"
    assert failed.analyzed_page_count == 1
    assert failed.resume_page == 2

    monkeypatch.setattr(imports, "_checkpoint_page", original_checkpoint)
    imports.queue_batch(batch_id)
    retried = imports.process_next(batch_id, page_budget=10)
    assert retried.file is not None
    assert retried.file.status == "ready_for_segmentation"
    assert retried.processed_pages == 1


def test_question_estimate_is_loaded_from_audit_catalog(tmp_path: Path) -> None:
    estimates = tmp_path / "estimates.csv"
    estimates.write_text(
        "filename,preliminary_question_estimate\n大题 函数与导数.pdf,40\n",
        encoding="utf-8",
    )
    imports = PdfImportStudio(
        tmp_path / "imports.sqlite3", tmp_path / "files", estimates
    )

    created = imports.create_batch(
        command(), [("大题 函数与导数.pdf", pdf_bytes(["1. Function question"]))]
    )

    assert created.batch.estimated_question_count == 40
    assert created.batch.files[0].estimated_question_count == 40
    assert imports.workspace().stats.estimated_questions == 40


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


def test_queue_http_contract_processes_bounded_page_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imports = studio(tmp_path)
    monkeypatch.setattr("app.routes.imports.get_pdf_import_studio", lambda: imports)
    client = TestClient(app)
    created = imports.create_batch(
        command(title="断点队列接口测试"),
        [("queue.pdf", pdf_bytes(["1. First page"], ["2. Second page"]))],
    )
    batch_id = created.batch.batch_id

    queued = client.post(f"/api/v1/imports/batches/{batch_id}/queue")
    first = client.post(
        f"/api/v1/imports/batches/{batch_id}/process-next",
        params={"page_budget": 1},
    )
    paused = client.post(f"/api/v1/imports/batches/{batch_id}/pause")

    assert queued.status_code == 200
    assert queued.json()["queued_count"] == 1
    assert first.status_code == 200
    assert first.json()["processed_pages"] == 1
    assert first.json()["file"]["resume_page"] == 2
    assert paused.status_code == 200
    assert paused.json()["batch"]["paused_count"] == 1


def test_question_marker_supports_exam_source_style() -> None:
    text = "1(2024·浙江绍兴·二模) 已知函数，求其单调区间。\n2（2023·湖北武汉·模拟）证明不等式。"

    assert PdfImportStudio._marker_count(text) == 2


def test_boundary_proposal_handles_cross_page_content_and_teacher_review(tmp_path: Path) -> None:
    imports = studio(tmp_path)
    created = imports.create_batch(
        command(),
        [
            (
                "函数边界.pdf",
                pdf_bytes(
                    [
                        "1. Find the derivative and discuss monotonicity (1) calculate (2) prove",
                        "2. Given a sequence, find its general term",
                    ],
                    ["continued conditions and final request without a new marker"],
                ),
            )
        ],
    )
    file_id = created.batch.files[0].file_id
    imports.analyze(file_id)

    proposal = imports.propose_boundary_candidates(file_id)

    assert proposal.created_count == 2
    assert proposal.candidates.total == 2
    assert proposal.candidates.items[0].subquestion_count == 2
    assert proposal.candidates.items[1].start_page == 1
    assert proposal.candidates.items[1].end_page == 2
    assert "continued conditions" in proposal.candidates.items[1].stem_text
    assert imports.propose_boundary_candidates(file_id).created_count == 0

    reviewed = imports.update_boundary_candidate(
        file_id,
        proposal.candidates.items[0].candidate_id,
        BoundaryCandidateUpdate(
            start_page=1,
            end_page=1,
            stem_text="1. Teacher corrected stem",
            question_type="open_response",
            subquestion_count=2,
            note="已核对原 PDF",
            status="confirmed",
        ),
    )
    assert reviewed.status == "confirmed"
    assert reviewed.editor_id == "owner_teacher"
    assert imports.boundary_candidates(file_id).confirmed_count == 1


def test_boundary_manual_candidate_and_page_validation(tmp_path: Path) -> None:
    imports = studio(tmp_path)
    created = imports.create_batch(
        command(), [("无稳定题号.pdf", pdf_bytes(["A question without a stable marker"]))]
    )
    file_id = created.batch.files[0].file_id
    imports.analyze(file_id)

    manual = imports.create_boundary_candidate(
        file_id,
        BoundaryCandidateCreate(
            start_page=1,
            end_page=1,
            stem_text="教师手工补录的题目",
            question_type="fill_blank",
            note="自动规则未识别",
        ),
    )

    assert manual.position == 1
    assert manual.status == "draft"
    with pytest.raises(PdfImportError, match="结束页"):
        imports.update_boundary_candidate(
            file_id,
            manual.candidate_id,
            BoundaryCandidateUpdate(
                start_page=2,
                end_page=1,
                stem_text=manual.stem_text,
            ),
        )


def test_boundary_http_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    imports = studio(tmp_path)
    monkeypatch.setattr("app.routes.imports.get_pdf_import_studio", lambda: imports)
    created = imports.create_batch(
        command(), [("HTTP边界.pdf", pdf_bytes(["1. First question", "2. Second question"]))]
    )
    file_id = created.batch.files[0].file_id
    imports.analyze(file_id)
    client = TestClient(app)

    proposed = client.post(f"/api/v1/imports/files/{file_id}/boundary-candidates/propose")
    assert proposed.status_code == 200
    candidate = proposed.json()["candidates"]["items"][0]
    assert proposed.json()["created_count"] == 2

    updated = client.patch(
        f"/api/v1/imports/files/{file_id}/boundary-candidates/{candidate['candidate_id']}",
        json={
            "start_page": 1,
            "end_page": 1,
            "stem_text": candidate["stem_text"],
            "question_type": "single_choice",
            "subquestion_count": 0,
            "status": "discarded",
            "note": "重复题",
            "editor_id": "owner_teacher",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "discarded"
    listed = client.get(f"/api/v1/imports/files/{file_id}/boundary-candidates")
    assert listed.status_code == 200
    assert listed.json()["discarded_count"] == 1


def test_structured_draft_requires_confirmed_boundary_and_formula_review(tmp_path: Path) -> None:
    imports = studio(tmp_path)
    created = imports.create_batch(
        command(),
        [("结构化题.pdf", pdf_bytes(["1. Given x=2 choose an answer A. 1 B. 2 C. 3 D. 4", "Answer: B"]))],
    )
    file_id = created.batch.files[0].file_id
    imports.analyze(file_id)
    boundary = imports.propose_boundary_candidates(file_id).candidates.items[0]

    with pytest.raises(PdfImportError, match="至少确认"):
        imports.propose_structured_question_drafts(file_id)

    imports.update_boundary_candidate(
        file_id,
        boundary.candidate_id,
        BoundaryCandidateUpdate(
            start_page=1,
            end_page=1,
            stem_text=boundary.stem_text,
            question_type="single_choice",
            status="confirmed",
        ),
    )
    proposal = imports.propose_structured_question_drafts(file_id)
    assert proposal.created_count == 1
    draft = proposal.drafts.items[0]
    assert draft.options[0].key == "A"
    assert "Answer" not in draft.stem_plain
    assert imports.propose_structured_question_drafts(file_id).created_count == 0

    with pytest.raises(PdfImportError, match="当前版本公式"):
        imports.update_structured_question_draft(
            file_id,
            draft.draft_id,
            StructuredQuestionDraftUpdate(
                **{
                    **draft.model_dump(exclude={"draft_id", "file_id", "boundary_candidate_id", "position", "start_page", "end_page", "source_text", "warnings", "imported_question_id", "created_at", "updated_at"}),
                    "status": "confirmed",
                }
            ),
        )

    saved = imports.update_structured_question_draft(
        file_id,
        draft.draft_id,
        StructuredQuestionDraftUpdate(
            **{
                **draft.model_dump(exclude={"draft_id", "file_id", "boundary_candidate_id", "position", "start_page", "end_page", "source_text", "warnings", "imported_question_id", "created_at", "updated_at"}),
                "stem_latex": "Given $x=2$ choose an answer",
                "formula_status": "needs_review",
                "status": "draft",
                "media_references": [
                    StructuredMediaReference(page_number=1, placement="stem", note="图形待裁剪")
                ],
            }
        ),
    )
    checked = imports.review_structured_formula(
        file_id, draft.draft_id, StructuredFormulaReviewCommand(confirm=False)
    )
    assert checked.formula_check.status == "passed"
    assert not checked.formula_check.teacher_confirmed
    assert checked.formula_status == "pending"
    formula_confirmed = imports.review_structured_formula(
        file_id, draft.draft_id, StructuredFormulaReviewCommand(confirm=True)
    )
    assert formula_confirmed.formula_check.teacher_confirmed
    confirmed = imports.update_structured_question_draft(
        file_id,
        draft.draft_id,
        StructuredQuestionDraftUpdate(
            **{
                **formula_confirmed.model_dump(exclude={"draft_id", "file_id", "boundary_candidate_id", "position", "start_page", "end_page", "source_text", "warnings", "media_crops", "formula_check", "imported_question_id", "created_at", "updated_at"}),
                "status": "confirmed",
            }
        ),
    )
    assert confirmed.status == "confirmed"
    assert confirmed.formula_status == "confirmed"
    with pytest.raises(PdfImportError, match="伪造"):
        imports.update_structured_question_draft(
            file_id,
            draft.draft_id,
            StructuredQuestionDraftUpdate(
                **{
                    **confirmed.model_dump(exclude={"draft_id", "file_id", "boundary_candidate_id", "position", "start_page", "end_page", "source_text", "warnings", "imported_question_id", "created_at", "updated_at"}),
                    "status": "imported",
                }
            ),
        )
    invalidated = imports.update_structured_question_draft(
        file_id,
        draft.draft_id,
        StructuredQuestionDraftUpdate(
            **{
                **confirmed.model_dump(exclude={"draft_id", "file_id", "boundary_candidate_id", "position", "start_page", "end_page", "source_text", "warnings", "media_crops", "formula_check", "imported_question_id", "created_at", "updated_at"}),
                "stem_latex": "Given $x=3$ choose an answer",
                "status": "draft",
            }
        ),
    )
    assert invalidated.formula_status == "needs_review"
    assert invalidated.formula_check is None


def test_structured_draft_http_import_is_private_and_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imports = studio(tmp_path)
    bank = QuestionBank(tmp_path / "questions.sqlite3", tmp_path / "question-media")
    monkeypatch.setattr("app.routes.imports.get_pdf_import_studio", lambda: imports)
    monkeypatch.setattr("app.routes.imports.get_import_question_bank", lambda: bank)
    created = imports.create_batch(
        command(), [("HTTP结构化.pdf", pdf_bytes(["1. Prove the identity"]))]
    )
    file_id = created.batch.files[0].file_id
    imports.analyze(file_id)
    boundary = imports.propose_boundary_candidates(file_id).candidates.items[0]
    imports.update_boundary_candidate(
        file_id,
        boundary.candidate_id,
        BoundaryCandidateUpdate(
            start_page=1,
            end_page=1,
            stem_text=boundary.stem_text,
            question_type="open_response",
            status="confirmed",
        ),
    )
    client = TestClient(app)
    proposed = client.post(f"/api/v1/imports/files/{file_id}/structured-drafts/propose")
    assert proposed.status_code == 200
    draft = proposed.json()["drafts"]["items"][0]
    draft.update({"formula_status": "needs_review", "status": "draft"})
    updated = client.patch(
        f"/api/v1/imports/files/{file_id}/structured-drafts/{draft['draft_id']}",
        json={key: value for key, value in draft.items() if key in StructuredQuestionDraftUpdate.model_fields},
    )
    assert updated.status_code == 200
    formula_review = client.post(
        f"/api/v1/imports/files/{file_id}/structured-drafts/{draft['draft_id']}/formula-review",
        json={"confirm": True, "reviewer_id": "owner_teacher"},
    )
    assert formula_review.status_code == 200
    assert formula_review.json()["formula_status"] == "confirmed"
    reviewed_draft = formula_review.json()
    reviewed_draft["status"] = "confirmed"
    updated = client.patch(
        f"/api/v1/imports/files/{file_id}/structured-drafts/{draft['draft_id']}",
        json={key: value for key, value in reviewed_draft.items() if key in StructuredQuestionDraftUpdate.model_fields},
    )
    assert updated.status_code == 200

    cropped = client.post(
        f"/api/v1/imports/files/{file_id}/structured-drafts/{draft['draft_id']}/media-crops",
        json={
            "page_number": 1,
            "placement": "stem",
            "x_ratio": 0.1,
            "y_ratio": 0.2,
            "width_ratio": 0.4,
            "height_ratio": 0.25,
            "note": "题干示意图",
            "editor_id": "owner_teacher",
        },
    )
    assert cropped.status_code == 201
    crop = cropped.json()
    assert crop["pixel_width"] == 720
    assert crop["pixel_height"] > 500
    crop_file = client.get(f"/api/v1/imports/media-crops/{crop['crop_id']}/file")
    assert crop_file.status_code == 200
    with Image.open(BytesIO(crop_file.content)) as crop_image:
        assert crop_image.size == (crop["pixel_width"], crop["pixel_height"])

    imported = client.post(
        f"/api/v1/imports/files/{file_id}/structured-drafts/{draft['draft_id']}/import"
    )
    repeated = client.post(
        f"/api/v1/imports/files/{file_id}/structured-drafts/{draft['draft_id']}/import"
    )
    assert imported.status_code == 200
    assert repeated.status_code == 200
    assert repeated.json()["already_imported"]
    locked_delete = client.delete(
        f"/api/v1/imports/files/{file_id}/structured-drafts/{draft['draft_id']}/media-crops/{crop['crop_id']}"
    )
    assert locked_delete.status_code == 409
    question = bank.get_question(imported.json()["question_id"])
    assert question.visibility == "private"
    assert question.review_status == "pending"
    assert question.verification_status == "needs_math_review"
    assert question.source_page_start == 1
    assert len(question.images) == 1
    assert question.images[0].placement == "stem"
    assert question.images[0].width == crop["pixel_width"]


def test_formula_review_locates_unreadable_glyphs_and_latex_structure(tmp_path: Path) -> None:
    imports = studio(tmp_path)
    created = imports.create_batch(
        command(), [("公式异常.pdf", pdf_bytes(["1. Formula question with enough text"]))]
    )
    file_id = created.batch.files[0].file_id
    imports.analyze(file_id)
    boundary = imports.propose_boundary_candidates(file_id).candidates.items[0]
    imports.update_boundary_candidate(
        file_id,
        boundary.candidate_id,
        BoundaryCandidateUpdate(
            start_page=1, end_page=1, stem_text=boundary.stem_text,
            question_type="open_response", status="confirmed",
        ),
    )
    draft = imports.propose_structured_question_drafts(file_id).drafts.items[0]
    imports.update_structured_question_draft(
        file_id,
        draft.draft_id,
        StructuredQuestionDraftUpdate(
            **{
                **draft.model_dump(exclude={"draft_id", "file_id", "boundary_candidate_id", "position", "start_page", "end_page", "source_text", "warnings", "media_crops", "formula_check", "imported_question_id", "created_at", "updated_at"}),
                "stem_plain": "已知函数 fx=x+1",
                "stem_latex": "已知函数 $f(x)=\\frac{x+1$",
            }
        ),
    )
    reviewed = imports.review_structured_formula(
        file_id, draft.draft_id, StructuredFormulaReviewCommand(confirm=True)
    )
    assert reviewed.formula_status == "needs_review"
    assert not reviewed.formula_check.teacher_confirmed
    issue_codes = {issue.code for issue in reviewed.formula_check.issues}
    assert "unreadable_glyph" in issue_codes
    assert "unbalanced_braces" in issue_codes
    assert any(issue.excerpt for issue in reviewed.formula_check.issues)


def test_structured_media_crop_gates_and_delete(tmp_path: Path) -> None:
    imports = studio(tmp_path)
    created = imports.create_batch(
        command(), [("跨页配图.pdf", pdf_bytes(["1. Geometry question"], ["continued figure"]))]
    )
    file_id = created.batch.files[0].file_id
    imports.analyze(file_id)
    boundary = imports.propose_boundary_candidates(file_id).candidates.items[0]
    imports.update_boundary_candidate(
        file_id,
        boundary.candidate_id,
        BoundaryCandidateUpdate(
            start_page=1, end_page=2, stem_text=boundary.stem_text,
            question_type="open_response", status="confirmed",
        ),
    )
    draft = imports.propose_structured_question_drafts(file_id).drafts.items[0]
    with pytest.raises(PdfImportError, match="右边界"):
        imports.create_media_crop(
            file_id,
            draft.draft_id,
            StructuredMediaCropCommand(
                page_number=1, x_ratio=0.8, y_ratio=0.1,
                width_ratio=0.3, height_ratio=0.2,
            ),
        )
    with pytest.raises(PdfImportError, match="裁剪页"):
        imports.create_media_crop(
            file_id,
            draft.draft_id,
            StructuredMediaCropCommand(
                page_number=3, x_ratio=0.1, y_ratio=0.1,
                width_ratio=0.2, height_ratio=0.2,
            ),
        )
    crop = imports.create_media_crop(
        file_id,
        draft.draft_id,
        StructuredMediaCropCommand(
            page_number=2, x_ratio=0.1, y_ratio=0.1,
            width_ratio=0.2, height_ratio=0.2,
        ),
    )
    path, _ = imports.media_crop_file(crop.crop_id)
    assert path.exists()
    assert imports.structured_question_drafts(file_id).items[0].media_crops[0].crop_id == crop.crop_id
    imports.delete_media_crop(file_id, draft.draft_id, crop.crop_id)
    assert not path.exists()
    assert imports.structured_question_drafts(file_id).items[0].media_crops == []
