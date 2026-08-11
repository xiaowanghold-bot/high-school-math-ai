from dataclasses import dataclass

from app.modules.pdf_imports.math_ocr import choose_question_candidate, compose_readable_candidate


@dataclass
class Element:
    text: str
    box: tuple[int, int, int, int]


def test_choose_question_candidate_prefers_matching_question_and_deduplicates_overlap() -> None:
    elements = [
        Element("大题典例", (100, 100, 300, 150)),
        Element(
            "题目1(2024河南郑州)已知函数 $f(x)=\\frac{x^{2}}{2}+ax-(ax+1)\\ln x$",
            (100, 200, 900, 300),
        ),
        Element("(1)求 $a,b$ 的值；(2)证明 $f(x)$ 在 $(1,+\\infty)$ 上递增。", (100, 310, 900, 400)),
        Element("(1)求 $a,b$ 的值", (100, 310, 400, 350)),
        Element("【思路分析】", (100, 410, 300, 450)),
        Element("这里是解析，不得进入题干", (100, 460, 900, 520)),
    ]

    candidate = choose_question_candidate(
        "1(2024·河南郑州)已知函数fx=x22+ax，求a,b并证明单调性。",
        [(1, elements)],
    )

    assert candidate is not None
    assert "$f(x)=\\frac{x^{2}}{2}" in candidate.text
    assert candidate.text.count("求$a,b$的值") == 1
    assert "不得进入题干" not in candidate.text


def test_choose_question_candidate_normalizes_parallel_and_numeric_formula_spacing() -> None:
    elements = [
        Element(
            "题目1 正三棱柱 $A B C-A_{\\mathrm{1}} B_{\\mathrm{1}} C_{\\mathrm{1}}$，"
            "证明 $M N / /$ 平面 $A_{1} C P$",
            (100, 200, 900, 300),
        )
    ]

    candidate = choose_question_candidate(
        "正三棱柱ABC-A1B1C1，证明MN⎳平面A1CP。",
        [(1, elements)],
    )

    assert candidate is not None
    assert r"$MN \parallel$" in candidate.text
    assert r"$ABC-A_1B_1C_1$" in candidate.text


def test_compose_readable_candidate_keeps_source_chinese_and_restores_function_math() -> None:
    plain = (
        "3(2022·河南·高三专题练习)已知函数f(x)=eˣ-ax³/12，其中常数a∈R."
        "(1)若f(x)在(0,+∞)上是增函数；(2)若a=4，"
        "设g(x)=f(x)+x³/3-x²-x+1，求证：函数g(x)在(-1,+∞)上有两个极值点."
    )
    noisy_ocr = "已知两数$f(x)=e^x-\\frac{ax^3}{12}$，其中将数a"

    composed = compose_readable_candidate(plain, noisy_ocr)

    assert "已知函数" in composed
    assert "已知两数" not in composed
    assert r"$f(x)=e^x-\frac{ax^3}{12}$" in composed
    assert r"$g(x)=f(x)+\frac{x^3}{3}-x^2-x+1$" in composed


def test_compose_readable_candidate_keeps_geometry_text_and_notation() -> None:
    plain = "已知正三棱柱ABC-A₁B₁C₁，证明：MN∥平面A₁CP。"
    noisy_ocr = "已知正二枝柱$ABC-A_1B_1C_1$，证明$MN \\parallel$平面$A_1CP$"

    composed = compose_readable_candidate(plain, noisy_ocr)

    assert "正三棱柱" in composed
    assert "正二枝柱" not in composed
    assert r"$ABC-A_1B_1C_1$" in composed
    assert r"$MN\parallel$平面$A_1CP$" in composed
