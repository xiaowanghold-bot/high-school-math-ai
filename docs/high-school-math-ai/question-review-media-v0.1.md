# 题目修订与配图审核 v0.1

## 目标

让教师在同一个审核工作区内完成题目正文修订和配图管理，同时保留来源版本、数学验证状态和审核证据。当前结构直接兼容后续立体几何模块的多图题。

## 教师工作流

1. 在“内容预览”中检查题干、选项、答案、解析和配图。
2. 切换到“编辑与配图”，自由修改题干正文、LaTeX、选项、答案、解析方法和逐步解析。
3. 在题干图或解析图区域插入图片，并补充图片说明和无障碍描述。
4. 保存时创建新修订，来源原文不被覆盖，审核状态回到“待教师审核”。
5. 数学内容或题干图变化时自动退回“待数学验算”；只调整解析文字或解析图时保留原验证状态。

## 图片规则

- 支持 PNG、JPEG、WebP，不允许仅依赖扩展名伪装文件类型。
- 单张最大 8 MB，单题最多 8 张，像素总量不超过 2500 万。
- 图片按“题干 / 解析”分组，支持替换、组内前后排序、说明编辑和删除。
- 列表页不渲染图片，只在题目详情中使用固定 4:3 容器和 `object-fit: contain`，因此超长图、竖图和多图不会破坏题目列表或挤出页面。
- 图片文件写入本地运行目录，元数据和审计事件写入 SQLite；以后迁移对象存储时页面接口无需变化。

## API

```text
PATCH  /api/v1/questions/{question_id}
POST   /api/v1/questions/{question_id}/images
PATCH  /api/v1/questions/{question_id}/images/{image_id}
PUT    /api/v1/questions/{question_id}/images/{image_id}/file
PUT    /api/v1/questions/{question_id}/images/order
DELETE /api/v1/questions/{question_id}/images/{image_id}
GET    /api/v1/questions/{question_id}/images/{image_id}/content
```

## 立体几何扩展边界

当前图片对象已经具备位置、排序、尺寸、说明和无障碍描述。后续立体几何模块可在此基础上增加图形标注、局部放大和作图工具，但不需要修改题目修订、审核或发布门禁的核心流程。
