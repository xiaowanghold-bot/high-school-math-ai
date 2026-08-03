# AI 教案生成器 MVP v1

日期：2026-08-03

## 已实现范围

从 `/lesson-plans` 可以完成一条可运行的教师工作流：

1. 从人教 A 版必修第一册课程树选择“节”或“知识点”。
2. 设置课型、课时长度、班级学情、本课侧重点和推荐例题数量。
3. 自动检索相同章节中独立数学验证通过的题目。
4. 生成包含教学目标、重难点、教学流程、评价证据、分层作业、板书和教师备注的教案初稿。
5. 教师逐项编辑，并以新版本保存到本地 SQLite。

没有模型密钥时，系统使用确定性本地模板，确保产品闭环可开发、可测试。配置密钥后，`auto` 模式会切换到 OpenAI 适配器。

## 模块接口与接缝

`LessonPlanStudio` 是对路由和测试公开的深模块，调用者只需理解三个主要操作：

```text
create(generation_request) -> LessonPlanView
list(limit) -> LessonPlanList
get(plan_id) -> LessonPlanView
update(plan_id, update_command) -> LessonPlanView
```

模块内部隐藏：

- 教材节点向章节、节和知识点上下文的解析。
- 课程树名称与题库展示名称的归一化匹配。
- 只召回 `verification_status=passed` 题目的检索规则。
- 教学流程课时总和校验。
- SQLite 表结构、JSON 快照和版本号更新。
- 模型供应商请求和结构化输出解析。

外部模型属于真实外部依赖，因此在内部接缝上定义 `LessonPlanDraftProvider`。目前已有两个适配器：

- `TemplateLessonPlanProvider`：本地开发与测试使用，不产生费用。
- `OpenAIResponsesLessonPlanProvider`：生产模型调用，使用严格 JSON Schema。

## OpenAI 接入决策

- 使用 Responses API，不将页面直接绑定到模型 SDK。
- 使用 `text.format` 的严格 `json_schema`，避免自由文本再解析。
- 默认模型为 `gpt-5.6-terra`，优先平衡教案质量、延迟和商业成本。
- 默认推理强度为 `low`，后续应以真实教师评分、延迟和单份教案成本做 A/B 评估。
- 请求设置 `store=false`，并为教师账号生成不可逆的稳定 `safety_identifier`。
- API Key 只从服务端环境变量读取，不进入浏览器代码和 Git 仓库。

官方实现依据：

- [OpenAI 模型选择与 GPT-5.6 指南](https://developers.openai.com/api/docs/guides/latest-model)
- [Responses API 迁移与基础调用](https://developers.openai.com/api/docs/guides/migrate-to-responses)
- [Structured Outputs 与 text.format](https://developers.openai.com/api/docs/guides/structured-outputs)

## HTTP 接口

```text
GET   /api/v1/lesson-plans
POST  /api/v1/lesson-plans/generate
GET   /api/v1/lesson-plans/{lesson_plan_id}
PATCH /api/v1/lesson-plans/{lesson_plan_id}
```

生成结果永远是 `draft`。本版本没有公开发布接口，避免模型结果绕过教师审核。

## 配置

```dotenv
MATH_AI_LESSON_PLAN_PROVIDER=auto
MATH_AI_OPENAI_API_KEY=
MATH_AI_OPENAI_MODEL=gpt-5.6-terra
MATH_AI_OPENAI_REASONING_EFFORT=low
```

`auto` 的行为：有 Key 时使用 OpenAI；无 Key 时使用本地模板。也可显式设置 `local` 或 `openai`。

## 验证证据

- 自动测试覆盖教材上下文解析、题库召回、45 分钟流程总和、草稿存储、版本更新和 HTTP 端点。
- API 全套测试 19 项通过，其中包含 Responses API 严格结构化输出请求的适配器测试。
- Web TypeScript 类型检查和 Next.js 生产构建通过。
- 浏览器端实际完成“生成函数性质教案 → 自动关联 3 道已验证题 → 修改标题 → 保存为 v2”。
- 页面控制台无 warning 或 error。
- 浏览器验收发现并修复了中等桌面宽度下标题输入框造成的横向溢出。

## 下一步

1. 增加教案块级锁定和局部 AI 重写，避免再次生成覆盖教师已确认内容。
2. 增加 DOCX/PDF 导出和教师模板。
3. 建立 20–50 份教师评分集，比较不同模型、推理强度和提示版本。
4. 记录模型 token、延迟和单份成本，为商业套餐设计提供依据。
