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
- 集合模块 10 题公式重建、KaTeX 数学排版和独立规则验证。
- 概率模块首批 4 道解答题完成公式重建、分布列校正和独立状态枚举验证。
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
