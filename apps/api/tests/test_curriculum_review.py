from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.curriculum import (
    CurriculumGovernance,
    CurriculumNode,
    CurriculumNodePatch,
    CurriculumReviewCommand,
    CurriculumReviewError,
    CurriculumReviewRepository,
    InMemoryCurriculumCatalog,
)
from app.routes.curriculum import get_catalog, get_governance


def _node(
    node_id: str,
    *,
    parent_id: str | None,
    node_type: str,
    code: str,
    name: str,
) -> CurriculumNode:
    return CurriculumNode(
        node_id=node_id,
        parent_id=parent_id,
        volume="必修第一册" if node_type != "textbook" else "全册",
        node_type=node_type,
        code=code,
        name=name,
        description=f"{name}说明",
        primary_competencies=["数学抽象"],
        typical_question_types=["基础题"],
        common_errors=["概念混淆"],
        gaokao_priority="medium",
        status="draft_for_teacher_review",
        reviewed_by="catalog_seed",
    )


def _governance(tmp_path: Path) -> CurriculumGovernance:
    catalog = InMemoryCurriculumCatalog(
        [
            _node("root", parent_id=None, node_type="textbook", code="0", name="人教A版"),
            _node("volume", parent_id="root", node_type="volume", code="1", name="必修第一册"),
            _node("chapter", parent_id="volume", node_type="chapter", code="1.1", name="集合"),
            _node("section", parent_id="chapter", node_type="section", code="1.1.1", name="集合的概念"),
            _node("kp1", parent_id="section", node_type="knowledge_point", code="1.1.1.1", name="集合的含义"),
            _node("kp2", parent_id="section", node_type="knowledge_point", code="1.1.1.2", name="元素与集合"),
        ]
    )
    return CurriculumGovernance(
        base_catalog=catalog,
        repository=CurriculumReviewRepository(tmp_path / "curriculum-reviews.sqlite3"),
    )


def test_workspace_tracks_review_counts_and_volume_root(tmp_path: Path) -> None:
    governance = _governance(tmp_path)

    workspace = governance.workspace(volume="必修第一册")

    assert workspace.volume_node_id == "volume"
    assert workspace.counts.total == 5
    assert workspace.counts.pending == 5
    assert {item.node_id for item in workspace.items} == {
        "volume",
        "chapter",
        "section",
        "kp1",
        "kp2",
    }


def test_draft_edit_overlays_catalog_without_mutating_base(tmp_path: Path) -> None:
    governance = _governance(tmp_path)

    result = governance.submit(
        "kp1",
        CurriculumReviewCommand(
            decision="draft",
            changes=CurriculumNodePatch(
                name="集合含义与表示",
                typical_question_types=["概念辨析", "集合表示"],
                gaokao_priority="high",
            ),
            note="按课堂表述修订",
        ),
    )

    assert result.affected_count == 1
    assert governance.base_catalog.get_node("kp1").name == "集合的含义"
    assert governance.catalog.get_node("kp1").name == "集合含义与表示"
    assert governance.catalog.get_node("kp1").status == "draft_for_teacher_review"
    assert governance.catalog.search("集合表示")[0].node_id == "kp1"
    assert governance.inspect("kp1").history[0].note == "按课堂表述修订"


def test_cascade_approval_records_section_and_descendants(tmp_path: Path) -> None:
    governance = _governance(tmp_path)

    result = governance.submit(
        "section",
        CurriculumReviewCommand(
            decision="approved",
            changes=CurriculumNodePatch(description="教师确认后的节说明"),
            note="本节审核完成",
            cascade=True,
        ),
    )

    assert result.affected_count == 3
    assert result.detail.review_status == "approved"
    assert governance.catalog.get_node("section").description == "教师确认后的节说明"
    assert governance.catalog.get_node("kp1").status == "teacher_approved"
    workspace = governance.workspace(volume="必修第一册")
    assert workspace.counts.approved == 3
    assert workspace.counts.pending == 2


def test_request_changes_requires_note_and_preserves_effective_content(tmp_path: Path) -> None:
    governance = _governance(tmp_path)

    with pytest.raises(CurriculumReviewError):
        governance.submit(
            "kp2",
            CurriculumReviewCommand(decision="changes_requested"),
        )

    governance.submit(
        "kp2",
        CurriculumReviewCommand(
            decision="changes_requested",
            changes=CurriculumNodePatch(name="不应生效的名称"),
            note="需重新核对教材表述",
        ),
    )

    assert governance.catalog.get_node("kp2").name == "元素与集合"
    assert governance.catalog.get_node("kp2").status == "changes_requested"


def test_curriculum_review_http_contract(tmp_path: Path) -> None:
    governance = _governance(tmp_path)
    app.dependency_overrides[get_governance] = lambda: governance
    app.dependency_overrides[get_catalog] = lambda: governance.catalog
    client = TestClient(app)
    try:
        workspace = client.get(
            "/api/v1/curriculum/reviews",
            params={"volume": "必修第一册", "node_type": "knowledge_point"},
        )
        assert workspace.status_code == 200
        assert len(workspace.json()["items"]) == 2

        reviewed = client.post(
            "/api/v1/curriculum/reviews/kp1",
            json={
                "decision": "approved",
                "changes": {"name": "集合含义（教师审定）"},
                "note": "确认",
                "reviewer_id": "owner_teacher",
                "cascade": False,
            },
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["detail"]["effective_node"]["name"] == "集合含义（教师审定）"

        node = client.get("/api/v1/curriculum/nodes/kp1")
        assert node.status_code == 200
        assert node.json()["status"] == "teacher_approved"
    finally:
        app.dependency_overrides.clear()
