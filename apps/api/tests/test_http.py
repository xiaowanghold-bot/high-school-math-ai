from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_curriculum_tree_endpoint() -> None:
    response = client.get("/api/v1/curriculum/tree")

    assert response.status_code == 200
    payload = response.json()
    assert payload["node_id"] == "pep_a_r1"
    assert len(payload["children"]) == 5


def test_unknown_curriculum_node_is_404() -> None:
    response = client.get("/api/v1/curriculum/nodes/not-found")

    assert response.status_code == 404


def test_question_bank_stats_and_search_endpoints() -> None:
    stats_response = client.get("/api/v1/question-bank/stats")
    batches_response = client.get("/api/v1/question-bank/import-batches")
    search_response = client.get("/api/v1/questions", params={"query": "集合", "page_size": 5})

    assert stats_response.status_code == 200
    assert stats_response.json()["total"] == 30
    assert stats_response.json()["by_verification_status"]["passed"] == 18
    assert stats_response.json()["by_verification_status"]["source_inconsistency_detected"] == 3
    assert batches_response.status_code == 200
    assert batches_response.json()[0]["declared_count"] == 30
    assert search_response.status_code == 200
    payload = search_response.json()
    assert payload["total"] == 10
    assert len(payload["items"]) == 5
