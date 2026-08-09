from __future__ import annotations

import re


_COMMANDS = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "theta": "θ",
    "lambda": "λ",
    "mu": "μ",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "phi": "φ",
    "omega": "ω",
    "xi": "ξ",
    "Delta": "Δ",
    "Sigma": "Σ",
    "Omega": "Ω",
    "infty": "∞",
    "in": "∈",
    "notin": "∉",
    "subset": "⊂",
    "subseteq": "⊆",
    "supset": "⊃",
    "supseteq": "⊇",
    "cap": "∩",
    "cup": "∪",
    "complement": "∁",
    "setminus": "∖",
    "emptyset": "∅",
    "le": "≤",
    "leq": "≤",
    "ge": "≥",
    "geq": "≥",
    "ne": "≠",
    "neq": "≠",
    "approx": "≈",
    "equiv": "≡",
    "times": "×",
    "cdot": "·",
    "div": "÷",
    "pm": "±",
    "mp": "∓",
    "sum": "∑",
    "prod": "∏",
    "int": "∫",
    "mid": "|",
    "parallel": "∥",
    "perp": "⊥",
    "angle": "∠",
    "triangle": "△",
    "therefore": "∴",
    "because": "∵",
    "to": "→",
    "rightarrow": "→",
    "leftarrow": "←",
    "leftrightarrow": "↔",
    "log": "log",
    "ln": "ln",
    "sin": "sin",
    "cos": "cos",
    "tan": "tan",
    "cot": "cot",
    "max": "max",
    "min": "min",
}

_BLACKBOARD = {
    "R": "ℝ",
    "N": "ℕ",
    "Z": "ℤ",
    "Q": "ℚ",
    "C": "ℂ",
}

_SUPERSCRIPT = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
_SUBSCRIPT = str.maketrans(
    "0123456789+-=()aeiouhklmnprstvxU",
    "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑᵢₒᵤₕₖₗₘₙₚᵣₛₜᵥₓᵤ",
)


def teacher_readable_math(value: str | None) -> str:
    """Convert the LaTeX subset used by the question bank to editable text.

    Exports deliberately use readable Unicode/linear math instead of leaking
    source markup. This keeps both Word and PDF dependable without requiring a
    TeX installation, while Word users can still edit every expression.
    """

    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("$$", "").replace("$", "")
    text = re.sub(r"\\(?:left|right)\b", "", text)
    text = re.sub(r"\\[,;:]", " ", text)
    text = text.replace(r"\!", "").replace(r"\ ", " ").replace("~", " ")
    text = _convert_structures(text)
    text = _convert_scripts(text)
    text = re.sub(r"\\([A-Za-z]+)", lambda match: _COMMANDS.get(match.group(1), match.group(1)), text)
    text = text.replace(r"\{", "{").replace(r"\}", "}").replace(r"\_", "_")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def _convert_structures(text: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(text):
        if text.startswith(r"\frac", index):
            numerator, next_index = _read_argument(text, index + 5)
            denominator, next_index = _read_argument(text, next_index)
            if numerator is not None and denominator is not None:
                top = teacher_readable_math(numerator)
                bottom = teacher_readable_math(denominator)
                output.append(f"{_fraction_part(top)}/{_fraction_part(bottom)}")
                index = next_index
                continue
        if text.startswith(r"\sqrt", index):
            radicand, next_index = _read_argument(text, index + 5)
            if radicand is not None:
                output.append(f"√({_strip_outer_parentheses(teacher_readable_math(radicand))})")
                index = next_index
                continue
        matched_wrapper = False
        for command in ("text", "mathrm", "mathbf", "mathit", "operatorname", "overline", "vec"):
            marker = f"\\{command}"
            if not text.startswith(marker, index):
                continue
            content, next_index = _read_argument(text, index + len(marker))
            if content is None:
                continue
            converted = teacher_readable_math(content)
            if command == "overline":
                converted = f"¯({converted})"
            elif command == "vec":
                converted = f"→{converted}"
            output.append(converted)
            index = next_index
            matched_wrapper = True
            break
        if matched_wrapper:
            continue
        if text.startswith(r"\mathbb", index):
            content, next_index = _read_argument(text, index + 7)
            if content is not None:
                converted = teacher_readable_math(content)
                output.append(_BLACKBOARD.get(converted, converted))
                index = next_index
                continue
        output.append(text[index])
        index += 1
    return "".join(output)


def _convert_scripts(text: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(text):
        marker = text[index]
        if marker not in {"^", "_"}:
            output.append(marker)
            index += 1
            continue
        content, next_index = _read_argument(text, index + 1)
        if content is None:
            output.append(marker)
            index += 1
            continue
        converted = teacher_readable_math(content)
        table = _SUPERSCRIPT if marker == "^" else _SUBSCRIPT
        translated = converted.translate(table)
        allowed = (
            "0123456789+-=()n"
            if marker == "^"
            else "0123456789+-=()aeiouhklmnprstvxU"
        )
        convertible = all(character in allowed for character in converted)
        output.append(translated if convertible else f"{marker}({converted})")
        index = next_index
    return "".join(output)


def _read_argument(text: str, index: int) -> tuple[str | None, int]:
    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text):
        return None, index
    if text[index] != "{":
        return text[index], index + 1
    depth = 1
    cursor = index + 1
    while cursor < len(text) and depth:
        if text[cursor] == "{":
            depth += 1
        elif text[cursor] == "}":
            depth -= 1
        cursor += 1
    if depth:
        return None, index
    return text[index + 1 : cursor - 1], cursor


def _fraction_part(value: str) -> str:
    if re.search(r"(?<!^)[+\-=]", value) or " " in value:
        return f"({value})"
    return value


def _strip_outer_parentheses(value: str) -> str:
    if value.startswith("(") and value.endswith(")"):
        return value[1:-1]
    return value
