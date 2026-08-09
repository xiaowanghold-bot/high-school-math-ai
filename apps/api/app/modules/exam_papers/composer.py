from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
from math import floor

from app.modules.exam_papers.schemas import (
    ExamPaperBreakdownItem,
    ExamPaperComposeCommand,
    ExamPaperProposal,
    ExamPaperProposalItem,
)
from app.modules.question_bank.schemas import QuestionSummary


class ExamPaperComposeError(ValueError):
    pass


class ExamPaperComposer:
    """Builds an editable paper proposal from verified question-bank facts.

    The interface accepts a teaching blueprint and returns selected question IDs,
    exact scores and explainable selection reasons. Persistence and export remain
    the responsibility of ExamPaperStudio and ExamPaperDocumentRenderer.
    """

    PROFILE_WEIGHTS = {
        "foundation": {1: 0.25, 2: 0.45, 3: 0.25, 4: 0.05, 5: 0.0},
        "balanced": {1: 0.05, 2: 0.25, 3: 0.4, 4: 0.25, 5: 0.05},
        "challenge": {1: 0.0, 2: 0.1, 3: 0.3, 4: 0.4, 5: 0.2},
    }
    PROFILE_LABELS = {
        "foundation": "基础巩固",
        "balanced": "均衡",
        "challenge": "能力提升",
    }
    TYPE_SCORE_WEIGHTS = {
        "single_choice": 5,
        "multiple_choice": 5,
        "fill_blank": 5,
        "open_response": 12,
        "composite": 12,
    }

    def __init__(self, question_bank) -> None:
        self.question_bank = question_bank

    def compose(self, command: ExamPaperComposeCommand) -> ExamPaperProposal:
        total_count = sum(quota.count for quota in command.type_quotas)
        if command.target_score < total_count * 0.5:
            raise ExamPaperComposeError("目标总分过低：每道题至少需要 0.5 分")
        if command.target_score > total_count * 50:
            raise ExamPaperComposeError("目标总分过高：单题分值不能超过 50 分")

        candidates = self._verified_candidates(command)
        chapter_usage: Counter[str] = Counter()
        selections: list[tuple[QuestionSummary, int]] = []
        for quota in command.type_quotas:
            matching = [item for item in candidates if item.question_type == quota.question_type]
            if len(matching) < quota.count:
                label = self._question_type_label(quota.question_type)
                raise ExamPaperComposeError(
                    f"符合条件的{label}不足：需要 {quota.count} 道，当前只有 {len(matching)} 道"
                )
            targets = self._difficulty_slots(quota.count, command.difficulty_profile)
            remaining = list(matching)
            for target in targets:
                selected = min(
                    remaining,
                    key=lambda item: (
                        abs(item.difficulty - target),
                        chapter_usage[item.chapter or "未分类"],
                        0 if item.review_status == "approved" else 1,
                        self._stable_rank(command.seed, item.question_id),
                    ),
                )
                remaining.remove(selected)
                chapter_usage[selected.chapter or "未分类"] += 1
                selections.append((selected, target))

        scores = self._allocate_scores(
            command.target_score,
            [self.TYPE_SCORE_WEIGHTS.get(item.question_type, 10) for item, _ in selections],
        )
        items = [
            ExamPaperProposalItem(
                question=question,
                score=score,
                selection_reason=(
                    f"{self.PROFILE_LABELS[command.difficulty_profile]}难度 · "
                    f"目标 {target} 级，实际 {question.difficulty} 级 · "
                    f"{question.chapter or '未分类'}"
                ),
            )
            for (question, target), score in zip(selections, scores, strict=True)
        ]
        return self._proposal(command, items)

    def _verified_candidates(self, command: ExamPaperComposeCommand) -> list[QuestionSummary]:
        candidates: list[QuestionSummary] = []
        page = 1
        while True:
            result = self.question_bank.search(
                verification_status="passed",
                page=page,
                page_size=100,
            )
            candidates.extend(result.items)
            if len(candidates) >= result.total:
                break
            page += 1

        excluded = set(command.exclude_question_ids)
        chapters = set(command.chapters)
        return [
            item
            for item in candidates
            if item.question_id not in excluded
            and item.review_status != "rejected"
            and (not chapters or item.chapter in chapters)
            and (
                command.review_policy == "verified"
                or item.review_status == "approved"
            )
        ]

    def _difficulty_slots(self, count: int, profile: str) -> list[int]:
        weights = self.PROFILE_WEIGHTS[profile]
        raw = {difficulty: count * weight for difficulty, weight in weights.items()}
        allocated = {difficulty: floor(value) for difficulty, value in raw.items()}
        remainder = count - sum(allocated.values())
        order = sorted(
            weights,
            key=lambda difficulty: (raw[difficulty] - allocated[difficulty], weights[difficulty]),
            reverse=True,
        )
        for difficulty in order[:remainder]:
            allocated[difficulty] += 1
        return [
            difficulty
            for difficulty in sorted(allocated)
            for _ in range(allocated[difficulty])
        ]

    @staticmethod
    def _allocate_scores(target_score: float, weights: list[int]) -> list[float]:
        target_units = round(target_score * 2)
        allocated = [1] * len(weights)
        desired = [target_units * weight / sum(weights) for weight in weights]
        for _ in range(target_units - len(weights)):
            available = [index for index, value in enumerate(allocated) if value < 100]
            if not available:
                raise ExamPaperComposeError("无法在单题 50 分限制内完成目标配分")
            index = max(available, key=lambda item: (desired[item] - allocated[item], -item))
            allocated[index] += 1
        return [value / 2 for value in allocated]

    def _proposal(
        self, command: ExamPaperComposeCommand, items: list[ExamPaperProposalItem]
    ) -> ExamPaperProposal:
        chapter_counts: dict[str, list[float]] = defaultdict(list)
        difficulty_counts: dict[int, list[float]] = defaultdict(list)
        for item in items:
            chapter_counts[item.question.chapter or "未分类"].append(item.score)
            difficulty_counts[item.question.difficulty].append(item.score)

        average = sum(item.question.difficulty for item in items) / len(items)
        desired_average = sum(
            difficulty * weight
            for difficulty, weight in self.PROFILE_WEIGHTS[command.difficulty_profile].items()
        )
        warnings: list[str] = []
        pending = sum(item.question.review_status != "approved" for item in items)
        if pending:
            warnings.append(f"自动草稿含 {pending} 道待教师审核题，请逐题确认后再保存。")
        if abs(average - desired_average) >= 0.75:
            warnings.append(
                f"受当前题库供给限制，实际平均难度 {average:.1f} 与目标 {desired_average:.1f} 有偏差。"
            )

        return ExamPaperProposal(
            target_score=command.target_score,
            actual_score=sum(item.score for item in items),
            average_difficulty=round(average, 2),
            items=items,
            chapter_breakdown=[
                ExamPaperBreakdownItem(
                    label=label, question_count=len(scores), score=sum(scores)
                )
                for label, scores in sorted(chapter_counts.items())
            ],
            difficulty_breakdown=[
                ExamPaperBreakdownItem(
                    label=f"难度 {difficulty}",
                    question_count=len(scores),
                    score=sum(scores),
                )
                for difficulty, scores in sorted(difficulty_counts.items())
            ],
            warnings=warnings,
        )

    @staticmethod
    def _stable_rank(seed: str, question_id: str) -> str:
        return sha256(f"{seed}:{question_id}".encode("utf-8")).hexdigest()

    @staticmethod
    def _question_type_label(question_type: str) -> str:
        return {
            "single_choice": "单选题",
            "multiple_choice": "多选题",
            "fill_blank": "填空题",
            "open_response": "解答题",
            "composite": "综合题",
        }.get(question_type, question_type)
