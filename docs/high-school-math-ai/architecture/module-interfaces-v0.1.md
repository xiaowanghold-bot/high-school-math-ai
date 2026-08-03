# 核心深模块接口 v0.1

## 1. 模块划分原则

首版是一个模块化单体。模块之间只能通过明确接口协作，不能跨模块直接修改数据表。模块内部可以拥有私有实现和内部接缝，但不把测试细节暴露给调用者。

## 2. QuestionBank 模块

### Interface

```text
import_batch(source_document_id, policy) -> ImportBatch
get_question(question_id, revision?) -> QuestionView
save_revision(question_id, draft, actor) -> QuestionRevision
transition(question_id, action, evidence, actor) -> QuestionState
```

### 不变量

- 发布过的版本不可修改。
- `publish` 必须同时通过权利门禁、验证门禁和教师确认。
- 私人题不能因修改标签而变为公共题。

### 错误模式

- `InvalidTransition`
- `MissingSourceEvidence`
- `StaleRevision`
- `PublicationGateRejected`

## 3. RightsGate 模块

### Interface

```text
decide(content_id, action, actor_context) -> RightsDecision
record_grant(source_id, grant) -> LicenseGrant
revoke(grant_id, reason) -> AffectedContent
```

`action` 只允许：`view`、`adapt`、`train`、`export`、`publish`。

### 不变量

- 没有明确决定时默认拒绝。
- 题目内容可用不等于 PDF 整体可用。
- 撤销权利后必须返回所有受影响内容，交由下架流程处理。

## 4. Search 模块

### Interface

```text
search(query, search_context) -> SearchPage
similar(question_id, search_context) -> SearchPage
explain(result_id) -> RankingExplanation
```

### 实现隐藏内容

- 查询意图解析。
- 权限和权利过滤。
- 关键词、公式、向量和标签召回。
- 重排、去重和多样性。

### 性能

- 普通搜索 P95 小于 2 秒。
- 无模型降级时仍返回关键词和标签结果。

## 5. AIOrchestrator 模块

### Interface

```text
run(task_spec, content_context, policy) -> ModelTask
resume(task_id) -> ModelTask
cancel(task_id) -> ModelTask
```

### 任务类型

- `lesson_plan_generate`
- `question_generate`
- `question_variant`
- `solution_generate`
- `query_parse`
- `content_review`

### 不变量

- 每次运行记录模型、提示版本、引用内容、费用和输出。
- 模型输出只能成为草稿，不能自行发布。
- 私人内容只能发送给符合当前隐私策略的模型适配器。

### 适配器

- 生产模型适配器。
- 本地/录制响应测试适配器。

## 6. MathVerifier 模块

### Interface

```text
verify(question_revision, solution?) -> VerificationReport
capabilities(question_type) -> VerificationCapability
```

### 验证报告

- `passed`
- `failed`
- `inconclusive`
- 验证方法和证据
- 正确选项唯一性
- 答案与解析一致性
- 风险级别

### 首版能力顺序

1. 数值型单选题。
2. 集合、不等式和函数基础题。
3. 方程和参数抽样题。
4. 概率有限状态枚举。
5. 解析几何数值/符号交叉验证。

## 7. CurriculumCatalog 模块

### Interface

```text
get_tree(curriculum_version, scope?) -> CurriculumTree
get_node(node_id) -> CurriculumNodeView
map_question(question_revision) -> MappingCandidates
```

目录版本不可被业务代码写死；同一题可以映射多个知识点，但必须有一个主要知识点。

## 8. LessonWorkspace 模块

### Interface

```text
create(spec, actor) -> LessonPlan
apply_commands(plan_id, base_revision, commands) -> LessonPlanRevision
snapshot(plan_id) -> LessonPlanSnapshot
```

命令包括编辑、锁定、解锁、AI重写、插入题目、替换题目和重排内容块。锁定块不能被全篇生成覆盖。

## 9. PaperWorkspace 模块

### Interface

```text
create(spec, actor) -> ExamPaper
apply_commands(paper_id, base_revision, commands) -> ExamPaperRevision
analyze(paper_revision) -> PaperAnalysis
```

分析输出知识点覆盖、题型、分值、难度和重复度。历史试卷始终引用题目版本快照。

## 10. DocumentRenderer 模块

### Interface

```text
render(document_snapshot, template, formats) -> ExportJob
inspect(export_job_id) -> ExportResult
```

### 适配器

- DOCX 渲染适配器。
- PDF 渲染适配器。
- 测试用结构快照适配器。

导出时写入 AI 内容标识、来源附注和文档元数据，不允许学生卷泄漏答案。

## 11. UsageBilling 模块

### Interface

```text
authorize(user_id, capability, estimate) -> UsageReservation
commit(reservation_id, actual_usage) -> LedgerEntry
release(reservation_id) -> LedgerEntry
```

模型任务必须先预留额度，失败或取消后释放，防止并发任务透支。

## 12. 测试策略

- 模块接口就是主要测试面。
- PostgreSQL 使用隔离测试库或本地替代实现。
- 外部模型、支付和对象存储通过测试适配器替换。
- 测试只断言接口可观察结果，不依赖模块内部函数和表结构。
- 端到端测试覆盖搜题、生成教案、组卷、导出和发布五条主流程。
