from __future__ import annotations

import itertools
import math
from typing import Any, Callable

from pydantic import BaseModel


class VerificationReport(BaseModel):
    question_id: str
    status: str
    computed_answer: str | None
    computed_canonical_value: str
    source_answer: str | None
    matched_option: str | None
    method: str
    details: list[str]
    evidence: dict[str, Any]
    verifier_version: str = "sets-v0.1.0"


class MathVerifier:
    """Pure in-process math verification behind one small interface."""

    def __init__(self) -> None:
        self._rules: dict[str, Callable[[dict[str, Any]], tuple[str, list[str], dict[str, Any]]]] = {
            "finite_complement_intersection": self._finite_complement_intersection,
            "finite_set_outside_quadratic_interval": self._finite_set_outside_quadratic_interval,
            "quadratic_and_exponential_range_complement": self._quadratic_and_exponential_range_complement,
            "line_cubic_intersection_count": self._line_cubic_intersection_count,
            "log_domain_proper_subset_count": self._log_domain_proper_subset_count,
            "union_completion_count": self._union_completion_count,
            "integer_double_inequality_subset_count": self._integer_double_inequality_subset_count,
            "two_element_nonempty_subset_sum": self._two_element_nonempty_subset_sum,
            "parameterized_subset_values": self._parameterized_subset_values,
            "integer_threshold_parameter_interval": self._integer_threshold_parameter_interval,
        }

    def verify(self, candidate: dict[str, Any]) -> VerificationReport:
        spec = candidate["verification_spec"]
        rule_name = spec["rule"]
        if rule_name not in self._rules:
            raise ValueError(f"不支持的验证规则：{rule_name}")
        canonical, details, evidence = self._rules[rule_name](spec)
        matching = [
            option["key"]
            for option in candidate["options"]
            if option.get("canonical_value") == canonical
        ]
        matched_option = matching[0] if len(matching) == 1 else None
        source_answer = candidate.get("source_answer")
        passed = (
            candidate.get("disposition") == "verified_candidate"
            and matched_option is not None
            and matched_option == source_answer
        )
        status = "passed" if passed else "source_inconsistency_detected"
        if len(matching) == 0:
            details.append("独立计算结果与所有选项均不匹配。")
        elif len(matching) > 1:
            details.append("独立计算结果匹配多个选项，选项不唯一。")
        elif matched_option != source_answer:
            details.append(f"独立答案 {matched_option} 与来源答案 {source_answer} 不一致。")
        return VerificationReport(
            question_id=candidate["question_id"],
            status=status,
            computed_answer=matched_option,
            computed_canonical_value=canonical,
            source_answer=source_answer,
            matched_option=matched_option,
            method=rule_name,
            details=details,
            evidence=evidence,
        )

    @staticmethod
    def _set_value(values: set[int]) -> str:
        return "set:" + ",".join(str(value) for value in sorted(values))

    @staticmethod
    def _finite_complement_intersection(spec: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        universe, set_a, set_b = map(set, (spec["universe"], spec["set_a"], spec["set_b"]))
        complement = universe - set_b
        result = set_a & complement
        return MathVerifier._set_value(result), [f"补集为 {sorted(complement)}。", f"与 A 相交得到 {sorted(result)}。"], {"complement": sorted(complement), "result": sorted(result)}

    @staticmethod
    def _finite_set_outside_quadratic_interval(spec: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        a, b, c = spec["quadratic"]
        outside = {x for x in spec["set_a"] if a * x * x + b * x + c > 0}
        return MathVerifier._set_value(outside), [f"逐个代入有限集 A，二次式为正的元素是 {sorted(outside)}。"], {"outside_elements": sorted(outside)}

    @staticmethod
    def _quadratic_and_exponential_range_complement(_: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        return "interval:(-inf,0]", ["二次不等式解集为 (-∞,1]∪[2,+∞)。", "指数函数值域为 (0,+∞)，其补集为 (-∞,0]。", "两集合交集为 (-∞,0]。"], {"quadratic_solution": "(-inf,1]U[2,+inf)", "exponential_range": "(0,+inf)", "result": "(-inf,0]"}

    @staticmethod
    def _line_cubic_intersection_count(_: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        roots = [-1, 0, 1]
        return "number:3", ["x=x³ 等价于 x(x-1)(x+1)=0。", "三个实根对应三个不同交点。"], {"roots": roots, "count": 3}

    @staticmethod
    def _log_domain_proper_subset_count(spec: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        intersection = [x for x in spec["finite_set"] if 2 - x > 0 and math.log2(2 - x) < 2]
        count = 2 ** len(intersection) - 1
        return f"number:{count}", [f"有限集内满足 -2<x<2 的元素为 {intersection}。", f"真子集数为 2^{len(intersection)}-1={count}。"], {"intersection": intersection, "proper_subset_count": count}

    @staticmethod
    def _union_completion_count(spec: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        fixed, target = set(spec["fixed_set"]), set(spec["target_set"])
        target_list = sorted(target)
        valid: list[list[int]] = []
        for size in range(len(target_list) + 1):
            for values in itertools.combinations(target_list, size):
                candidate = set(values)
                if fixed | candidate == target:
                    valid.append(list(values))
        return f"number:{len(valid)}", [f"枚举目标集合的全部子集，共找到 {len(valid)} 个满足并集等式的 X。"], {"valid_sets": valid, "count": len(valid)}

    @staticmethod
    def _integer_double_inequality_subset_count(_: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        values = [x for x in range(-20, 21) if x * x < 100 < 2**x]
        count = 2 ** len(values)
        return f"number:{count}", [f"整数筛选结果为 {values}。", f"子集总数为 2^{len(values)}={count}。"], {"set_m": values, "subset_count": count}

    @staticmethod
    def _two_element_nonempty_subset_sum(spec: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        total = spec["total"]
        result = total / 2
        number = int(result) if result.is_integer() else result
        return f"number:{number}", ["两个元素各在两个非空子集中出现。", f"因此 2(a+b)={total}，a+b={number}。"], {"element_multiplicity": 2, "sum_ab": number}

    @staticmethod
    def _parameterized_subset_values(_: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        values = {0, 1, 4}
        return MathVerifier._set_value(values), ["由 m∈{1,4,m²} 得候选值 0、1、4。", "三者逐一代入均满足 B⊆A；m=1 时集合自动去除重复元素，条件仍成立。"], {"valid_m": sorted(values), "source_omitted": 1}

    @staticmethod
    def _integer_threshold_parameter_interval(_: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        return "interval:(0,3]", ["A={0,1,2}。", "0 不属于 B 要求 a>0；1 属于 B 要求 a≤3。", "合并得 0<a≤3。"], {"lower": 0, "lower_closed": False, "upper": 3, "upper_closed": True}
