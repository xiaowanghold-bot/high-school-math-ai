# PDF 结构化题目校对台 v1

## 目标

把教师已经确认的 PDF 题目边界转换为逐题可编辑的结构化草稿，并在不绕过任何质量门禁的前提下送入私人题库审核流程。

稳定流程为：

`逐页分析 → 边界确认 → 内容结构化 → 公式确认 → 私人题库 → 教材映射 → 独立数学核验 → 教师审核`

## 模块边界

`PdfImportStudio` 负责：

- 只从 `confirmed` 边界生成结构化草稿；
- 分离题干与可识别选项，并隔离来源答案、分析和详解段；
- 保存题干正文、LaTeX、选项、答案草稿、自有解析、难度、公式状态与图片页引用；
- 保留完整原始连续内容和页码，保证校对可追溯；
- 防止重复提议覆盖教师修改；
- 记录草稿与题库题目的确定性关联。

`QuestionBank` 继续负责正式题目、配图、修订、教材映射、数学核验与发布门禁。HTTP 路由只编排两个深模块，不直接写数据库。

## 安全门

- 未确认边界不能生成结构化草稿。
- 题型仍为“待判断”或公式未标记“已核对”时，草稿不能确认。
- 选择题至少需要两个不重复编号的选项。
- 图片引用页必须属于当前 PDF 的有效页码；引用只表示归属，题库审核时仍需裁剪或替换。
- 原答案和原解析不会被自动当成已核验内容；解析默认要求独立编写。
- 只有教师确认的结构化草稿可以送入题库。
- 入库题始终为 `private / pending / needs_math_review`，不能自动公开或用于正式组卷。
- 已入库草稿在加工区锁定，后续修订统一进入题库版本历史。

## 数据对象

`import_structured_question_drafts` 保存：

- 文件、边界候选、顺序和起止页；
- 不可变来源连续内容；
- 题型、题干正文和 LaTeX；
- 选项、答案草稿和自有解析步骤；
- 难度与公式校对状态；
- 图片页引用、教师备注和自动警告；
- `draft / confirmed / imported` 状态与关联题库题号。

## 图片裁剪能力

当前版本已完成题目级矩形框选与裁剪：

- 浏览器基于实际显示页面记录 `x / y / width / height` 相对坐标，调整窗口或预览宽度不会导致裁剪漂移；
- 后端按 1800 像素页宽重新渲染来源 PDF，再依据相对坐标生成高清 PNG；
- 裁剪页必须位于该题已确认的起止页内，区域不能越界或小于页面宽高的 1%；
- 每题最多保存 8 张裁剪图，可分别标记为题干图或解析图；
- 加工区保留裁剪坐标、来源页、像素尺寸和教师说明；
- 草稿进入题库时，裁剪图逐张复制到题库媒体目录并建立图片审计记录；失败重试只复制尚未关联的图片，不会重复入库；
- 已入库草稿的裁剪图在加工区锁定，后续替换、排序和删除统一由题库媒体模块处理。

无法立即裁剪、需要重绘或跨页的图片仍可保留“来源页备注”，但备注本身不会生成题库图片。

## 接口

- `GET /api/v1/imports/files/{file_id}/structured-drafts`
- `POST /api/v1/imports/files/{file_id}/structured-drafts/propose`
- `PATCH /api/v1/imports/files/{file_id}/structured-drafts/{draft_id}`
- `POST /api/v1/imports/files/{file_id}/structured-drafts/{draft_id}/media-crops`
- `GET /api/v1/imports/media-crops/{crop_id}/file`
- `DELETE /api/v1/imports/files/{file_id}/structured-drafts/{draft_id}/media-crops/{crop_id}`
- `POST /api/v1/imports/files/{file_id}/structured-drafts/{draft_id}/import`
