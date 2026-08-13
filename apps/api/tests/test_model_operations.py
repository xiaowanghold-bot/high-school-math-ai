from pathlib import Path

import pytest

from app.modules.model_operations import ModelOperationsRegistry


def make_registry(database_path: Path) -> ModelOperationsRegistry:
    return ModelOperationsRegistry(
        database_path,
        input_rate=2.5,
        cached_input_rate=0.25,
        output_rate=15.0,
    )


def test_registry_records_usage_latency_and_cost(tmp_path: Path) -> None:
    registry = make_registry(tmp_path / "model-runs.sqlite3")

    with registry.track(
        feature="lesson_plan_generation",
        provider="openai",
        model="test-model",
        prompt_version="lesson-plan-v1",
        actor_id="teacher-1",
    ) as run:
        run.capture_response(
            {
                "usage": {
                    "input_tokens": 1000,
                    "input_tokens_details": {"cached_tokens": 400},
                    "output_tokens": 200,
                    "total_tokens": 1200,
                }
            }
        )

    dashboard = registry.dashboard(
        api_configured=True,
        model="test-model",
        reasoning_effort="low",
        timeout_seconds=90,
        lesson_plan_provider="auto",
        question_variant_provider="auto",
        solution_provider="auto",
    )

    assert dashboard.stats.total_runs == 1
    assert dashboard.stats.succeeded_runs == 1
    assert dashboard.stats.total_tokens == 1200
    assert dashboard.stats.cached_input_tokens == 400
    assert dashboard.stats.estimated_cost_usd == pytest.approx(0.0046)
    assert dashboard.recent_runs[0].actor_id == "teacher-1"
    assert dashboard.routes[0].effective_provider == "openai"


def test_registry_records_sanitized_failures(tmp_path: Path) -> None:
    registry = ModelOperationsRegistry(tmp_path / "model-runs.sqlite3")

    with pytest.raises(RuntimeError, match="调用失败"):
        with registry.track(
            feature="solution_assistant",
            provider="openai",
            model="test-model",
            prompt_version="solution-v1",
        ):
            raise RuntimeError("调用失败 Bearer sk-secret-value")

    run = registry.list_runs(limit=1)[0]
    assert run.status == "failed"
    assert run.error_category == "RuntimeError"
    assert "sk-secret-value" not in (run.error_message or "")
    assert "[REDACTED]" in (run.error_message or "")


def test_dashboard_exposes_readiness_without_exposing_credentials(tmp_path: Path) -> None:
    registry = ModelOperationsRegistry(tmp_path / "model-runs.sqlite3")

    dashboard = registry.dashboard(
        api_configured=False,
        model="test-model",
        reasoning_effort="low",
        timeout_seconds=90,
        lesson_plan_provider="auto",
        question_variant_provider="auto",
        solution_provider="openai",
    )

    routes = {route.feature: route for route in dashboard.routes}
    assert dashboard.api_configured is False
    assert dashboard.pricing_configured is False
    assert routes["lesson_plan_generation"].effective_provider == "local_template"
    assert routes["solution_assistant"].ready is False
    assert routes["private_resource_ocr"].effective_provider == "unavailable"


def test_explicit_provider_readiness_uses_its_own_key(tmp_path: Path) -> None:
    registry = ModelOperationsRegistry(tmp_path / "model-runs.sqlite3")
    dashboard = registry.dashboard(
        api_configured=True,
        model="deepseek-model",
        reasoning_effort="low",
        timeout_seconds=90,
        lesson_plan_provider="openai",
        question_variant_provider="deepseek",
        solution_provider="auto",
        external_provider="deepseek",
        provider_configuration={
            "deepseek": (True, "deepseek-model"),
            "openai": (False, "openai-model"),
        },
        ocr_api_configured=False,
    )
    routes = {route.feature: route for route in dashboard.routes}
    assert routes["lesson_plan_generation"].ready is False
    assert routes["question_variant"].model == "deepseek-model"
