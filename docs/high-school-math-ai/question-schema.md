# 题目数据结构草案 v0.1

## 设计目标

题目必须同时支持教材同步、自然语言搜索、高考专题、数学验证、版权追溯和教师审核。

## 示例

```json
{
  "id": "q_01J...",
  "status": "reviewed",
  "visibility": "public",
  "language": "zh-CN",
  "stem": {
    "latex": "已知函数 $f(x)=...$",
    "plain_text": "已知函数 f(x)=...",
    "assets": []
  },
  "question_type": "single_choice",
  "options": [
    {"key": "A", "latex": "..."},
    {"key": "B", "latex": "..."},
    {"key": "C", "latex": "..."},
    {"key": "D", "latex": "..."}
  ],
  "answer": {
    "type": "option",
    "value": "C",
    "alternatives": []
  },
  "solutions": [
    {
      "method": "定义法",
      "steps_latex": ["..."],
      "final_answer": "C",
      "author_type": "teacher",
      "review_status": "approved"
    }
  ],
  "curriculum": {
    "curriculum_version": "CN-HS-MATH-2017-2020",
    "textbook": "PEP-A",
    "volume": "必修第一册",
    "chapter": "第三章 函数的概念与性质",
    "section": "3.2 函数的基本性质",
    "knowledge_point_ids": ["kp_function_monotonicity"],
    "prerequisite_ids": ["kp_function_concept"]
  },
  "exam": {
    "paper_family": "新高考全国I卷",
    "region": null,
    "year": null,
    "original_score": 5,
    "competency_tags": ["逻辑推理", "数学运算"]
  },
  "pedagogy": {
    "difficulty": 3,
    "difficulty_confidence": 0.82,
    "estimated_minutes": 4,
    "methods": ["定义法"],
    "common_errors": ["忽略区间限制"],
    "usage_scenarios": ["课堂练习", "课后作业"]
  },
  "verification": {
    "status": "passed",
    "methods": ["symbolic", "option_uniqueness"],
    "verifier_version": "0.1.0",
    "checked_at": "2026-08-03T00:00:00Z",
    "details": []
  },
  "source": {
    "source_id": "SRC-008",
    "original_identifier": null,
    "author": "签约教师ID",
    "license_status": "commercial_granted",
    "allowed_uses": ["display", "modify", "generate_derivatives", "train"],
    "attribution_required": false,
    "proof_document_id": "grant_..."
  },
  "provenance": {
    "created_by": "teacher",
    "derived_from_question_ids": [],
    "model_run_id": null,
    "duplicate_cluster_id": null
  },
  "reviews": [
    {
      "reviewer_id": "teacher_...",
      "review_type": "math",
      "result": "approved",
      "reviewed_at": "2026-08-03T00:00:00Z"
    }
  ],
  "created_at": "2026-08-03T00:00:00Z",
  "updated_at": "2026-08-03T00:00:00Z"
}
```

## 必填字段

- `id`
- `status`
- `visibility`
- `stem.latex` 或 `stem.plain_text`
- `question_type`
- `answer`
- `curriculum.knowledge_point_ids`
- `pedagogy.difficulty`
- `verification.status`
- `source.source_id`
- `source.license_status`
- `provenance.created_by`

## 题型枚举

- `single_choice`
- `multiple_choice`
- `fill_blank`
- `short_answer`
- `proof`
- `open_ended`
- `composite`

## 内容状态

- `imported`：刚导入，尚未校对。
- `formatted`：公式、图片和结构已校对。
- `verified`：通过程序或数学审核。
- `reviewed`：通过教学审核。
- `published`：版权与质量满足商业发布要求。
- `rejected`：存在错误、重复或权利风险。

## 可见性

- `private`：仅上传者可见。
- `organization`：所属教研组或学校可见。
- `public`：商业公共题库可见。
- `research_only`：仅离线评测和研究使用。

## 难度模型

MVP 使用 1 至 5 级：

1. 概念识记与直接计算。
2. 单知识点常规应用。
3. 两个左右知识点综合或存在典型转化。
4. 多步骤综合、分类讨论或较强建模要求。
5. 压轴、开放探究或高强度综合。

难度需要同时保存模型预测、教师标注、样本统计和置信度，后期再根据真实作答数据校准。

## 许可证状态

- `unknown`
- `private_use_only`
- `research_only`
- `commercial_granted`
- `question_content_user_declared_usable`：用户声明仅题目内容可使用；PDF 整体、版式、讲义文字和原解析不得复用。此状态默认只能进入私有导入区，完成题源归因、公式校正、独立验算和教师审核后才能发布。
- `public_permissive`
- `expired_or_revoked`

许可证状态必须先于内容可见性判断，`unknown` 不能发布到公共商业题库。
