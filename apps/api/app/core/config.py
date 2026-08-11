from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MATH_AI_", env_file=".env", extra="ignore")

    app_name: str = "高中数学 AI 备课工作台"
    environment: str = "development"
    cors_origins: str = "http://localhost:3000"
    curriculum_csv: Path = Field(
        default=PROJECT_ROOT
        / "docs"
        / "high-school-math-ai"
        / "curriculum"
        / "pep-a-full-knowledge-tree-v1.csv"
    )
    curriculum_review_db: Path = Field(
        default=PROJECT_ROOT / "data" / "runtime" / "curriculum-reviews.sqlite3"
    )
    question_bank_db: Path = Field(
        default=PROJECT_ROOT / "data" / "runtime" / "question-bank.sqlite3"
    )
    question_media_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "runtime" / "question-media"
    )
    private_library_db: Path = Field(
        default=PROJECT_ROOT / "data" / "runtime" / "private-library.sqlite3"
    )
    private_library_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "runtime" / "private-library-files"
    )
    pdf_import_db: Path = Field(
        default=PROJECT_ROOT / "data" / "runtime" / "pdf-imports.sqlite3"
    )
    pdf_import_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "runtime" / "pdf-import-files"
    )
    lesson_plan_db: Path = Field(
        default=PROJECT_ROOT / "data" / "runtime" / "lesson-plans.sqlite3"
    )
    exam_paper_db: Path = Field(
        default=PROJECT_ROOT / "data" / "runtime" / "exam-papers.sqlite3"
    )
    exam_paper_asset_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "runtime" / "exam-paper-assets"
    )
    model_operations_db: Path = Field(
        default=PROJECT_ROOT / "data" / "runtime" / "model-operations-v1.sqlite3"
    )
    lesson_export_dir: Path = Field(default=PROJECT_ROOT / "output")
    cjk_font_regular: Path | None = None
    cjk_font_bold: Path | None = None
    lesson_plan_provider: str = "auto"
    question_variant_provider: str = "auto"
    solution_provider: str = "auto"
    openai_api_key: str = ""
    openai_model: str = "gpt-5.6-terra"
    openai_reasoning_effort: str = "low"
    openai_timeout_seconds: int = 90
    openai_input_usd_per_million: float | None = None
    openai_cached_input_usd_per_million: float | None = None
    openai_output_usd_per_million: float | None = None
    pilot_batch_json: Path = Field(
        default=PROJECT_ROOT / "data" / "pilot" / "batch-2026-08-001-30q.json"
    )
    set_curation_json: Path = Field(
        default=PROJECT_ROOT / "data" / "curated" / "set-10q-corrections-v1.json"
    )
    probability_curation_json: Path = Field(
        default=PROJECT_ROOT / "data" / "curated" / "probability-4q-corrections-v1.json"
    )
    probability_curation_2_json: Path = Field(
        default=PROJECT_ROOT / "data" / "curated" / "probability-6q-corrections-v1.json"
    )
    function_pilot_batch_json: Path = Field(
        default=PROJECT_ROOT / "data" / "pilot" / "function-properties-5q-v1.json"
    )
    function_curation_json: Path = Field(
        default=PROJECT_ROOT / "data" / "curated" / "function-properties-5q-corrections-v1.json"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
