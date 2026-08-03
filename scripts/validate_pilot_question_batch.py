from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


REQUIRED_TOP_LEVEL = {
    "id",
    "status",
    "visibility",
    "stem",
    "question_type",
    "answer",
    "curriculum",
    "pedagogy",
    "verification",
    "source",
    "provenance",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the 30-question pilot batch.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    questions = payload.get("questions", [])
    errors: list[str] = []
    warnings: list[str] = []
    ids: list[str] = []
    stem_hashes: dict[str, str] = {}

    for index, question in enumerate(questions, start=1):
        missing = sorted(REQUIRED_TOP_LEVEL - set(question))
        if missing:
            errors.append(f"题目{index}缺少字段: {', '.join(missing)}")
        qid = question.get("id", f"index-{index}")
        ids.append(qid)
        if not question.get("stem", {}).get("plain_text"):
            errors.append(f"{qid}: 题干为空")
        stem_text = question.get("stem", {}).get("plain_text", "")
        normalized_stem = re.sub(r"\s+", "", stem_text)
        stem_hash = hashlib.sha256(normalized_stem.encode("utf-8")).hexdigest()
        if stem_hash in stem_hashes:
            errors.append(f"{qid}: 与{stem_hashes[stem_hash]}题干完全重复")
        stem_hashes[stem_hash] = qid
        forbidden = [marker for marker in ("【解析】", "【详解】", "【分析】", "\n解：", "学科网") if marker in stem_text]
        if forbidden:
            errors.append(f"{qid}: 题干混入排除材料标记: {', '.join(forbidden)}")
        if question.get("visibility") != "private":
            errors.append(f"{qid}: 试点题必须为private")
        if question.get("source", {}).get("license_status") != "question_content_user_declared_usable":
            errors.append(f"{qid}: 权利状态不符合试点约束")
        if question.get("question_type") == "single_choice":
            options = question.get("options", [])
            if len(options) != 4:
                warnings.append(f"{qid}: 选择题选项解析为{len(options)}个，需对照原页")
            value = question.get("answer", {}).get("value")
            if value not in {"A", "B", "C", "D"}:
                warnings.append(f"{qid}: 客观答案不是A-D: {value!r}")
        if question.get("verification", {}).get("status") == "source_inconsistency_detected":
            warnings.append(f"{qid}: 检出原资料答案/详解表述不一致")

    duplicates = [qid for qid, count in Counter(ids).items() if count > 1]
    if duplicates:
        errors.append(f"ID重复: {', '.join(duplicates)}")
    if payload.get("question_count") != len(questions):
        errors.append("question_count与实际数组长度不一致")
    if len(questions) != 30:
        errors.append(f"试点批次应为30题，实际为{len(questions)}题")

    status_counts = Counter(question.get("verification", {}).get("status") for question in questions)
    answer_counts = Counter(question.get("answer", {}).get("status") for question in questions)
    source_counts = Counter(question.get("source", {}).get("document_name") for question in questions)
    report = {
        "input": str(args.input.resolve()),
        "valid": not errors,
        "question_count": len(questions),
        "errors": errors,
        "warnings": warnings,
        "verification_status_counts": dict(status_counts),
        "answer_status_counts": dict(answer_counts),
        "source_counts": dict(source_counts),
        "exact_duplicate_stem_count": len(questions) - len(stem_hashes),
        "excluded_material_leak_count": sum(1 for error in errors if "混入排除材料" in error),
    }

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
