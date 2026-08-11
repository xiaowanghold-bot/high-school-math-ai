from __future__ import annotations

import re
from dataclasses import dataclass


_PRIVATE_USE_RE = re.compile(r"[\uf000-\uf8ff]")
_SOLUTION_MARKER_RE = re.compile(
    r"【\s*(?:思路分析|规范解答|答案|分析|解析|详解)\s*】|^\s*Answer\s*[:：]?",
    re.MULTILINE | re.IGNORECASE,
)
_SUBSCRIPT_DIGITS = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


@dataclass(frozen=True)
class StructuredTextRepair:
    stem_plain: str
    stem_latex: str | None
    options: list[dict[str, str]]
    formula_status: str
    warnings: list[str]
    auto_repaired: bool


def _question_only(source_text: str) -> tuple[str, bool]:
    match = _SOLUTION_MARKER_RE.search(source_text)
    if not match:
        return source_text.strip(), False
    return source_text[: match.start()].strip(), True


def _restore_function_calls(text: str) -> str:
    # MathType frequently emits both fence glyphs after their contents.  Handle
    # the most useful semantic forms before consuming the generic fence pair.
    text = re.sub(
        r"点\s*([^，。；：]{1,24}?),\s*([fghuv])([A-Za-z0-9+\-*/.]+)\uf0ee{4}\s*处",
        lambda m: f"点({m.group(1)},{m.group(2)}({m.group(3)}))处",
        text,
    )
    text = re.sub(
        r"([fghuv])\uf00a([A-Za-z0-9+\-*/.]+)\uf0ee{2}",
        lambda m: f"{m.group(1)}′({m.group(2)})",
        text,
    )
    text = re.sub(
        r"([fghuv])\uf00b([A-Za-z0-9+\-*/.]+)\uf0ee{2}",
        lambda m: f"{m.group(1)}″({m.group(2)})",
        text,
    )
    text = re.sub(
        r"(?<![A-Za-z])([fghuv])([A-Za-z0-9+\-*/.]+)\uf0ee{2}",
        lambda m: f"{m.group(1)}({m.group(2)})",
        text,
    )
    return text


def _restore_intervals(text: str) -> str:
    # PMExtra uses different private glyphs for round and square/bracket pieces.
    # Opening fences are often moved or dropped by PDF text extraction, so infer
    # them only in explicit interval/domain language.
    value = r"[A-Za-z0-9+\-*/.π∞]+(?:\s*,\s*[A-Za-z0-9+\-*/.π∞]+)"
    text = re.sub(
        rf"(区间|范围)\s*({value})\uf0f6{{2}}",
        lambda m: f"{m.group(1)}[{m.group(2)}]",
        text,
    )
    text = re.sub(
        rf"(区间|范围)\s*({value})(?:\uf0e8\uf0e9\uf0ea){{2}}",
        lambda m: f"{m.group(1)}[{m.group(2)}]",
        text,
    )
    text = re.sub(
        rf"(在|于|x∈|a∈|n∈)\s*({value})\uf0f6{{2}}",
        lambda m: f"{m.group(1)}({m.group(2)}]",
        text,
    )
    text = re.sub(
        rf"(在|于|x∈|a∈|n∈)\s*({value})(?:\uf0e8\uf0e9\uf0ea){{2}}",
        lambda m: f"{m.group(1)}[{m.group(2)}]",
        text,
    )
    text = re.sub(
        rf"(在|于|x∈|a∈|n∈)\s*({value})\uf0cb{{2}}",
        lambda m: f"{m.group(1)}[{m.group(2)}]",
        text,
    )
    text = re.sub(
        rf"(在|于|x∈|a∈|n∈)\s*({value})\uf0ee{{2}}",
        lambda m: f"{m.group(1)}({m.group(2)})",
        text,
    )
    return text


def _restore_flat_math(text: str) -> str:
    # High-confidence layout losses seen in MathType PDFs. These replacements
    # intentionally cover common high-school notation and stay review-gated.
    text = re.sub(r"x22", "x²/2", text)
    text = re.sub(r"(?<!\d)52(?=\s*\()", "5/2", text)
    text = re.sub(r"(?<!\d)32(?=\s*x)", "3/2", text)
    text = re.sub(r"(?<![A-Za-z0-9])1e(?=\s*,)", "1/e", text)
    text = re.sub(r"π2\b", "π/2", text)
    # Text layers flatten stacked fractions and superscripts into a run of
    # baseline digits. These two forms are high-confidence because the same
    # page still provides the surrounding function definitions.
    text = re.sub(r"\bex-ax312\b", "eˣ-ax³/12", text)
    text = re.sub(r"\bx33\b", "x³/3", text)
    text = re.sub(r"\b(sin|cos|tan)([234])(?=[A-Za-z])", lambda m: f"{m.group(1)}{'²³⁴'[int(m.group(2)) - 2]}", text)
    superscripts = {"2": "²", "3": "³", "4": "⁴"}
    text = re.sub(
        r"(?<!\d)([xyabn])([234])\b",
        lambda m: f"{m.group(1)}{superscripts[m.group(2)]}",
        text,
    )
    text = re.sub(r"(?<![A-Za-z0-9])1([xyaen])\b", lambda m: f"1/{m.group(1)}", text)
    return text


def _restore_geometry_notation(text: str) -> str:
    # Some embedded equation fonts expose the parallel glyph as the Unicode
    # bottom-bracket character U+23B3. Context is essential: before "平面" the
    # original notation is a parallel relation, not a perpendicular relation.
    text = re.sub(r"(?<=[A-Za-z0-9])\s*[⎳]\s*(?=平面)", "∥", text)
    if re.search(r"如图|棱柱|棱锥|平面|直线|中点", text):
        text = re.sub(
            r"(?<=[A-Z])([0-9])",
            lambda match: match.group(1).translate(_SUBSCRIPT_DIGITS),
            text,
        )
    return text


def _consume_remaining_private_glyphs(text: str) -> tuple[str, bool]:
    had_private = bool(_PRIVATE_USE_RE.search(text))
    # A doubled F0CB usually represents a late-emitted pair of fences around the
    # immediately preceding factor (for example (1/x+a) before ln(1+x)).
    text = re.sub(
        r"((?:1/[A-Za-z]|[A-Za-z0-9.]+)(?:\s*[+\-]\s*[A-Za-z0-9./]+)*)\uf0cb{2}(?=\s*ln)",
        lambda m: f"({m.group(1)})",
        text,
    )
    text = re.sub(
        r"\b(ln|sin|cos|tan)([A-Za-z0-9./+\-]+)\uf0cb{2}",
        lambda m: f"{m.group(1)}({m.group(2)})",
        text,
    )
    text = text.replace("\uf0ee\uf0ee", "()")
    text = text.replace("\uf0cb\uf0cb", "()")
    text = text.replace("\uf0f6\uf0f6", "]")
    text = text.replace("\uf0e8\uf0e9\uf0ea", "")
    text = text.replace("\uf0e0\uf0e1\uf0e2", "{")
    text = text.replace("\uf00a", "′").replace("\uf00b", "″")
    # Unknown private glyphs must never reach teachers or exports. Keep the draft
    # review-gated and expose a readable marker instead of a tofu box.
    text = _PRIVATE_USE_RE.sub("〔公式符号待核〕", text)
    return text, had_private


def _clean_spacing(text: str) -> str:
    text = text.replace("．", ".")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"\[\s+", "[", text)
    text = re.sub(r"\s+\]", "]", text)
    return text.strip()


def needs_math_ocr(text: str) -> bool:
    """Return whether a structured draft contains notation worth rendering."""
    return bool(
        "〔公式符号待核〕" in text
        or "()" in text
        or re.search(r"[⎳�□■\uf000-\uf8ff]", text)
        or re.search(r"[²³⁴₀-₉∀-⋿]", text)
        or re.search(r"[A-Za-z]\s*[=<>+−*/^]", text)
        or re.search(r"[=<>+−*/^]\s*[A-Za-z0-9]", text)
        or re.search(r"[A-Za-z]\s*[\[(]", text)
        or re.search(r"(?:[A-Z]\s*){2,}", text)
        or re.search(r"[A-Za-z]\d", text)
        or re.search(r"(?:ln|sin|cos|tan)[A-Za-z0-9]{3,}", text)
        or re.search(r"[。；.]\s*\d{1,3}\s*\(", text)
    )


def _extract_options(question_text: str) -> tuple[str, list[dict[str, str]]]:
    pattern = re.compile(
        r"(?ms)(?:^|\s)([A-H])\s*[.．、]\s*(.*?)(?=(?:\s+[A-H]\s*[.．、]\s)|\Z)"
    )
    matches = list(pattern.finditer(question_text))
    options = [
        {"key": match.group(1), "text": re.sub(r"\s+", " ", match.group(2)).strip()}
        for match in matches
    ]
    stem = question_text[: matches[0].start()].strip() if matches else question_text
    return stem, options


def repair_structured_text(source_text: str, question_type: str) -> StructuredTextRepair:
    question_text, separated_solution = _question_only(source_text)
    original = question_text
    question_text = _restore_function_calls(question_text)
    question_text = _restore_intervals(question_text)
    question_text = _restore_flat_math(question_text)
    question_text = _restore_geometry_notation(question_text)
    question_text, had_private = _consume_remaining_private_glyphs(question_text)
    question_text = _clean_spacing(question_text)
    stem_plain, options = _extract_options(question_text)
    stem_plain = re.sub(r"^\s*(?:例|题)?\s*\d{1,3}\s*[.．、]\s*", "", stem_plain).strip()

    warnings: list[str] = []
    if separated_solution:
        warnings.append("已自动分离原答案或解析段；题干不会再混入后续解析。")
    if had_private:
        warnings.append("已自动修复 PDF MathType 私有字符；请抽查分式、括号和上下标。")
    if question_type in {"single_choice", "multiple_choice"} and len(options) < 2:
        warnings.append("未稳定拆出选择题选项，请对照原页补充。")
    if "〔公式符号待核〕" in question_text:
        warnings.append("仍有无法可靠推断的公式符号，已用可读标记定位，请对照原页复核。")

    math_signal = needs_math_ocr(stem_plain)
    auto_repaired = question_text != _clean_spacing(original) or separated_solution
    return StructuredTextRepair(
        stem_plain=stem_plain or question_text,
        stem_latex=None,
        options=options,
        formula_status="needs_review" if math_signal or had_private else "pending",
        warnings=warnings,
        auto_repaired=auto_repaired,
    )
