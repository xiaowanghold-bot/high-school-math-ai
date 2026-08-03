from __future__ import annotations

import argparse
import bisect
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pdfplumber


PUA_MAP = str.maketrans(
    {
        "\uf03d": "=",
        "\uf02d": "−",
        "\uf02b": "+",
        "\uf03c": "<",
        "\uf03e": ">",
        "\uf0a3": "≤",
        "\uf0b3": "≥",
        "\uf0b1": "±",
        "\uf0b9": "≠",
        "\uf0ce": "∈",
        "\uf0c7": "∩",
        "\uf0c8": "∪",
        "\uf0cd": "⊆",
        "\uf0c6": "∅",
        "\uf0a5": "∞",
        "\uf07b": "{",
        "\uf07d": "}",
        "\uf028": "(",
        "\uf029": ")",
        "\uf05b": "[",
        "\uf05d": "]",
    }
)

ANALYSIS_MARKERS = ("【解析】", "【分析】", "【详解】")


@dataclass
class DocumentText:
    path: Path
    pages: list[str]
    full_text: str
    page_starts: list[int]

    def page_for_offset(self, offset: int) -> int:
        return bisect.bisect_right(self.page_starts, offset)


def extract_document(path: Path) -> DocumentText:
    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            try:
                pages.append(page.extract_text(x_tolerance=2, y_tolerance=3) or "")
            except Exception:
                pages.append("")

    starts: list[int] = []
    chunks: list[str] = []
    offset = 0
    for page in pages:
        starts.append(offset)
        chunks.append(page)
        offset += len(page) + 2
    return DocumentText(path, pages, "\n\n".join(chunks), starts)


def normalize_text(text: str) -> str:
    text = text.translate(PUA_MAP)
    text = text.replace("ð", "∁").replace("¥", "∞").replace("æ", "").replace("ç", "").replace("ö", "").replace("÷", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def has_unmapped_pua(text: str) -> bool:
    return any(0xE000 <= ord(ch) <= 0xF8FF for ch in text.translate(PUA_MAP))


def split_options(stem_with_options: str) -> tuple[str, list[dict[str, str]]]:
    matches = list(re.finditer(r"(?<![A-Za-z])([A-D])．", stem_with_options))
    if len(matches) < 2:
        return normalize_text(stem_with_options), []

    stem = stem_with_options[: matches[0].start()]
    options: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(stem_with_options)
        value = normalize_text(stem_with_options[match.end() : end])
        options.append({"key": match.group(1), "plain_text": value})
    return normalize_text(stem), options


def trim_before_any(text: str, markers: tuple[str, ...]) -> str:
    positions = [text.find(marker) for marker in markers if text.find(marker) >= 0]
    return text[: min(positions)] if positions else text


def source_reference(stem: str) -> str | None:
    match = re.search(r"[（(]([^）)]{4,80})[）)]", stem)
    return normalize_text(match.group(1)) if match else None


def topic_before(text: str, offset: int, patterns: tuple[str, ...]) -> str | None:
    prefix = text[:offset]
    candidates: list[tuple[int, str]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, prefix, re.MULTILINE):
            candidates.append((match.start(), normalize_text(match.group(0))))
    return max(candidates, default=(0, None), key=lambda item: item[0])[1]


def base_record(
    *,
    qid: str,
    stem: str,
    options: list[dict[str, str]],
    answer: dict[str, Any],
    question_type: str,
    doc: DocumentText,
    start: int,
    end: int,
    source_number: str,
    source_ref: str | None,
    topic: str | None,
    curriculum: dict[str, Any],
    knowledge_points: list[str],
    difficulty: int,
    created_at: str,
) -> dict[str, Any]:
    formula_warning = has_unmapped_pua(doc.full_text[start:end]) or bool(re.search(r"\n\d+(?:\s+\d+){1,}\n", stem))
    return {
        "id": qid,
        "status": "imported",
        "visibility": "private",
        "language": "zh-CN",
        "stem": {"plain_text": stem, "latex": None, "assets": []},
        "question_type": question_type,
        "options": options,
        "answer": answer,
        "solutions": [
            {
                "method": None,
                "steps_latex": [],
                "final_answer": None,
                "author_type": "not_imported",
                "review_status": "to_be_regenerated_and_verified",
            }
        ],
        "curriculum": {
            **curriculum,
            "knowledge_point_ids": knowledge_points,
            "prerequisite_ids": [],
            "mapping_status": "pilot_candidate",
        },
        "exam": {
            "paper_family": "新高考全国I卷适配候选",
            "region": None,
            "year": None,
            "original_score": None,
            "competency_tags": [],
        },
        "pedagogy": {
            "difficulty": difficulty,
            "difficulty_confidence": 0.45,
            "estimated_minutes": None,
            "methods": [],
            "common_errors": [],
            "usage_scenarios": ["题库检索候选"],
        },
        "verification": {
            "status": "needs_formula_review" if formula_warning else "needs_math_review",
            "methods": ["source_boundary_check"],
            "details": [
                "未导入原解析；解析须独立生成并验算",
                *( ["PDF文本层含未映射公式字符或分式错行，须对照原页校正"] if formula_warning else [] ),
            ],
        },
        "source": {
            "source_id": "SRC-007",
            "document_name": doc.path.name,
            "document_path": str(doc.path),
            "source_question_number": source_number,
            "source_reference": source_ref,
            "source_page_start": doc.page_for_offset(start),
            "source_page_end": doc.page_for_offset(max(start, end - 1)),
            "license_status": "question_content_user_declared_usable",
            "allowed_uses": ["extract_question_facts", "display_question", "adapt_question", "model_training_question_only"],
            "excluded_material": ["PDF整体", "版式", "封面", "水印", "讲义文字", "原解析表述"],
            "attribution_required": "to_be_confirmed_per_original_question_source",
            "proof_document_id": "user-declaration-2026-08-03",
        },
        "provenance": {
            "created_by": "import_pipeline",
            "derived_from_question_ids": [],
            "model_run_id": None,
            "duplicate_cluster_id": None,
            "extraction_method": "pypdf_text_boundary_v0.1",
            "topic_heading": topic,
        },
        "reviews": [],
        "created_at": created_at,
        "updated_at": created_at,
    }


def parse_answer(segment: str) -> str | None:
    match = re.search(r"【答案】\s*([^\n【]+)", segment)
    return normalize_text(match.group(1)) if match else None


def parse_marked_examples(doc: DocumentText, limit: int, created_at: str) -> list[dict[str, Any]]:
    matches = list(re.finditer(r"【例\s*(\d+-\d+)】", doc.full_text))
    records: list[dict[str, Any]] = []
    for index, match in enumerate(matches[:limit]):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(doc.full_text)
        segment = doc.full_text[match.end() : end]
        answer_pos = segment.find("【答案】")
        if answer_pos < 0:
            continue
        stem_raw = segment[:answer_pos]
        stem, options = split_options(stem_raw)
        answer_value = parse_answer(segment)
        topic = topic_before(doc.full_text, match.start(), (r"^考法[^\n]+",))
        records.append(
            base_record(
                qid=f"q_pilot_set_{match.group(1).replace('-', '_')}",
                stem=stem,
                options=options,
                answer={"type": "option", "value": answer_value, "status": "source_answer_extracted", "alternatives": []},
                question_type="single_choice",
                doc=doc,
                start=match.start(),
                end=end,
                source_number=match.group(1),
                source_ref=source_reference(stem),
                topic=topic,
                curriculum={
                    "curriculum_version": "CN-HS-MATH-2017-2020",
                    "textbook": "PEP-A",
                    "volume": "必修第一册",
                    "chapter": "第一章 集合与常用逻辑用语",
                    "section": None,
                },
                knowledge_points=["kp_sets_and_logic"],
                difficulty=2,
                created_at=created_at,
            )
        )
    return records


def numbered_matches(text: str, dotted: bool) -> list[re.Match[str]]:
    if dotted:
        return list(re.finditer(r"(?m)^[ \t]*(\d{1,2})．(?=[ \t]*[（(\u4e00-\u9fff])", text))
    return list(re.finditer(r"(?m)^[ \t]*(\d{1,2})[ \t]+(?=(?:[\u4e00-\u9fff]|20\d{2}))", text))


def first_sequential_matches(matches: list[re.Match[str]], limit: int) -> list[re.Match[str]]:
    selected: list[re.Match[str]] = []
    expected = 1
    for match in matches:
        if int(match.group(1)) != expected:
            continue
        selected.append(match)
        expected += 1
        if len(selected) == limit:
            break
    return selected


def parse_ellipse(doc: DocumentText, limit: int, created_at: str) -> list[dict[str, Any]]:
    boundaries = first_sequential_matches(numbered_matches(doc.full_text, dotted=True), limit + 1)
    matches = boundaries[:limit]
    records: list[dict[str, Any]] = []
    for index, match in enumerate(matches[:limit]):
        end = boundaries[index + 1].start() if index + 1 < len(boundaries) else len(doc.full_text)
        segment = doc.full_text[match.end() : end]
        answer_pos = segment.find("【答案】")
        if answer_pos < 0:
            continue
        stem, options = split_options(segment[:answer_pos])
        answer_value = parse_answer(segment)
        topic = topic_before(doc.full_text, match.start(), (r"^[一二三四五六七八九十]+．[^\n]+",))
        record = base_record(
            qid=f"q_pilot_ellipse_{int(match.group(1)):02d}",
            stem=stem,
            options=options,
            answer={"type": "option", "value": answer_value, "status": "source_answer_extracted", "alternatives": []},
            question_type="single_choice",
            doc=doc,
            start=match.start(),
            end=end,
            source_number=match.group(1),
            source_ref=source_reference(stem),
            topic=topic,
            curriculum={
                "curriculum_version": "CN-HS-MATH-2017-2020",
                "textbook": "PEP-A",
                "volume": "选择性必修第一册",
                "chapter": "第三章 圆锥曲线的方程",
                "section": "3.1 椭圆",
            },
            knowledge_points=["kp_ellipse"],
            difficulty=3,
            created_at=created_at,
        )
        if match.group(1) == "5":
            record["verification"]["status"] = "source_inconsistency_detected"
            record["verification"]["details"].append("原资料第5题答案栏为B，但详解末尾写“故选C”；详解计算结果2/9与B项一致")
        records.append(record)
    return records


def parse_probability(doc: DocumentText, limit: int, created_at: str) -> list[dict[str, Any]]:
    # The first sequential run 1..10 is the opening competition section.
    boundaries = first_sequential_matches(numbered_matches(doc.full_text, dotted=False), limit + 1)
    matches = boundaries[:limit]
    records: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = boundaries[index + 1].start() if index + 1 < len(boundaries) else len(doc.full_text)
        segment = doc.full_text[match.end() : end]
        stem_raw = trim_before_any(segment, ("\n解：", "\n解:", "\n【答案】", "\n【解析】", "\n【详解】"))
        stem = normalize_text(stem_raw)
        topic = topic_before(doc.full_text, match.start(), (r"^[一二三四五六七八九十]+．[^\n]+",))
        records.append(
            base_record(
                qid=f"q_pilot_probability_{int(match.group(1)):02d}",
                stem=stem,
                options=[],
                answer={
                    "type": "composite",
                    "value": None,
                    "status": "requires_independent_verification",
                    "alternatives": [],
                },
                question_type="composite",
                doc=doc,
                start=match.start(),
                end=end,
                source_number=match.group(1),
                source_ref=source_reference(stem),
                topic=topic,
                curriculum={
                    "curriculum_version": "CN-HS-MATH-2017-2020",
                    "textbook": "PEP-A",
                    "volume": "选择性必修第三册",
                    "chapter": "第七章 随机变量及其分布",
                    "section": None,
                },
                knowledge_points=["kp_probability", "kp_random_variable_distribution"],
                difficulty=4,
                created_at=created_at,
            )
        )
    return records


def find_source_files(source_root: Path) -> tuple[Path, Path, Path]:
    files = list(source_root.glob("*.pdf"))
    collection = next(path for path in files if path.name.startswith("专题01 "))
    probability = next(path for path in files if path.name.startswith("新高考数学概率"))
    ellipse = next(path for path in files if path.name.startswith("椭圆性质"))
    return collection, probability, ellipse


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the first 30-question private pilot batch.")
    parser.add_argument("--source-root", type=Path, default=Path("D:/高中数学/2026-08"))
    parser.add_argument("--output", type=Path, default=Path("data/pilot/batch-2026-08-001-30q.json"))
    args = parser.parse_args()

    collection_path, probability_path, ellipse_path = find_source_files(args.source_root)
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    collection_doc = extract_document(collection_path)
    probability_doc = extract_document(probability_path)
    ellipse_doc = extract_document(ellipse_path)
    questions = [
        *parse_marked_examples(collection_doc, 10, created_at),
        *parse_probability(probability_doc, 10, created_at),
        *parse_ellipse(ellipse_doc, 10, created_at),
    ]

    payload = {
        "batch_id": "batch-2026-08-001-pilot-30q",
        "schema_version": "0.1-pilot",
        "created_at": created_at,
        "publication_status": "private_not_publishable",
        "rights_boundary": {
            "basis": "用户声明题目内容可使用，但PDF整体不可商用",
            "included": ["题干事实", "选项", "客观答案", "必要图形的后续重绘"],
            "excluded": ["PDF整体", "原版式", "封面", "水印", "讲义文字", "原解析表述"],
        },
        "quality_gate": "公式校正、答案独立验算、题源归因和教师审核全部完成后方可发布",
        "question_count": len(questions),
        "questions": questions,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "question_count": len(questions)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
