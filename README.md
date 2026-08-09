# 高中数学 AI 备课工作台

教师优先的人教 A 版高中数学备课、搜题、解题、组卷与导出工具。

## 当前可运行切片

- Next.js 教师工作台和教材目录页。
- FastAPI 健康检查。
- 从知识点树 CSV 读取并返回教材目录。
- 30 题试点批次幂等导入与 SQLite 私有题库。
- 关键词/章节/难度/质量状态组合检索。
- 教师审核留痕与不可绕过的商业发布门禁。
- 题库管理和审核工作台。
- AI 教案生成器 MVP：按教材节点、课型、课时和学情生成可编辑初稿，自动关联独立验证通过的题目，并保存教案版本。
- 教案生成支持无 Key 的本地预览适配器，以及 OpenAI Responses API 结构化输出适配器；模型输出始终保留教师审核提示。
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

### 可选：启用真实 AI 教案生成

复制 `.env.example` 为 `.env`，填写 `MATH_AI_OPENAI_API_KEY`。默认使用 `gpt-5.6-terra`；不填写时自动使用本地模板，教案生成、编辑和版本保存仍可完整运行。

导出文件默认写入本地 `output/docx` 和 `output/pdf`（已从 Git 忽略）。Linux 部署若未自动发现 Noto Sans CJK，可配置 `MATH_AI_CJK_FONT_REGULAR` 与 `MATH_AI_CJK_FONT_BOLD`。

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
