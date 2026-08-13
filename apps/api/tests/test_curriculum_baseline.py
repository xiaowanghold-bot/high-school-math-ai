import json
from pathlib import Path

import pytest

from app.modules.curriculum import CurriculumBaseline, CurriculumBaselineError


def test_curriculum_baseline_rejects_catalog_drift(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.csv"
    catalog.write_text("sealed", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "baseline_id": "v1",
        "catalog_sha256": "0" * 64,
        "official_sources": [{"authority": "中华人民共和国教育部", "title": "课程标准"}],
    }, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(CurriculumBaselineError, match="偏离封存基线"):
        CurriculumBaseline.load(manifest, catalog)
