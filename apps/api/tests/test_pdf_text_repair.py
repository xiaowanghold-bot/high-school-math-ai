from app.modules.pdf_imports.text_repair import needs_math_ocr, repair_structured_text


def test_repair_structured_text_restores_mathtype_glyphs_and_separates_solution() -> None:
    source = (
        "1(2024·河南郑州·高三校联考阶段练习)已知函数f(x) =x22+ax-(ax+1)lnx"
        "在x=1处的切线方程为y=bx+52(a,b∈R)."
        "(1)求a，b的值；(2)证明：fx\uf0ee\uf0ee在1,+∞\uf0ee\uf0ee上单调递增."
        "【思路分析】(1)求出函数的导函数，依题意可得f\uf00a1\uf0ee\uf0ee=b。"
    )

    repaired = repair_structured_text(source, "open_response")

    assert "【思路分析】" not in repaired.stem_plain
    assert "f(x)" in repaired.stem_plain
    assert "f′(1)" not in repaired.stem_plain  # solution text must not leak into the stem
    assert "(1,+∞)" in repaired.stem_plain
    assert "x²/2" in repaired.stem_plain
    assert "5/2" in repaired.stem_plain
    assert not any(0xF000 <= ord(char) <= 0xF8FF for char in repaired.stem_plain)
    assert repaired.formula_status == "needs_review"
    assert repaired.auto_repaired


def test_repair_structured_text_restores_common_intervals_and_derivative() -> None:
    source = (
        "已知函数fx\uf0ee\uf0ee=x4+ax3."
        "(1)若函数在点1,f1\uf0ee\uf0ee\uf0ee\uf0ee处的切线过原点；"
        "(2)求函数fx\uf0ee\uf0ee在区间-1,4\uf0f6\uf0f6上的最大值；"
        "设f\uf00ax\uf0ee\uf0ee>0."
    )

    repaired = repair_structured_text(source, "open_response")

    assert "f(x)=x⁴+ax³" in repaired.stem_plain
    assert "(1,f(1))" in repaired.stem_plain
    assert "[-1,4]" in repaired.stem_plain
    assert "f′(x)>0" in repaired.stem_plain
    assert not any(0xF000 <= ord(char) <= 0xF8FF for char in repaired.stem_plain)


def test_repair_structured_text_never_leaves_private_use_glyphs() -> None:
    source = "函数fx\uf0ee\uf0ee在区间1e,e\uf0e8\uf0e9\uf0ea\uf0e8\uf0e9\uf0ea上，且1x+a\uf0cb\uf0cbln(1+x)>0"

    repaired = repair_structured_text(source, "open_response")

    assert "f(x)" in repaired.stem_plain
    assert "[1/e,e]" in repaired.stem_plain
    assert "(1/x+a)ln(1+x)" in repaired.stem_plain
    assert not any(0xF000 <= ord(char) <= 0xF8FF for char in repaired.stem_plain)


def test_math_ocr_is_requested_for_structured_math_content() -> None:
    assert needs_math_ocr("已知函数f(x)=x²/2，求其导数。")
    assert needs_math_ocr("已知函数f(x)=1/x+a()lnx。")
    assert needs_math_ocr("当a∈(0,1)时，〔公式符号待核〕。")


def test_math_ocr_detects_flattened_fraction_power_and_geometry_notation() -> None:
    assert needs_math_ocr(
        "已知函数f(x)=ex-ax312，设g(x)=f(x)+x33-x²-x+1。"
    )
    assert needs_math_ocr(
        "正三棱柱ABC-A1B1C1中，证明MN⎳平面A1CP。"
    )


def test_repair_structured_text_restores_parallel_symbol_and_vertex_subscripts() -> None:
    repaired = repair_structured_text(
        "正三棱柱ABC-A1B1C1中，证明MN⎳平面A1CP。",
        "open_response",
    )

    assert "ABC-A₁B₁C₁" in repaired.stem_plain
    assert "MN∥平面A₁CP" in repaired.stem_plain


def test_repair_structured_text_restores_flattened_exponential_fractions() -> None:
    repaired = repair_structured_text(
        "已知函数f(x)=ex-ax312，设g(x)=f(x)+x33-x²-x+1。",
        "open_response",
    )

    assert "f(x)=eˣ-ax³/12" in repaired.stem_plain
    assert "g(x)=f(x)+x³/3-x²-x+1" in repaired.stem_plain
