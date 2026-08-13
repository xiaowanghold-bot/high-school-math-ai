from __future__ import annotations

from app.modules.question_bank import QuestionBank
from app.modules.question_variants.providers import (
    QuestionVariantGenerationContext,
    QuestionVariantProvider,
)
from app.modules.question_variants.schemas import (
    QuestionVariantGenerationRequest,
    QuestionVariantGenerationResult,
    TeacherVariantDraftCommand,
)


class QuestionVariantServiceError(ValueError):
    pass


class QuestionVariantService:
    """Coordinates trusted-source checks, generation and private draft persistence."""

    def __init__(self, *, question_bank: QuestionBank, provider: QuestionVariantProvider) -> None:
        self.question_bank = question_bank
        self.provider = provider

    def generate(
        self, source_question_id: str, request: QuestionVariantGenerationRequest
    ) -> QuestionVariantGenerationResult:
        source = self.question_bank.get_question(source_question_id)
        if source.verification_status != "passed":
            raise QuestionVariantServiceError("原题尚未通过独立数学验证，不能作为自动变式母题")
        generated = self.provider.generate(
            QuestionVariantGenerationContext(source=source, request=request)
        )
        question = self.question_bank.create_derived_question(
            source_question_id,
            generated.model_dump(),
            generation={
                "provider": self.provider.name,
                "model": self.provider.model,
                "mode": "live_ai" if self.provider.name in {"openai", "deepseek"} else "local_rule",
                "request": request.model_dump(),
            },
        )
        warnings = ["变式已保存为私有草稿，必须经教师审核后才能进入正式题库。"]
        if generated.verification_status != "passed":
            warnings.append("大模型生成内容尚未经过独立数学验证，当前不可标记为教师通过。")
        if any(image.placement == "stem" for image in source.images):
            warnings.append("原题题干图片已复制到变式的固定图片槽，请复核图文条件是否仍然一致。")
        return QuestionVariantGenerationResult(
            question=question,
            source_question_id=source_question_id,
            provider=self.provider.name,
            model=self.provider.model,
            mode="live_ai" if self.provider.name in {"openai", "deepseek"} else "local_rule",
            warnings=warnings,
        )

    def save_teacher_draft(
        self, source_question_id: str, command: TeacherVariantDraftCommand
    ):
        source = self.question_bank.get_question(source_question_id)
        if source.verification_status != "passed":
            raise QuestionVariantServiceError("只有已验证母题可以另存为教师私有变式")
        candidate = command.model_dump(exclude={"teacher_id"})
        candidate.update(
            verification_status="needs_math_review",
            verification_details=["教师自拟变式，答案和解析需重新独立验算"],
        )
        candidate["options"] = [item.model_dump() for item in command.options]
        return self.question_bank.create_derived_question(
            source_question_id,
            candidate,
            generation={
                "provider": "teacher",
                "model": "teacher-authored-v1",
                "mode": "teacher_authored",
                "request": {"variant_kind": "teacher_custom", "teacher_id": command.teacher_id},
            },
        )
