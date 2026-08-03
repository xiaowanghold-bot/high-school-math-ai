from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


PATTERNS = {
    "answer_markers": re.compile(r"【\s*答案\s*】"),
    "analysis_markers": re.compile(r"【\s*分析\s*】"),
    "solution_markers": re.compile(r"【\s*(?:解析|详解|解答)\s*】"),
    "example_markers": re.compile(r"(?:【\s*)?例(?:题)?\s*\d+(?:[-—]\d+)?(?:\s*】)?"),
    "numbered_question_markers": re.compile(r"(?m)^\s*\d{1,3}\s*[\.．、]\s*"),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audit_json", type=Path)
    parser.add_argument("text_dir", type=Path)
    parser.add_argument("output_csv", type=Path)
    args = parser.parse_args()

    audit_rows = json.loads(args.audit_json.read_text(encoding="utf-8"))
    rows = []
    for audit in audit_rows:
        text_path = args.text_dir / f"{Path(audit['filename']).stem}.txt"
        text = text_path.read_text(encoding="utf-8")
        counts = {key: len(pattern.findall(text)) for key, pattern in PATTERNS.items()}

        title = str(audit["filename"])
        is_student = "学生版" in title or "原卷" in title
        candidates = [
            counts["answer_markers"],
            counts["solution_markers"],
            counts["example_markers"],
            counts["numbered_question_markers"],
        ]
        if counts["answer_markers"] >= 5:
            estimate = counts["answer_markers"]
            basis = "answer_markers"
        elif is_student:
            estimate = max(counts["example_markers"], counts["numbered_question_markers"])
            basis = "student_numbering"
        else:
            estimate = max(candidates)
            basis = "max_structural_marker"

        rows.append(
            {
                "filename": audit["filename"],
                "pages": audit["pages"],
                **counts,
                "preliminary_question_estimate": estimate,
                "estimate_basis": basis,
                "needs_parser_validation": True,
            }
        )

    with args.output_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(
        json.dumps(
            {
                "files": len(rows),
                "preliminary_question_estimate_sum": sum(
                    int(row["preliminary_question_estimate"]) for row in rows
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
