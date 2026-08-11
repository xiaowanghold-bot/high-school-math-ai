import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient


_model_operations_test_dir = tempfile.TemporaryDirectory(prefix="math-ai-model-ops-")
os.environ["MATH_AI_MODEL_OPERATIONS_DB"] = str(
    Path(_model_operations_test_dir.name) / "model-operations.sqlite3"
)

from app.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_model_operations_dashboard_endpoint() -> None:
    response = client.get("/api/v1/admin/model-operations", params={"limit": 5})

    assert response.status_code == 200
    payload = response.json()
    assert payload["model"]
    assert len(payload["routes"]) == 5
    assert {route["feature"] for route in payload["routes"]} == {
        "lesson_plan_generation",
        "lesson_block_rewrite",
        "question_variant",
        "solution_assistant",
        "private_resource_ocr",
    }
    assert len(payload["recent_runs"]) <= 5


def test_curriculum_tree_endpoint() -> None:
    response = client.get("/api/v1/curriculum/tree")

    assert response.status_code == 200
    payload = response.json()
    assert payload["node_id"] == "pep_a"
    assert len(payload["children"]) == 5


def test_unknown_curriculum_node_is_404() -> None:
    response = client.get("/api/v1/curriculum/nodes/not-found")

    assert response.status_code == 404


def test_curriculum_search_endpoint() -> None:
    response = client.get(
        "/api/v1/curriculum/search", params={"query": "单调性", "limit": 5}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert payload["items"][0]["node_id"] == "kp_r1_3_2_01"
    assert payload["items"][0]["section"] == "函数的基本性质"


def test_question_bank_stats_and_search_endpoints() -> None:
    stats_response = client.get("/api/v1/question-bank/stats")
    batches_response = client.get("/api/v1/question-bank/import-batches")
    search_response = client.get("/api/v1/questions", params={"query": "集合", "page_size": 5})

    assert stats_response.status_code == 200
    assert stats_response.json()["total"] >= 35
    assert stats_response.json()["by_verification_status"]["passed"] >= 22
    assert stats_response.json()["by_verification_status"]["source_inconsistency_detected"] >= 4
    assert "verified_pending_teacher" in stats_response.json()["by_work_queue"]
    assert "solid_geometry" in stats_response.json()["by_module"]
    assert batches_response.status_code == 200
    assert {5, 30}.issubset(
        {batch["declared_count"] for batch in batches_response.json()}
    )
    assert search_response.status_code == 200
    payload = search_response.json()
    assert payload["total"] == 10
    assert len(payload["items"]) == 5

    queue_response = client.get(
        "/api/v1/questions",
        params={"work_queue": "source_conflict", "page_size": 50},
    )
    assert queue_response.status_code == 200
    assert all(
        item["verification_status"] == "source_inconsistency_detected"
        for item in queue_response.json()["items"]
    )


def test_lesson_plan_generation_and_update_endpoints() -> None:
    generated_response = client.post(
        "/api/v1/lesson-plans/generate",
        json={
            "curriculum_node_id": "pep_a_r1_c3_s2",
            "lesson_type": "new_lesson",
            "duration_minutes": 45,
            "student_profile": "高一平行班，基础中等",
            "focus": "突出单调性定义与图象直观之间的联系",
            "question_count": 2,
        },
    )

    assert generated_response.status_code == 201
    plan = generated_response.json()
    assert plan["curriculum"]["section"] == "函数的基本性质"
    assert plan["generation"]["provider"] == "local_template"
    assert len(plan["content"]["recommended_questions"]) == 2
    assert sum(item["minutes"] for item in plan["content"]["teaching_flow"]) == 45

    plan["content"]["title"] = "函数基本性质教学设计（教师修订）"
    update_response = client.patch(
        f"/api/v1/lesson-plans/{plan['lesson_plan_id']}",
        json={"content": plan["content"], "editor_id": "owner_teacher"},
    )

    assert update_response.status_code == 200
    assert update_response.json()["version"] == 2
    assert update_response.json()["content"]["title"].endswith("教师修订）")

    docx_response = client.get(
        f"/api/v1/lesson-plans/{plan['lesson_plan_id']}/export",
        params={"format": "docx"},
    )
    pdf_response = client.get(
        f"/api/v1/lesson-plans/{plan['lesson_plan_id']}/export",
        params={"format": "pdf"},
    )

    assert docx_response.status_code == 200
    assert docx_response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument"
    )
    assert docx_response.content.startswith(b"PK")
    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"].startswith("application/pdf")
    assert pdf_response.content.startswith(b"%PDF")

    lock_response = client.put(
        f"/api/v1/lesson-plans/{plan['lesson_plan_id']}/blocks/key_points/lock",
        json={"locked": True, "editor_id": "owner_teacher"},
    )
    assert lock_response.status_code == 200
    assert lock_response.json()["version"] == 3
    assert lock_response.json()["locked_blocks"] == ["key_points"]

    blocked_rewrite = client.post(
        f"/api/v1/lesson-plans/{plan['lesson_plan_id']}/blocks/key_points/rewrite",
        json={
            "instruction": "突出定义域和区间条件",
            "content": plan["content"],
            "teacher_id": "owner_teacher",
        },
    )
    assert blocked_rewrite.status_code == 422
    assert "已锁定" in blocked_rewrite.json()["detail"]

    unlock_response = client.put(
        f"/api/v1/lesson-plans/{plan['lesson_plan_id']}/blocks/key_points/lock",
        json={"locked": False, "editor_id": "owner_teacher"},
    )
    rewrite_response = client.post(
        f"/api/v1/lesson-plans/{plan['lesson_plan_id']}/blocks/key_points/rewrite",
        json={
            "instruction": "突出定义域和区间条件",
            "content": plan["content"],
            "teacher_id": "owner_teacher",
        },
    )

    assert unlock_response.status_code == 200
    assert unlock_response.json()["version"] == 4
    assert rewrite_response.status_code == 200
    assert rewrite_response.json()["block"] == "key_points"
    assert rewrite_response.json()["mode"] == "local_preview"
    assert "定义域和区间条件" in rewrite_response.json()["value"][0]
