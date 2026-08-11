from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from threading import Lock
from typing import Any, Iterable


@dataclass(frozen=True)
class OcrQuestionCandidate:
    text: str
    page_number: int
    score: float


_engine: Any | None = None
_engine_lock = Lock()


def _get_engine() -> Any:
    global _engine
    with _engine_lock:
        if _engine is None:
            try:
                from pix2text import Pix2Text
            except ImportError as exc:  # pragma: no cover - environment-dependent
                raise RuntimeError(
                    "数学 OCR 尚未安装，请安装 API 的 math-ocr 可选依赖"
                ) from exc
            _engine = Pix2Text.from_config(enable_table=False, device="cpu")
    return _engine


def _box(element: Any) -> tuple[float, float, float, float]:
    value = element.box
    return tuple(float(item) for item in value)


def _area(box: tuple[float, float, float, float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _contained_ratio(
    inner: tuple[float, float, float, float], outer: tuple[float, float, float, float]
) -> float:
    width = max(0.0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    height = max(0.0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    return width * height / max(1.0, _area(inner))


def _deduplicate_elements(elements: Iterable[Any]) -> list[Any]:
    textual = [item for item in elements if str(getattr(item, "text", "")).strip()]
    kept: list[Any] = []
    for item in sorted(textual, key=lambda value: _area(_box(value)), reverse=True):
        item_box = _box(item)
        if any(
            _contained_ratio(item_box, _box(existing)) >= 0.88
            and len(str(existing.text)) >= len(str(item.text))
            for existing in kept
        ):
            continue
        kept.append(item)
    return sorted(kept, key=lambda value: (_box(value)[1], _box(value)[0]))


def _is_question_start(text: str) -> bool:
    return bool(
        re.search(r"(?:题目|例题)\s*\d{1,3}", text)
        or re.match(r"^\s*\d{1,3}\s*[（(]\s*20\d{2}", text)
    )


def _is_solution_start(text: str) -> bool:
    return bool(
        re.search(r"【[^】]{0,8}(?:答案|分析|解析|思路|解答)", text)
        or re.match(r"^\s*(?:答案|解析|分析|详解)\s*[:：]", text)
    )


def _candidate_segments(elements: Iterable[Any]) -> list[str]:
    segments: list[list[str]] = []
    current: list[str] | None = None
    for element in _deduplicate_elements(elements):
        text = str(element.text).strip()
        if _is_solution_start(text):
            if current:
                segments.append(current)
            current = None
            continue
        if _is_question_start(text):
            if current:
                segments.append(current)
            current = [text]
        elif current is not None:
            current.append(text)
    if current:
        segments.append(current)
    return ["\n".join(segment) for segment in segments if segment]


def _signature(text: str) -> str:
    text = re.sub(r"【[^】]+】.*", "", text, flags=re.DOTALL)
    return "".join(re.findall(r"[\u4e00-\u9fff0-9]+", text))[:600]


def _clean_candidate(text: str, source_text: str = "") -> str:
    text = re.sub(r"^\s*(?:题目|例题)\s*\d{1,3}\s*", "", text)
    text = text.replace(r"\mathrm{l n}", r"\ln").replace(r"\mathrm{ln}", r"\ln")
    text = text.replace(r"\!", "")
    text = re.sub(r"\$\s+", "$", text)
    text = re.sub(r"\s+\$", "$", text)
    text = re.sub(r"\${2,}", "$", text)
    if "≤" in source_text:
        text = text.replace(r"\ll", r"\leqslant")
    if "≥" in source_text:
        text = text.replace(r"\gg", r"\geqslant")
    subquestion_twos = list(re.finditer(r"[（(]\s*2\s*[)）]", text))
    if len(subquestion_twos) > 1:
        text = text[: subquestion_twos[1].start()]
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def choose_question_candidate(
    source_text: str, pages: Iterable[tuple[int, Iterable[Any]]]
) -> OcrQuestionCandidate | None:
    source_signature = _signature(source_text)
    candidates: list[OcrQuestionCandidate] = []
    for page_number, elements in pages:
        for segment in _candidate_segments(elements):
            candidate_signature = _signature(segment)
            if not candidate_signature:
                continue
            score = SequenceMatcher(None, source_signature, candidate_signature).ratio()
            candidates.append(
                OcrQuestionCandidate(
                    text=_clean_candidate(segment, source_text), page_number=page_number, score=score
                )
            )
    if not candidates:
        return None
    best = max(candidates, key=lambda item: item.score)
    return best if best.score >= 0.24 else None


def _question_clip(page: Any, source_text: str) -> Any:
    import pymupdf

    blocks = sorted(page.get_text("blocks"), key=lambda item: (item[1], item[0]))
    source_signature = _signature(source_text)
    starts = []
    for block in blocks:
        text = str(block[4]).replace("\n", " ")
        if re.search(r"20\d{2}|已知|设函数|证明", text):
            score = SequenceMatcher(None, source_signature, _signature(text)).ratio()
            starts.append((score, block))
    if not starts:
        return page.rect
    _, start = max(starts, key=lambda item: item[0])
    start_y = max(float(page.rect.y0), float(start[1]) - 8)
    end_y = float(page.rect.y1)
    for block in blocks:
        if float(block[1]) <= float(start[1]) + 4:
            continue
        text = str(block[4]).replace("\n", " ")
        if _is_solution_start(text) or _is_question_start(text):
            end_y = min(end_y, float(block[1]) - 4)
            break
    if end_y - start_y < 35:
        end_y = min(float(page.rect.y1), start_y + 180)
    return pymupdf.Rect(page.rect.x0, start_y, page.rect.x1, end_y)


def recognize_question_candidates(
    pdf_path: Path,
    requests: Iterable[tuple[str, str, int, int]],
) -> dict[str, OcrQuestionCandidate]:
    request_list = list(requests)
    import io

    import pymupdf
    from PIL import Image

    engine = _get_engine()
    output: dict[str, OcrQuestionCandidate] = {}
    document = pymupdf.open(pdf_path)
    for draft_id, source_text, start_page, _ in request_list:
        page = document.load_page(start_page - 1)
        clip = _question_clip(page, source_text)
        pixmap = page.get_pixmap(dpi=260, clip=clip, alpha=False)
        image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
        recognized = engine.recognize_page(
            image,
            page_number=start_page - 1,
            page_id=f"question-{draft_id}",
            table_as_image=True,
        )
        candidate = choose_question_candidate(
            source_text, [(start_page, recognized.elements)]
        )
        if candidate is None:
            # A tight crop can omit a printed "题目 N" label. Treat the whole
            # crop as one candidate while still refusing very weak matches.
            elements = _deduplicate_elements(recognized.elements)
            fallback = "\n".join(str(item.text).strip() for item in elements)
            score = SequenceMatcher(None, _signature(source_text), _signature(fallback)).ratio()
            if fallback and score >= 0.24:
                candidate = OcrQuestionCandidate(
                    text=_clean_candidate(fallback, source_text),
                    page_number=start_page,
                    score=score,
                )
        if candidate is not None:
            output[draft_id] = candidate
    return output
