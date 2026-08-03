from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from pathlib import Path

import pdfplumber
from pypdf import PdfReader


QUESTION_RE = re.compile(r"(?m)^\s*(?:例|题)?\s*(\d{1,3})\s*[\.．、]\s*")
TYPE_RE = re.compile(r"(?:【\s*)?题型\s*[一二三四五六七八九十0-9]+")
SOLUTION_RE = re.compile(r"【?(?:答案|解析|详解|解答|证明)】?")
COPYRIGHT_RE = re.compile(r"(?:版权所有|版权|仅供|严禁|侵权|来源|公众号|网站|学科网|组卷网)")


def safe_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\x00", "").strip()


def audit_pdf(path: Path, text_dir: Path) -> dict[str, object]:
    reader = PdfReader(str(path), strict=False)
    encrypted = bool(reader.is_encrypted)
    if encrypted:
        try:
            reader.decrypt("")
        except Exception:
            pass

    metadata = reader.metadata or {}
    page_count = len(reader.pages)
    outline_count = 0
    try:
        outline_count = len(reader.outline or [])
    except Exception:
        outline_count = 0

    page_char_counts: list[int] = []
    image_counts: list[int] = []
    extracted_pages: list[str] = []
    page_sizes: set[str] = set()
    extraction_errors: list[str] = []

    with pdfplumber.open(str(path)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            except Exception as exc:
                text = ""
                extraction_errors.append(f"p{index}:{type(exc).__name__}")
            text = safe_text(text)
            extracted_pages.append(text)
            page_char_counts.append(len(text))
            image_counts.append(len(page.images or []))
            page_sizes.add(f"{round(page.width, 1)}x{round(page.height, 1)}")

    full_text = "\n\n".join(extracted_pages)
    text_path = text_dir / f"{path.stem}.txt"
    text_path.write_text(full_text, encoding="utf-8")

    text_pages = sum(count >= 20 for count in page_char_counts)
    low_text_pages = sum(count < 20 for count in page_char_counts)
    total_chars = sum(page_char_counts)
    median_chars = statistics.median(page_char_counts) if page_char_counts else 0
    image_pages = sum(count > 0 for count in image_counts)
    low_text_ratio = (low_text_pages / page_count) if page_count else 1.0
    if total_chars == 0 or low_text_ratio >= 0.75:
        extraction_class = "ocr_required"
    elif low_text_ratio >= 0.25:
        extraction_class = "mixed_or_partial_ocr"
    elif median_chars < 150:
        extraction_class = "sparse_text_layer"
    else:
        extraction_class = "text_layer_good"

    question_matches = QUESTION_RE.findall(full_text)
    type_matches = TYPE_RE.findall(full_text)
    solution_matches = SOLUTION_RE.findall(full_text)
    copyright_hits = COPYRIGHT_RE.findall(full_text)

    sample = re.sub(r"\s+", " ", full_text[:1800]).strip()

    return {
        "filename": path.name,
        "path": str(path),
        "bytes": path.stat().st_size,
        "pages": page_count,
        "encrypted": encrypted,
        "title_metadata": safe_text(metadata.get("/Title")),
        "author_metadata": safe_text(metadata.get("/Author")),
        "creator_metadata": safe_text(metadata.get("/Creator")),
        "producer_metadata": safe_text(metadata.get("/Producer")),
        "outline_items_top_level": outline_count,
        "page_sizes": "|".join(sorted(page_sizes)),
        "total_text_chars": total_chars,
        "median_text_chars_per_page": median_chars,
        "text_pages": text_pages,
        "low_text_pages": low_text_pages,
        "image_pages": image_pages,
        "total_embedded_images": sum(image_counts),
        "extraction_class": extraction_class,
        "question_number_markers": len(question_matches),
        "type_heading_markers": len(type_matches),
        "solution_markers": len(solution_matches),
        "copyright_or_source_markers": len(copyright_hits),
        "extraction_errors": "|".join(extraction_errors),
        "sample_text": sample,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    text_dir = args.output_dir / "text"
    text_dir.mkdir(parents=True, exist_ok=True)

    pdf_paths = sorted(args.source_dir.glob("*.pdf"), key=lambda p: p.name)
    rows: list[dict[str, object]] = []
    for path in pdf_paths:
        try:
            rows.append(audit_pdf(path, text_dir))
        except Exception as exc:
            rows.append(
                {
                    "filename": path.name,
                    "path": str(path),
                    "bytes": path.stat().st_size,
                    "pages": 0,
                    "extraction_class": "failed",
                    "extraction_errors": f"{type(exc).__name__}:{exc}",
                }
            )

    json_path = args.output_dir / "pdf-audit.json"
    csv_path = args.output_dir / "pdf-audit.csv"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "pdf_count": len(rows),
        "total_pages": sum(int(row.get("pages", 0) or 0) for row in rows),
        "total_bytes": sum(int(row.get("bytes", 0) or 0) for row in rows),
        "extraction_classes": {},
        "failed_files": [row["filename"] for row in rows if row.get("extraction_class") == "failed"],
    }
    for row in rows:
        cls = str(row.get("extraction_class", "unknown"))
        summary["extraction_classes"][cls] = summary["extraction_classes"].get(cls, 0) + 1
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

