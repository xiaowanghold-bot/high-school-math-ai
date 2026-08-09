from __future__ import annotations

import re
from typing import Iterable

from app.modules.curriculum import CurriculumTreeNode
from app.modules.question_bank import QuestionBank, QuestionBankError

from .schemas import (
    CurrentCurriculumMapping,
    CurriculumMappingCommand,
    CurriculumSuggestion,
    ManualVerificationCommand,
    QualityActionResult,
    QuestionQualityWorkspace,
    VerificationWorkspace,
)


class QuestionQualityError(ValueError):
    pass


class QuestionQualityWorkflow:
    """Deep module for curriculum recommendation and verification evidence."""

    SYMBOL_CUES = {
        "∈": "元素集合关系",
        "\\in": "元素集合关系",
        "⊂": "子集真子集",
        "⊆": "子集",
        "∪": "并集集合运算",
        "∩": "交集集合运算",
        "∁": "补集集合运算",
        "\\cup": "并集集合运算",
        "\\cap": "交集集合运算",
        "f(": "函数",
        "sin": "正弦三角函数",
        "cos": "余弦三角函数",
        "tan": "正切三角函数",
        "log": "对数函数",
        "ln": "对数函数",
        "最大值": "最值",
        "最小值": "最值",
    }

    def __init__(self, *, question_bank: QuestionBank, curriculum_catalog) -> None:
        self.question_bank = question_bank
        self.curriculum_catalog = curriculum_catalog

    def inspect(self, question_id: str) -> QuestionQualityWorkspace:
        question = self.question_bank.get_question(question_id)
        raw_curriculum = question.raw.get("curriculum") or {}
        verification = question.raw.get("verification") or {}
        capability = (
            "already_verified"
            if question.verification_status == "passed"
            else "rule_based"
            if question.raw.get("verification_spec")
            else "teacher_evidence_required"
        )
        return QuestionQualityWorkspace(
            question_id=question_id,
            current_curriculum=CurrentCurriculumMapping(
                volume=question.volume or raw_curriculum.get("volume"),
                chapter=question.chapter or raw_curriculum.get("chapter"),
                section=question.section or raw_curriculum.get("section"),
                knowledge_point_ids=question.knowledge_point_ids,
            ),
            curriculum_suggestions=self._recommend(question.stem_plain, question.raw),
            verification=VerificationWorkspace(
                status=question.verification_status,
                capability=capability,
                source_answer=question.answer_value,
                computed_answer=verification.get("computed_answer"),
                method=(verification.get("methods") or [None])[0],
                details=[str(item) for item in verification.get("details") or []],
            ),
        )

    def apply_curriculum(
        self, question_id: str, command: CurriculumMappingCommand
    ) -> QualityActionResult:
        try:
            node = self.curriculum_catalog.get_node(command.node_id)
        except KeyError as exc:
            raise QuestionQualityError("教材知识点不存在") from exc
        if node.node_type != "knowledge_point":
            raise QuestionQualityError("必须选择具体知识点，不能只选择册次、章节或小节")
        paths = self._node_paths()
        path = paths.get(node.node_id)
        if path is None:
            raise QuestionQualityError("教材知识点路径不完整")
        self.question_bank.apply_curriculum_mapping(
            question_id,
            node_id=node.node_id,
            volume=node.volume,
            chapter=path["chapter"],
            section=path["section"],
            topic=node.name,
            actor_id=command.teacher_id,
        )
        return QualityActionResult(
            workspace=self.inspect(question_id),
            status="curriculum_applied",
            message=f"已应用知识点“{node.name}”；题目仍保持原有私人和验证状态。",
        )

    def record_verification(
        self, question_id: str, command: ManualVerificationCommand
    ) -> QualityActionResult:
        if not command.independently_checked:
            raise QuestionQualityError("必须确认答案和推导由教师独立核验")
        steps = [step.strip() for step in command.evidence_steps if step.strip()]
        if not steps:
            raise QuestionQualityError("必须提供至少一条可复核的推导证据")
        try:
            result = self.question_bank.record_manual_verification(
                question_id,
                conclusion=command.conclusion,
                computed_answer=command.computed_answer.strip(),
                evidence_steps=steps,
                note=command.note.strip(),
                verifier_id=command.verifier_id,
            )
        except QuestionBankError as exc:
            raise QuestionQualityError(str(exc)) from exc
        messages = {
            "passed": "独立核验已通过；题目仍需完成教师内容审核后才能发布或进入正式试卷。",
            "source_inconsistency_detected": "独立结果与当前答案不一致，题目已标记为来源矛盾。",
            "needs_math_review": "已保存核验记录，当前证据不足以判定通过。",
        }
        return QualityActionResult(
            workspace=self.inspect(question_id),
            status=result,
            message=messages[result],
        )

    def _recommend(self, stem: str, raw: dict) -> list[CurriculumSuggestion]:
        solution_text = " ".join(
            " ".join(str(step) for step in solution.get("steps_latex") or [])
            for solution in raw.get("solutions") or []
        )
        source_text = f"{stem} {solution_text}"
        expanded = source_text
        for cue, words in self.SYMBOL_CUES.items():
            if cue in source_text:
                expanded += f" {words}"
        question_text = self._normalize(expanded)
        paths = self._node_paths()
        suggestions: list[CurriculumSuggestion] = []
        for node in self._knowledge_points(self.curriculum_catalog.get_tree()):
            normalized_name = self._normalize(node.name)
            name_grams = self._ngrams(normalized_name)
            matched = sorted(
                {gram for gram in name_grams if gram in question_text},
                key=lambda item: (-len(item), item),
            )
            corpus = self._normalize(
                " ".join([node.description, *node.typical_question_types, *node.common_errors])
            )
            corpus_matches = [
                gram for gram in self._ngrams(question_text, lengths=(2, 3))
                if gram in corpus
            ]
            exact = bool(normalized_name and normalized_name in question_text)
            if not exact and not matched and not corpus_matches:
                continue
            score = min(0.98, 0.18 + (0.55 if exact else 0) + 0.09 * len(matched[:4]) + 0.03 * len(corpus_matches[:3]))
            reasons = []
            if exact:
                reasons.append(f"题干或解析直接出现“{node.name}”")
            if matched:
                reasons.append(f"匹配关键词：{'、'.join(matched[:3])}")
            if corpus_matches:
                reasons.append("与该知识点的典型题型或易错描述相符")
            path = paths[node.node_id]
            suggestions.append(
                CurriculumSuggestion(
                    node_id=node.node_id,
                    name=node.name,
                    volume=node.volume,
                    chapter=path["chapter"],
                    section=path["section"],
                    confidence=round(score, 2),
                    reasons=reasons,
                )
            )
        return sorted(suggestions, key=lambda item: (-item.confidence, item.node_id))[:5]

    def _node_paths(self) -> dict[str, dict[str, str]]:
        result: dict[str, dict[str, str]] = {}

        def walk(node: CurriculumTreeNode, chapter: str = "", section: str = "") -> None:
            next_chapter = node.name if node.node_type == "chapter" else chapter
            next_section = node.name if node.node_type == "section" else section
            result[node.node_id] = {"chapter": next_chapter, "section": next_section}
            for child in node.children:
                walk(child, next_chapter, next_section)

        walk(self.curriculum_catalog.get_tree())
        return result

    @staticmethod
    def _knowledge_points(root: CurriculumTreeNode) -> Iterable[CurriculumTreeNode]:
        if root.node_type == "knowledge_point":
            yield root
        for child in root.children:
            yield from QuestionQualityWorkflow._knowledge_points(child)

    @staticmethod
    def _normalize(value: str) -> str:
        value = value.lower().replace("的", "").replace("与", "").replace("及", "").replace("和", "")
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value)

    @staticmethod
    def _ngrams(value: str, *, lengths: tuple[int, ...] = (2, 3, 4)) -> set[str]:
        return {
            value[index : index + length]
            for length in lengths
            for index in range(max(0, len(value) - length + 1))
            if len(value[index : index + length]) == length
        }

