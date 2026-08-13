from __future__ import annotations

import re
from typing import Iterable

from app.modules.curriculum import CurriculumTreeNode
from app.modules.question_bank import QuestionBank, QuestionBankError

from .schemas import (
    BatchCurriculumActionResult,
    BatchCurriculumMappingCommand,
    BatchCurriculumQuestion,
    BatchCurriculumWorkspace,
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

    # These aliases are deliberately narrow. Generic symbols such as ``a∈R`` and
    # ``f(x)`` occur across the whole curriculum and must never create a confident
    # recommendation on their own.
    TOPIC_ALIASES = {
        "∪": "并集",
        "\\cup": "并集",
        "∩": "交集",
        "\\cap": "交集",
        "⊂": "真子集",
        "⊆": "子集",
        "贝叶斯": "贝叶斯公式",
        "全概率": "全概率公式",
        "条件概率": "条件概率",
        "分布列": "分布列",
        "数学期望": "离散型随机变量均值",
        "单调性": "函数单调性",
        "增函数": "函数单调性",
        "减函数": "函数单调性",
        "切线方程": "切线方程",
        "极值点": "函数极值",
        "导函数": "导数",
        "f'": "导数",
        "f′": "导数",
        "椭圆": "椭圆",
        "双曲线": "双曲线",
        "抛物线": "抛物线",
        "二面角": "二面角",
        "线面角": "线面角",
    }
    HIGH_CONFIDENCE_THRESHOLD = 0.9
    HIGH_CONFIDENCE_MARGIN = 0.08

    def __init__(self, *, question_bank: QuestionBank, curriculum_catalog) -> None:
        self.question_bank = question_bank
        self.curriculum_catalog = curriculum_catalog

    def inspect(self, question_id: str) -> QuestionQualityWorkspace:
        question = self.question_bank.get_question(question_id)
        raw_curriculum = question.raw.get("curriculum") or {}
        verification = question.raw.get("verification") or {}
        knowledge_point_names = []
        for node_id in question.knowledge_point_ids:
            try:
                knowledge_point_names.append(self.curriculum_catalog.get_node(node_id).name)
            except KeyError:
                knowledge_point_names.append(node_id)
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
                knowledge_point_names=knowledge_point_names,
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

    def inspect_curriculum_batch(self, question_ids: list[str]) -> BatchCurriculumWorkspace:
        unique_ids = list(dict.fromkeys(question_ids))
        if not unique_ids:
            raise QuestionQualityError("至少选择一道已进入题库的题目")
        items: list[BatchCurriculumQuestion] = []
        for question_id in unique_ids:
            workspace = self.inspect(question_id)
            question = self.question_bank.get_question(question_id)
            if workspace.current_curriculum.knowledge_point_ids:
                status = "already_mapped"
            elif not workspace.curriculum_suggestions:
                status = "no_suggestion"
            elif self._is_high_confidence(workspace.curriculum_suggestions):
                status = "high_confidence"
            else:
                status = "review_required"
            items.append(
                BatchCurriculumQuestion(
                    question_id=question_id,
                    stem_plain=question.stem_plain,
                    source_document=question.source_document,
                    source_page_start=question.source_page_start,
                    source_page_end=question.source_page_end,
                    current_curriculum=workspace.current_curriculum,
                    suggestions=workspace.curriculum_suggestions,
                    recommendation_status=status,
                )
            )
        return BatchCurriculumWorkspace(
            total=len(items),
            mapped_count=sum(item.recommendation_status == "already_mapped" for item in items),
            high_confidence_count=sum(item.recommendation_status == "high_confidence" for item in items),
            review_required_count=sum(item.recommendation_status == "review_required" for item in items),
            no_suggestion_count=sum(item.recommendation_status == "no_suggestion" for item in items),
            items=items,
        )

    def _is_high_confidence(self, suggestions: list[CurriculumSuggestion]) -> bool:
        if not suggestions or suggestions[0].confidence < self.HIGH_CONFIDENCE_THRESHOLD:
            return False
        runner_up = suggestions[1].confidence if len(suggestions) > 1 else 0
        return suggestions[0].confidence - runner_up >= self.HIGH_CONFIDENCE_MARGIN

    def apply_curriculum_batch(
        self, command: BatchCurriculumMappingCommand
    ) -> BatchCurriculumActionResult:
        unique: dict[str, str] = {}
        for mapping in command.mappings:
            if mapping.question_id in unique:
                raise QuestionQualityError("同一道题不能在一次操作中映射多个知识点")
            unique[mapping.question_id] = mapping.node_id

        # Validate the complete command before writing, so a bad node never leaves
        # a teacher's batch half-applied.
        for question_id, node_id in unique.items():
            self.question_bank.get_question(question_id)
            try:
                node = self.curriculum_catalog.get_node(node_id)
            except KeyError as exc:
                raise QuestionQualityError(f"教材知识点不存在：{node_id}") from exc
            if node.node_type != "knowledge_point":
                raise QuestionQualityError("批量映射必须选择具体知识点")

        for question_id, node_id in unique.items():
            self.apply_curriculum(
                question_id,
                CurriculumMappingCommand(node_id=node_id, teacher_id=command.teacher_id),
            )
        return BatchCurriculumActionResult(
            applied_count=len(unique),
            question_ids=list(unique),
            message=f"已由教师确认 {len(unique)} 道题的人教 A 版知识点；题目仍需独立数学核验和内容审核。",
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
        question_text = self._normalize(source_text)
        aliases = {
            alias for cue, alias in self.TOPIC_ALIASES.items() if cue.lower() in source_text.lower()
        }
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
            exact = bool(len(normalized_name) >= 3 and normalized_name in question_text)
            alias_match = any(
                self._normalize(alias) in normalized_name or normalized_name in self._normalize(alias)
                for alias in aliases
            )
            useful_matches = [gram for gram in matched if len(gram) >= 3]
            if not exact and not alias_match and not useful_matches and not corpus_matches:
                continue
            score = min(
                0.98,
                0.16
                + (0.66 if exact else 0)
                + (0.68 if alias_match else 0)
                + 0.06 * len(useful_matches[:3])
                + 0.025 * len(corpus_matches[:3]),
            )
            reasons = []
            if exact:
                reasons.append(f"题干或解析直接出现“{node.name}”")
            if alias_match:
                reasons.append("匹配到该知识点的专用数学术语")
            if useful_matches:
                reasons.append(f"匹配关键词：{'、'.join(useful_matches[:3])}")
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
