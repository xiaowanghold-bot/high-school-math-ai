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
        / "pep-a-required-1-knowledge-tree-v1.csv"
    )
    question_bank_db: Path = Field(
        default=PROJECT_ROOT / "data" / "runtime" / "question-bank.sqlite3"
    )
    pilot_batch_json: Path = Field(
        default=PROJECT_ROOT / "data" / "pilot" / "batch-2026-08-001-30q.json"
    )
    set_curation_json: Path = Field(
        default=PROJECT_ROOT / "data" / "curated" / "set-10q-corrections-v1.json"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
