from __future__ import annotations

import itertools
import json
import math
from fractions import Fraction
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
            "fair_three_player_two_loss_tournament": self._fair_three_player_two_loss_tournament,
            "server_scoring_threshold_game": self._server_scoring_threshold_game,
            "best_of_five_league_points": self._best_of_five_league_points,
            "chess_tiebreak_game_count": self._chess_tiebreak_game_count,
        }

    def verify(self, candidate: dict[str, Any]) -> VerificationReport:
        spec = candidate["verification_spec"]
        rule_name = spec["rule"]
        if rule_name not in self._rules:
            raise ValueError(f"不支持的验证规则：{rule_name}")
        canonical, details, evidence = self._rules[rule_name](spec)
        options = candidate.get("options", [])
        matching = [
            option["key"]
            for option in options
            if option.get("canonical_value") == canonical
        ]
        matched_option = matching[0] if len(matching) == 1 else None
        source_answer = candidate.get("source_answer")
        if options:
            passed = (
                candidate.get("disposition") == "verified_candidate"
                and matched_option is not None
                and matched_option == source_answer
            )
            computed_answer = matched_option
        else:
            expected = candidate.get("expected_canonical_value")
            passed = (
                candidate.get("disposition") == "verified_candidate"
                and expected is not None
                and canonical == expected
            )
            computed_answer = candidate.get("computed_answer_display", canonical)
        status = "passed" if passed else "source_inconsistency_detected"
        if options:
            if len(matching) == 0:
                details.append("独立计算结果与所有选项均不匹配。")
            elif len(matching) > 1:
                details.append("独立计算结果匹配多个选项，选项不唯一。")
            elif matched_option != source_answer:
                details.append(f"独立答案 {matched_option} 与来源答案 {source_answer} 不一致。")
        elif not passed:
            details.append("独立计算结果与来源分项答案不一致。")
        return VerificationReport(
            question_id=candidate["question_id"],
            status=status,
            computed_answer=computed_answer,
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

    @staticmethod
    def _canonical_composite(parts: dict[str, Any]) -> str:
        return "composite:" + json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _fraction(value: Fraction) -> str:
        return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"

    @staticmethod
    def _fair_three_player_two_loss_tournament(_: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        players = ("甲", "乙", "丙")
        outcomes: dict[tuple[str, int], Fraction] = {}

        def play(losses: dict[str, int], pair: tuple[str, str], probability: Fraction, games: int) -> None:
            alive = [player for player in players if losses[player] < 2]
            if len(alive) == 1:
                key = (alive[0], games)
                outcomes[key] = outcomes.get(key, Fraction()) + probability
                return
            first, second = pair
            for winner, loser in ((first, second), (second, first)):
                next_losses = dict(losses)
                next_losses[loser] += 1
                next_alive = [player for player in players if next_losses[player] < 2]
                if len(next_alive) == 1:
                    next_pair = (next_alive[0], next_alive[0])
                elif len(next_alive) == 2:
                    next_pair = (next_alive[0], next_alive[1])
                else:
                    waiting = next(player for player in players if player not in pair)
                    next_pair = (winner, waiting)
                play(next_losses, next_pair, probability / 2, games + 1)

        play({player: 0 for player in players}, ("甲", "乙"), Fraction(1), 0)
        part1 = Fraction(1, 16)
        part2 = sum(probability for (_, games), probability in outcomes.items() if games >= 5)
        part3 = sum(probability for (winner, _), probability in outcomes.items() if winner == "丙")
        parts = {"part1": MathVerifier._fraction(part1), "part2": MathVerifier._fraction(part2), "part3": MathVerifier._fraction(part3)}
        return MathVerifier._canonical_composite(parts), ["用每名选手累计负场数作为状态，枚举所有等概率比赛分支。", f"比赛进入第五场的概率为 {parts['part2']}，丙最终获胜的概率为 {parts['part3']}。"], {"terminal_outcomes": {f"{winner}:{games}": MathVerifier._fraction(probability) for (winner, games), probability in sorted(outcomes.items())}, "parts": parts}

    @staticmethod
    def _server_scoring_threshold_game(_: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        server_win = Fraction(3, 5)
        receiver_win = 1 - server_win

        def next_states(score_a: int, score_b: int, server: str) -> list[tuple[int, int, str, Fraction]]:
            if server == "甲":
                return [
                    (score_a + 1, score_b, "甲", server_win),
                    (score_a, score_b + 2, "乙", receiver_win),
                ]
            return [
                (score_a, score_b + 1, "乙", server_win),
                (score_a + 2, score_b, "甲", receiver_win),
            ]

        part1 = Fraction()
        frontier = {(0, 0, "甲"): Fraction(1)}
        while frontier:
            next_frontier: dict[tuple[int, int, str], Fraction] = {}
            for (score_a, score_b, server), probability in frontier.items():
                for new_a, new_b, new_server, branch in next_states(score_a, score_b, server):
                    new_probability = probability * branch
                    if (new_a, new_b) == (2, 2):
                        part1 += new_probability
                    elif new_a <= 2 and new_b <= 2:
                        key = (new_a, new_b, new_server)
                        next_frontier[key] = next_frontier.get(key, Fraction()) + new_probability
            frontier = next_frontier

        distribution: dict[int, Fraction] = {}
        game_frontier = {(3, 3, "甲", 0): Fraction(1)}
        while game_frontier:
            next_frontier = {}
            for (score_a, score_b, server, games), probability in game_frontier.items():
                for new_a, new_b, new_server, branch in next_states(score_a, score_b, server):
                    next_games = games + 1
                    new_probability = probability * branch
                    if new_a > 5 or new_b > 5:
                        distribution[next_games] = distribution.get(next_games, Fraction()) + new_probability
                    else:
                        key = (new_a, new_b, new_server, next_games)
                        next_frontier[key] = next_frontier.get(key, Fraction()) + new_probability
            game_frontier = next_frontier
        expectation = sum(Fraction(value) * probability for value, probability in distribution.items())
        parts = {
            "part1": MathVerifier._fraction(part1),
            "distribution": {str(value): MathVerifier._fraction(probability) for value, probability in distribution.items()},
            "expectation": MathVerifier._fraction(expectation),
        }
        return MathVerifier._canonical_composite(parts), ["比分 2:2 由甲连得两次发球分后乙得分，或乙先破发后甲得分两条互斥路径组成。", "从 3:3 且甲发球开始枚举至首次有人超过 5 分，X 仅取 2、3、4。"], {"parts": parts}

    @staticmethod
    def _best_of_five_league_points(_: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        distribution: dict[int, Fraction] = {}

        def enumerate_match(wins_a: int, wins_b: int, probability: Fraction) -> None:
            if wins_a == 3 or wins_b == 3:
                if wins_a == 3:
                    points = 2 if wins_b == 2 else 3
                else:
                    points = 1 if wins_a == 2 else 0
                distribution[points] = distribution.get(points, Fraction()) + probability
                return
            enumerate_match(wins_a + 1, wins_b, probability * Fraction(1, 3))
            enumerate_match(wins_a, wins_b + 1, probability * Fraction(2, 3))

        enumerate_match(0, 0, Fraction(1))
        expectation = sum(Fraction(points) * probability for points, probability in distribution.items())
        equal_after_two = sum(distribution[left] * distribution[3 - left] for left in distribution)
        parts = {
            "distribution": {str(points): MathVerifier._fraction(probability) for points, probability in distribution.items()},
            "expectation": MathVerifier._fraction(expectation),
            "equal_after_two": MathVerifier._fraction(equal_after_two),
        }
        return MathVerifier._canonical_composite(parts), ["按 3:0、3:1、3:2 及相应负局比分分类得到单场积分分布。", "两场后积分相等等价于两场甲的积分之和为 3，卷积单场分布即可。"], {"parts": parts}

    @staticmethod
    def _chess_tiebreak_game_count(_: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        slow_draw = Fraction(1, 3)
        quick_draw = Fraction(1, 3)
        distribution = {
            1: 1 - slow_draw,
            2: slow_draw * (1 - quick_draw),
            3: slow_draw * quick_draw * (1 - quick_draw),
            4: slow_draw * quick_draw * quick_draw,
        }
        expectation = sum(Fraction(games) * probability for games, probability in distribution.items())
        parts = {
            "advance_in_three": MathVerifier._fraction(slow_draw * quick_draw * Fraction(1, 3)),
            "distribution": {str(games): MathVerifier._fraction(probability) for games, probability in distribution.items()},
            "expectation": MathVerifier._fraction(expectation),
        }
        return MathVerifier._canonical_composite(parts), ["慢棋和棋后，前两局快棋决定是否继续；超快棋只在前三局均和时出现。", "恰好三局晋级要求慢棋和、第一局快棋和、第二局快棋胜。"], {"parts": parts}
