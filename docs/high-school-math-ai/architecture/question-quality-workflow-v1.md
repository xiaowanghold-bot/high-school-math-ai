# 题目质量工作流 v1

## 目标

`QuestionQualityWorkflow` 负责把“题目草稿”推进为可检索、可组卷的可信题目。它集中封装教材映射建议与数学核验证据，不让页面、导入器或大模型直接修改审核事实。

## 对外接口

- `inspect(question_id)`：读取当前教材映射、最多 5 个知识点建议和核验能力。
- `apply_curriculum(question_id, command)`：校验知识点属于课程树的叶子节点，再保存教师确认的映射和审计信息。
- `record_verification(question_id, command)`：保存独立答案、推导步骤、核验结论和核验人，返回最新质量工作区。

HTTP 路由分别为：

- `GET /api/v1/questions/{question_id}/quality`
- `POST /api/v1/questions/{question_id}/quality/curriculum`
- `POST /api/v1/questions/{question_id}/quality/verification`

## 不变量

1. 自动推荐不能直接改变教材映射，教师必须显式应用具体知识点。
2. 不能把章节或小节当成知识点保存。
3. 任意来源题不能伪装成规则自动验算；无 `verification_spec` 时必须提交教师独立证据。
4. “通过”至少要求独立答案、一步推导证据和独立核验声明。
5. 独立答案与当前答案不一致时，即使请求结论为“通过”，系统仍强制标记为 `source_inconsistency_detected`。
6. 数学核验通过不等于可发布；教师内容审核、原创解析、来源归属和商用权利门禁仍独立生效。
7. 修改数学内容后，已有数学核验自动失效。

## 依赖边界

工作流只依赖两个可替换接口：

- `QuestionBank`：题目、修订、审核和门禁事实的唯一写入者。
- curriculum catalog：提供课程树与知识点查询；当前实现读取经审核的人教 A 版 CSV。

推荐算法是可替换实现。未来可以接入向量检索或大模型重排，但输出仍只是建议，不能绕过教师确认。

## 后续扩展

- 把人工课程树从必修第一册扩展到人教 A 版全册。
- 为常见高中数学题型补充可执行 `verification_spec`，将部分人工核验升级为规则核验。
- 支持从完整教材目录中手动搜索并选择知识点，覆盖自动推荐无结果的情况。
- 记录建议接受率、改判率和核验退回原因，用于优化推荐，不用于自动放宽发布门禁。
