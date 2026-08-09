from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.modules.question_bank import QuestionBank
from app.modules.question_bank.schemas import QuestionDetail
from app.modules.solution_assistant.providers import SolutionProvider
from app.modules.solution_assistant.schemas import (
    SolutionExplanation,
    SolutionRequest,
    SolutionResult,
)


class SolutionAssistantError(ValueError):
    pass


class SolutionAssistant:
    """Solves through one interface while keeping trust decisions internal."""

    MATCH_THRESHOLD = 0.88
    KNOWLEDGE_POINT_LABELS = {
        "kp_function_extrema": "函数最值",
        "kp_function_inequality": "函数与不等式",
        "kp_function_parity": "函数奇偶性",
        "kp_function_periodicity": "函数周期性",
        "kp_function_symmetry": "函数对称性",
        "kp_graph_transformation": "函数图象变换",
        "kp_probability": "概率",
        "kp_quadratic_function": "二次函数",
        "kp_random_variable_distribution": "随机变量及其分布",
        "kp_sets_and_logic": "集合与常用逻辑用语",
    }

    def __init__(
        self,
        *,
        question_bank: QuestionBank,
        provider: SolutionProvider | None = None,
    ) -> None:
        self.question_bank = question_bank
        self.provider = provider

    def solve(self, request: SolutionRequest) -> SolutionResult:
        match, score = self._best_verified_match(request.question_text)
        if match is not None:
            solutions = match.raw.get("solutions") or []
            solution_index = 1 if request.solution_mode == "alternative" else 0
            if len(solutions) > solution_index:
                return self._from_verified_question(
                    request, match, solutions[solution_index], score
                )
        if self.provider is not None:
            generated = self.provider.solve(request)
            return SolutionResult(
                question_text=request.question_text,
                solution_mode=request.solution_mode,
                **generated.model_dump(),
                confidence_status="teacher_review_required",
                verification_evidence=[
                    "答案与解析由大模型生成，尚未经过独立数学程序或第二模型复核。"
                ],
                provider=self.provider.name,
                model=self.provider.model,
                mode="live_ai",
                matched_question_id=match.question_id if match else None,
                match_score=score if match else None,
                alternative_available=True,
                warnings=["请由教师核对条件、推导过程和最终答案后再用于教学。"],
            )
        if match is not None and request.solution_mode == "alternative":
            raise SolutionAssistantError(
                "当前题库只保存了一种已验证解法；配置 OpenAI API Key 后可生成第二种解法。"
            )
        raise SolutionAssistantError(
            "当前文字题未匹配到已验证题库；配置 OpenAI API Key 后可解答任意新题。"
        )

    def _best_verified_match(
        self, question_text: str
    ) -> tuple[QuestionDetail | None, float | None]:
        target = self._normalize(question_text)
        candidates = self.question_bank.search(
            verification_status="passed", page=1, page_size=100
        ).items
        best = None
        best_score = 0.0
        for candidate in candidates:
            stem = self._normalize(candidate.stem_plain)
            if not stem:
                continue
            if stem in target:
                score = 1.0
            elif target in stem and len(target) >= len(stem) * self.MATCH_THRESHOLD:
                score = len(target) / len(stem)
            else:
                score = SequenceMatcher(None, target, stem).ratio()
            if score > best_score:
                best = candidate
                best_score = score
        if best is None or best_score < self.MATCH_THRESHOLD:
            return None, None
        return self.question_bank.get_question(best.question_id), round(best_score, 4)

    def _from_verified_question(
        self,
        request: SolutionRequest,
        question: QuestionDetail,
        solution: dict,
        score: float | None,
    ) -> SolutionResult:
        steps = [
            str(step).strip()
            for step in solution.get("steps_latex", [])
            if str(step).strip()
        ]
        if not steps:
            steps = ["该题已通过独立验证，但题库解析步骤仍需教师补充。"]
        final_answer = str(
            solution.get("final_answer") or question.answer_value or "待教师确认"
        ).strip()
        verification = question.raw.get("verification") or {}
        evidence = [
            str(item).strip()
            for item in verification.get("details", [])
            if str(item).strip()
        ]
        if not evidence:
            evidence = ["题库记录标记为已通过独立数学验证。"]
        all_solutions = question.raw.get("solutions") or []
        raw_knowledge_points = question.raw.get("curriculum", {}).get(
            "knowledge_point_ids", question.knowledge_point_ids
        ) or question.knowledge_point_ids
        knowledge_points = [
            self.KNOWLEDGE_POINT_LABELS.get(str(item), str(item))
            for item in raw_knowledge_points
        ]
        return SolutionResult(
            question_text=request.question_text,
            solution_mode=request.solution_mode,
            explanation=SolutionExplanation(
                method=str(solution.get("method") or "题库标准解法"),
                steps=steps,
                final_answer=final_answer,
            ),
            knowledge_points=knowledge_points,
            common_mistakes=self._common_mistakes(question),
            teaching_notes=[
                "建议先让学生说明关键条件，再展示完整推导。",
                "题库解析可以继续在审核台由教师修订。",
            ],
            confidence_status="program_verified",
            verification_evidence=evidence,
            provider="verified_question_bank",
            model="independent-math-verifier",
            mode="verified_bank",
            matched_question_id=question.question_id,
            match_score=score,
            alternative_available=len(all_solutions) > 1 or self.provider is not None,
            warnings=["结果来自当前私有题库的已验证题目，请核对输入是否与原题条件完全一致。"],
        )

    @staticmethod
    def _common_mistakes(question: QuestionDetail) -> list[str]:
        raw_items = question.raw.get("pedagogy", {}).get("common_mistakes", [])
        mistakes = [str(item).strip() for item in raw_items if str(item).strip()]
        if mistakes:
            return mistakes[:8]
        if question.question_type in {"single_choice", "multiple_choice"}:
            return ["只凭局部条件排除选项，未完成全部条件核验。"]
        return ["跳过关键等价变形或遗漏题目中的取值范围。"]

    @staticmethod
    def _normalize(value: str) -> str:
        value = value.lower().replace("$", "")
        value = re.sub(r"\s+", "", value)
        return re.sub(r"[，。；：、,.!?！？（）()\[\]{}]", "", value)
