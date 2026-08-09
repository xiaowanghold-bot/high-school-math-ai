# 高中数学 AI 备课工作台

教师优先的人教 A 版高中数学备课、搜题、解题、组卷与导出工具。

## 当前可运行切片

- Next.js 教师工作台和教材目录页。
- FastAPI 健康检查。
- 从知识点树 CSV 读取并返回教材目录。
- 30 题试点批次幂等导入与 SQLite 私有题库。
- 关键词/章节/难度/质量状态组合检索。
- 教师审核留痕与不可绕过的商业发布门禁。
- 题库管理和审核工作台：教师可直接修订题干、LaTeX、选项、答案与解析，所有人工修改生成新修订并保留来源版本。
- 题目支持最多 8 张受控配图，区分题干图和解析图，可插入、替换、排序、补充说明或删除；图片采用固定容器展示，为立体几何多图题预留结构。
- 题目变式 MVP：只允许独立验证通过且权利记录允许改编的题目作为母题；无 Key 时可生成确定性的错因诊断题，配置大模型后支持数值、难度和情境变式。所有新题保持私有待审核，记录母题、生成方式和教师要求，并继承题干配图到固定图片槽。
- 组卷工作台 MVP：既可从独立验证通过的题库中手工选题，也可按章节、题型数量、目标总分、难度方案和审核策略自动生成可编辑草稿；调整顺序与分值后保存不可变题目/图片快照和试卷版本，支持导出学生卷、答案卷、双向细目表三种 Word/PDF 文件。
- AI 教案生成器 MVP：按教材节点、课型、课时和学情生成可编辑初稿，自动关联独立验证通过的题目，并保存教案版本。
- 教案生成支持无 Key 的本地预览适配器，以及 OpenAI Responses API 结构化输出适配器；模型输出始终保留教师审核提示。
- 教案各内容块支持独立锁定和局部 AI 改写；改写先显示修改前后对比，教师可接受、放弃或在保存前撤销，保存后才进入新版本。
- 教案可导出为教师可继续编辑的 Word 或可直接打印的 PDF；两种格式都包含审核提示、题库联动、页眉页脚和版本化文件名。
- 集合模块 10 题公式重建、KaTeX 数学排版和独立规则验证。
- 概率模块 10 道解答题完成公式重建、分布列校正和独立状态枚举验证；其中 9 道通过，1 道来源解析错误已自动隔离。
- 函数性质模块首批 5 题完成独立验证；4 题通过，1 题因开区间端点条件不足已自动隔离，智能搜题页新增数学模块快捷筛选。
- 高一“不等式、函数和三角函数”长文档已补齐原卷，并按章节、题型和局部题号与 674 题解析版建立来源配对。
- 圆锥曲线、解三角形和立体几何三组资料已补齐“原题 + 解析”完整版本，旧原卷保留审计但退出默认导入队列。
- 来源错误自动隔离与可审计修订建议。

## 本地运行

### Web

```powershell
pnpm install
pnpm dev:web
```

打开 `http://localhost:3000`。

### API

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\apps\api[dev]"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir .\apps\api --reload
```

打开 `http://localhost:8000/docs`。

### 可选：启用真实 AI 教案与题目变式生成

复制 `.env.example` 为 `.env`，填写 `MATH_AI_OPENAI_API_KEY`。默认使用 `gpt-5.6-terra`；不填写时自动使用本地教案模板和错因诊断变式规则，核心生成、编辑和版本保存流程仍可运行。

导出文件默认写入本地 `output/docx` 和 `output/pdf`（已从 Git 忽略）。Linux 部署若未自动发现 Noto Sans CJK，可配置 `MATH_AI_CJK_FONT_REGULAR` 与 `MATH_AI_CJK_FONT_BOLD`。

题目配图默认写入 `data/runtime/question-media`（已从 Git 忽略）。仅接受经过内容校验的 PNG、JPEG 和 WebP，单张不超过 8 MB、像素总量不超过 2500 万。

试卷图片快照默认写入 `data/runtime/exam-paper-assets`（已从 Git 忽略）。它们独立于题库图片保存，确保题库后续换图不会改变已经保存的试卷版本。

### 测试

```powershell
.\.venv\Scripts\python.exe -m pytest .\apps\api\tests
pnpm typecheck:web
pnpm build:web
```

## 项目结构

```text
apps/web     Next.js Web/PWA
apps/api     FastAPI 模块化后端
data         结构化试点数据
docs         PRD、课程、架构、UI与审核文档
scripts      数据审计和导入工具
```
