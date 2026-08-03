from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)
    return text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audit_json", type=Path)
    parser.add_argument("text_dir", type=Path)
    parser.add_argument("output_json", type=Path)
    args = parser.parse_args()

    audit_rows = json.loads(args.audit_json.read_text(encoding="utf-8"))
    hashes: dict[str, list[dict[str, object]]] = defaultdict(list)
    split_mismatches: list[dict[str, object]] = []

    for row in audit_rows:
        text_path = args.text_dir / f"{Path(row['filename']).stem}.txt"
        pages = text_path.read_text(encoding="utf-8").split("\n\n")
        expected = int(row.get("pages", 0) or 0)
        if len(pages) != expected:
            split_mismatches.append(
                {"filename": row["filename"], "expected": expected, "segments": len(pages)}
            )
        for page_number, page_text in enumerate(pages, start=1):
            normalized = normalize(page_text)
            if len(normalized) < 180:
                continue
            digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            hashes[digest].append(
                {
                    "filename": row["filename"],
                    "page": page_number,
                    "normalized_chars": len(normalized),
                }
            )

    groups = []
    for digest, members in hashes.items():
        filenames = {str(member["filename"]) for member in members}
        if len(filenames) > 1:
            groups.append({"hash": digest, "members": members})
    groups.sort(key=lambda group: (-len(group["members"]), group["hash"]))

    file_pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    for group in groups:
        filenames = sorted({str(member["filename"]) for member in group["members"]})
        for i, left in enumerate(filenames):
            for right in filenames[i + 1 :]:
                file_pair_counts[(left, right)] += 1
    pairs = [
        {"left": left, "right": right, "duplicate_pages": count}
        for (left, right), count in sorted(
            file_pair_counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]

    output = {
        "split_mismatches": split_mismatches,
        "cross_file_duplicate_groups": len(groups),
        "cross_file_duplicate_page_instances": sum(len(group["members"]) for group in groups),
        "file_pairs": pairs,
        "groups": groups,
    }
    args.output_json.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in output.items() if key != "groups"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

