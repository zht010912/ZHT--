# API 说明

所有响应均为 UTF-8 JSON。错误统一为：

```json
{"error":{"code":"validation_error","message":"输入校验失败","details":[]}}
```

## 1. 新建会议

`POST /api/meetings`

```json
{
  "title": "发布评审会",
  "meeting_type": "评审会",
  "meeting_date": "2026-08-14",
  "content": "会议决定……"
}
```

约束：标题 1–200 字符；记录 1–20,000 字符；日期为 `YYYY-MM-DD`。

## 2. 查询会议

`GET /api/meetings?q=&meeting_type=&status=&owner=&due_before=`

- `q`：标题或原文关键词。
- `meeting_type`：精确匹配会议类型。
- `status`：`pending` 或 `completed`，筛选包含该状态行动项的会议。
- `owner`：负责人。
- `due_before`：不晚于指定日期。

`GET /api/meetings/{id}` 返回会议、正式 `actions` 和 `analysis_runs` 审计记录。

## 3. 手工新增行动项

`POST /api/meetings/{id}/actions`

```json
{
  "task": "完成接口联调",
  "owner": "王芳",
  "due_date": "2026-08-21",
  "status": "pending",
  "source_quotes": ["王芳负责接口联调"]
}
```

同一会议中任务、负责人和截止日期相同的重复提交不会重复创建，响应的 `created` 为 `false`。

## 4. 更新行动项

`PATCH /api/actions/{id}`

```json
{
  "task": "完成接口联调并提交报告",
  "owner": "王芳",
  "due_date": "2026-08-21",
  "status": "completed",
  "expected_version": 1
}
```

除 `expected_version` 必填外，其余字段按需更新。页面“编辑”可修改任务、负责人和日期，勾选框更新状态；版本过期返回 HTTP 409，防止并发修改被静默覆盖。

## 5. 运行 AI 分析

`POST /api/meetings/{id}/analyze`

```json
{"prompt_version":"optimized"}
```

`prompt_version` 支持 `baseline` 与 `optimized`。成功仅保存 AI 建议，不创建正式行动项；失败会保存脱敏错误记录。

建议结构：

```json
{
  "summary": "……",
  "decisions": [{"decision":"……","source_quote":"逐字原文"}],
  "action_items": [{
    "task": "完成接口联调",
    "owner": "王芳",
    "due_date_text": "下周五",
    "due_date": "2026-08-21",
    "source_quotes": ["逐字原文"],
    "confidence": 0.95
  }]
}
```

## 6. 人工审核

`POST /api/analysis-runs/{id}/review`

直接确认原建议：

```json
{"decision":"confirm","note":"已核对原文"}
```

修改后确认：

```json
{"decision":"edit","final_payload":{"summary":"……","decisions":[],"action_items":[]},"note":"人工修正负责人"}
```

拒绝：

```json
{"decision":"reject","note":"来源不足"}
```

仅 `confirm`/`edit` 会事务性创建正式行动项；同一个分析运行不能重复审核。

## 7. 健康检查

`GET /api/health`

只返回服务、数据库、模型名和 `api_key_configured: true/false`，绝不返回密钥本身。
