from __future__ import annotations

from app.modules.exam_papers.schemas import (
    ExamPaperTemplate,
    ExamPaperTemplateList,
    ExamPaperTemplateSection,
)


class ExamPaperTemplateError(ValueError):
    pass


class ExamPaperTemplateCatalog:
    """Owns versioned reference structures and their evidence metadata."""

    _TEMPLATES = (
        ExamPaperTemplate(
            template_id="gaokao-i-recent-19q-v1",
            name="新高考Ⅰ卷·近年19题结构",
            description="150 分、120 分钟；8 道单选、3 道多选、3 道填空、5 道解答。",
            region_scope="采用全国Ⅰ卷的新高考地区",
            duration_minutes=120,
            target_score=150,
            difficulty_profile="balanced",
            sections=[
                ExamPaperTemplateSection(
                    section_title="一、单项选择题",
                    question_type="single_choice",
                    count=8,
                    item_scores=[5] * 8,
                ),
                ExamPaperTemplateSection(
                    section_title="二、多项选择题",
                    question_type="multiple_choice",
                    count=3,
                    item_scores=[6] * 3,
                ),
                ExamPaperTemplateSection(
                    section_title="三、填空题",
                    question_type="fill_blank",
                    count=3,
                    item_scores=[5] * 3,
                ),
                ExamPaperTemplateSection(
                    section_title="四、解答题",
                    question_type="open_response",
                    count=5,
                    item_scores=[13, 15, 15, 17, 17],
                ),
            ],
            structure_status="recent_reference",
            reviewed_on="2026-08-09",
            verification_note=(
                "依据2025、2026年公开试卷与教育考试部门评析整理，属于近年参考结构，"
                "并非对未来命题结构不变的承诺；正式使用前由教师核对当年考试说明。"
            ),
            evidence_urls=[
                "https://www.moe.gov.cn/jyb_xwfb/xw_zt/moe_357/2026/2026_zt08/mtbd/202606/t20260610_1440059.html",
                "https://edu.jixi.gov.cn/Article/49686.html",
            ],
        ),
    )

    def list(self) -> ExamPaperTemplateList:
        items = [item.model_copy(deep=True) for item in self._TEMPLATES]
        return ExamPaperTemplateList(items=items, total=len(items))

    def get(self, template_id: str) -> ExamPaperTemplate:
        for template in self._TEMPLATES:
            if template.template_id == template_id:
                return template.model_copy(deep=True)
        raise ExamPaperTemplateError(f"试卷模板不存在：{template_id}")
