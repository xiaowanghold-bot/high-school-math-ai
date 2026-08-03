from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def classify_module(filename: str) -> tuple[str, str]:
    if "集合与逻辑" in filename:
        return "集合与常用逻辑用语", "选填题题型"
    if "不等式、函数和三角函数" in filename:
        return "高一综合", "不等式|函数|三角函数"
    if "函数性质" in filename:
        return "函数", "函数性质综合"
    if "函数与导数" in filename or "导数" in filename:
        return "函数与导数", "导数专题"
    if "数列" in filename:
        return "数列", "数列综合"
    if "解三角形" in filename:
        return "三角函数", "解三角形"
    if "排列组合" in filename:
        return "计数原理", "排列组合与二项式定理"
    if "概率" in filename or "统计" in filename:
        return "统计与概率", "概率统计综合"
    if "圆锥曲线" in filename or "椭圆" in filename:
        if "直线与圆" in filename:
            return "解析几何", "直线与圆|圆锥曲线"
        return "圆锥曲线", "椭圆|双曲线|抛物线"
    if "直线与圆" in filename:
        return "直线与圆", "直线与圆综合"
    if "立体几何" in filename:
        return "立体几何", "立体几何综合"
    if "武汉" in filename:
        return "新高考模拟卷", "武汉调研考试"
    return "待分类", "待分类"


def classify_version(filename: str) -> str:
    if "学生版" in filename or "原卷版" in filename:
        return "student_or_question_only"
    if "解析" in filename or "老师版" in filename or "教师版" in filename or "答案" in filename:
        return "teacher_or_solved"
    return "unknown"


OVERRIDE_ESTIMATES = {
    "大题 圆锥曲线（椭圆、双曲线、抛物线）（精选30题）（学生版）(1).pdf": 30,
    "新高考数学概率黄金32题（教师版）(1).pdf": 32,
    "数学-湖北省武汉市2025届高中毕业生四月调研考试（武汉四调）试卷和答案.pdf": 19,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audit_json", type=Path)
    parser.add_argument("question_estimates_csv", type=Path)
    parser.add_argument("text_dir", type=Path)
    parser.add_argument("output_csv", type=Path)
    args = parser.parse_args()

    audit_rows = json.loads(args.audit_json.read_text(encoding="utf-8"))
    with args.question_estimates_csv.open(encoding="utf-8-sig", newline="") as stream:
        estimate_rows = {row["filename"]: row for row in csv.DictReader(stream)}

    output_rows = []
    for index, audit in enumerate(audit_rows, start=1):
        filename = audit["filename"]
        text_path = args.text_dir / f"{Path(filename).stem}.txt"
        text = text_path.read_text(encoding="utf-8")
        module, subtopic = classify_module(filename)
        version = classify_version(filename)
        estimate = int(estimate_rows[filename]["preliminary_question_estimate"])
        estimate = OVERRIDE_ESTIMATES.get(filename, estimate)

        source_signals = []
        if "学科网（北京）股份有限公司" in text or "学科网" in text:
            source_signals.append("explicit_xkw_text")
        if "数学第六感" in text or "微信公众号" in text:
            source_signals.append("explicit_wechat_source")
        creator = str(audit.get("creator_metadata", ""))
        producer = str(audit.get("producer_metadata", ""))
        if "EduEditer" in creator or "EduEditer" in producer:
            source_signals.append("eduediter_metadata_and_branded_layout")
        if not source_signals:
            source_signals.append("no_explicit_signal_found")

        rights_hold = any(signal != "no_explicit_signal_found" for signal in source_signals)
        production_rights_status = (
            "hold_for_written_license_evidence" if rights_hold else "provisional_user_attestation"
        )

        pages = int(audit["pages"])
        extraction = str(audit["extraction_class"])
        if extraction != "text_layer_good":
            ingest_priority = "P3_hybrid_ocr"
        elif pages >= 100:
            ingest_priority = "P2_large_document_parser"
        elif version == "student_or_question_only":
            ingest_priority = "P2_question_only"
        else:
            ingest_priority = "P1_structured_pilot"

        formula_strategy = (
            "full_ocr_plus_math_ocr"
            if extraction != "text_layer_good"
            else "text_blocks_plus_math_formula_reconstruction"
        )

        output_rows.append(
            {
                "batch_id": "BATCH-2026-08-001",
                "file_id": f"USRPDF-{index:03d}",
                "filename": filename,
                "source_path": audit["path"],
                "module": module,
                "subtopic": subtopic,
                "version_type": version,
                "pages": pages,
                "preliminary_question_estimate": estimate,
                "estimate_requires_parser_validation": True,
                "text_extraction_class": extraction,
                "low_text_pages": audit["low_text_pages"],
                "image_pages": audit["image_pages"],
                "formula_strategy": formula_strategy,
                "source_signals": "|".join(source_signals),
                "user_rights_declaration": "commercial_display|adaptation|model_training",
                "production_rights_status": production_rights_status,
                "ingest_priority": ingest_priority,
                "target_visibility": "rights_quarantine_until_evidence_checked",
            }
        )

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output_rows[0].keys()))
        writer.writeheader()
        writer.writerows(output_rows)

    summary = {
        "files": len(output_rows),
        "pages": sum(row["pages"] for row in output_rows),
        "preliminary_question_estimate": sum(
            row["preliminary_question_estimate"] for row in output_rows
        ),
        "rights_hold_files": sum(
            row["production_rights_status"] == "hold_for_written_license_evidence"
            for row in output_rows
        ),
        "hybrid_ocr_files": sum(row["text_extraction_class"] != "text_layer_good" for row in output_rows),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
