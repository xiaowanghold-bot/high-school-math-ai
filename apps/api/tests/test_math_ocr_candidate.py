from dataclasses import dataclass

from app.modules.pdf_imports.math_ocr import choose_question_candidate


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
