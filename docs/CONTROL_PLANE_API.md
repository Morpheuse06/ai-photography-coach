# 控制面与反馈 API 契约

最后更新：2026-08-15  
契约版本：`control-plane-v1-draft`  
状态：Schema 与 Python Protocol 已实现；HTTP 路由和持久化尚未实现

## 1. 文档目的

本文定义 AI 摄影教练未来公网版本的访问控制、匿名反馈、运行记录和管理 API。
管理端前后端、公开网页和现有分析服务都应以此为共同契约。

当前代码只提供：

- `src/photography_coach/schemas/interaction.py`：公开交互契约
- `src/photography_coach/schemas/admin.py`：管理 API 契约
- `src/photography_coach/ports/control_plane.py`：额度、记录和反馈存储接口
- `AnalysisResponse.interaction`：向后兼容的可选扩展点

本文中的路由尚未注册。数据库、鉴权和事务完成前，不能创建返回假成功的占位接口。

## 2. 共同规则

### 2.1 Content-Type

- 分析上传继续使用 `multipart/form-data`。
- 评价、反馈和管理请求使用 `application/json`。
- CSV 导出接口返回 `text/csv; charset=utf-8`。

### 2.2 时间、标识和分页

- 所有时间使用带时区的 ISO 8601 UTC 字符串。
- `analysis_id`、邀请码 ID、反馈 ID、审计 ID 使用 UUID。
- 列表接口使用 `page` 和 `page_size`，`page_size` 最大 100。
- 列表响应包含 `items` 和 `PageInfo`。

### 2.3 统一错误结构

继续使用现有结构：

```json
{
  "error": {
    "code": "access_quota_exhausted",
    "message": "This access code has no remaining uses."
  }
}
```

公开错误不能泄露邀请码是否属于某个批次、管理员账号是否存在、数据库结构或上游
Provider 的原始响应。

### 2.4 敏感值

以下值禁止写入应用日志、审计详情或普通数据库列：

- 原始邀请码
- `feedback_token`
- `Idempotency-Key`
- 管理员密码和明文 Bearer Token
- 模型 API Key
- 原始图片和 Base64 data URL
- 原始 IP

邀请码、反馈凭据和幂等键进入服务后应立即哈希。管理员密码使用专用密码哈希算法，
不能直接使用普通 SHA-256。

## 3. 分析接口扩展

### `POST /api/v2/analyze`

原有 multipart 字段不变：

| 字段 | 类型 | 必需 | 说明 |
|---|---|---:|---|
| `photo` | 文件 | 是 | JPEG、PNG 或 WebP，最大 10 MiB |
| `intent` | 字符串 | 否 | 最大 1000 字符 |

新增请求 Header：

| Header | 模式 | 说明 |
|---|---|---|
| `X-Access-Code` | `open` 时可选，`code_required` 时必需 | 原始邀请码，只在请求内存中短暂存在 |
| `Idempotency-Key` | 必需 | 客户端为一次用户操作生成的随机值，重试时复用 |

控制面启用后，成功响应必须填充 `interaction`：

```json
{
  "report": {},
  "metadata": {},
  "interaction": {
    "analysis_id": "8d81ac6b-c3a5-4dad-912d-7635725a459f",
    "feedback_token": "7B1DgR5NwP2kL9xQa4Vm8Yc3Hs6Jt0UfEeZiKpAo",
    "access": {
      "mode": "code_required",
      "remaining_uses": 4
    }
  }
}
```

在当前未接入控制面的版本中，`interaction` 为 Python 可选字段，并在值为 `None` 时
不序列化，因此现有 V1/V2 客户端保持兼容。

### 分析新增错误

| HTTP | code | 场景 |
|---:|---|---|
| 401 | `access_code_required` | 当前模式要求邀请码但请求没有提供 |
| 403 | `access_denied` | 邀请码无效、过期或已撤销；公开响应不区分原因 |
| 403 | `analysis_closed` | 管理员关闭了新分析 |
| 409 | `idempotency_conflict` | 同一幂等键对应了不同请求 |
| 429 | `access_quota_exhausted` | 邀请码没有可用或可预占次数 |
| 429 | `request_rate_limited` | 单来源频率超过配置 |
| 429 | `global_quota_exhausted` | 全站当日预算或次数达到上限 |
| 429 | `concurrency_limit_reached` | 当前同时分析数量达到上限 |
| 503 | `control_plane_unavailable` | 额度数据库不可用，系统应失败关闭而不是放行 |

## 4. 次数事务

每次分析必须遵守以下顺序：

```text
读取并验证图片
→ 创建 analysis_id
→ reserve(analysis_id, access_code, idempotency_key)
→ 写入 analysis_runs=running
→ 执行 RAG 和模型
→ 成功：记录响应，然后 commit reservation
→ 失败：记录错误，然后 release reservation
```

要求：

- 非法图片和无效 HTTP 请求不预占次数。
- 模型超时、限流、异常输出、上游不可用和应用错误释放预占。
- 只有成功返回完整报告时正式消费一次。
- 预占、确认和释放必须幂等。
- 同一邀请码最后一次额度只能被一个并发事务预占。
- 预占记录必须有过期时间，后台任务可释放进程崩溃遗留的预占。
- 分析记录失败不能导致已经成功的模型请求被重复执行。
- 数据库实现必须使用事务或条件更新，不能先读取余额再在另一个语句中随意扣减。

## 5. 匿名模块评价

可评价的 `target`：

```text
composition
lighting
color
subject_expression
visual_storytelling
priority_actions
shooting_exercise
overall
```

### `PUT /api/v2/analyses/{analysis_id}/ratings/{target}`

Header：

```http
Authorization: Bearer <feedback_token>
```

请求模型：`RatingUpsertRequest`

```json
{
  "vote": "down",
  "reason_codes": ["generic_advice", "not_grounded"],
  "comment": "建议没有对应到画面中可以指出的位置。"
}
```

规则：

- 一个 feedback token 对一个 analysis 和 target 只能有一条当前评价。
- 重复 PUT 替换原评价，不增加重复计数。
- `reason_codes` 最多 5 个且不能重复。
- `comment` 可选，最大 500 字符。
- token 必须同时匹配 `analysis_id`，不能评价其他报告。

成功：`200 RatingReceipt`。

### `DELETE /api/v2/analyses/{analysis_id}/ratings/{target}`

使用相同 Bearer token。无论原评价是否存在都返回 `204`，避免泄露内部状态。

### 评价错误

| HTTP | code | 场景 |
|---:|---|---|
| 403 | `feedback_forbidden` | token 无效、过期或不属于该分析 |
| 404 | `analysis_not_found` | 分析记录已被清理或不存在 |
| 422 | `invalid_request` | target、vote、原因或文字不符合 Schema |
| 429 | `feedback_rate_limited` | 反馈提交过于频繁 |

## 6. 网页底部问题反馈

### `POST /api/v2/problem-reports`

请求模型：`ProblemReportCreate`

```json
{
  "analysis_id": "可选 UUID",
  "category": "report_quality",
  "message": "光影建议没有考虑画面中主体已经处于剪影状态。",
  "include_runtime_metadata": true
}
```

规则：

- message 长度 10～2000。
- 不收集姓名、邮箱和手机号。
- `include_runtime_metadata=false` 时不能附带分析运行信息。
- 为 true 时，只能关联服务端已经保存的非秘密元数据；不能信任客户端自行上传的
  模型、Token、IP 或诊断字段。
- 反馈文字按不可信文本处理，管理页面必须转义显示。

成功：`202 ProblemReportReceipt`。

## 7. 管理鉴权

所有 `/api/admin/v1/*` 接口除创建会话外都要求：

```http
Authorization: Bearer <admin-access-token>
```

### `POST /api/admin/v1/sessions`

- 请求：`AdminSessionCreate`
- 响应：`201 AdminSessionCreated`
- 登录失败统一返回 `401 admin_authentication_failed`
- 不能提示“用户名存在但密码错误”
- 必须对失败登录限流
- Token 应短期有效、可撤销，数据库只保存哈希或会话标识

### `DELETE /api/admin/v1/sessions/current`

撤销当前会话，成功返回 `204`。

管理端 V1 只支持一个 owner 角色，但数据库应保留稳定的 `admin_subject`，便于未来增加
多个管理员并保留审计归属。

## 8. 管理 API 路由

### 仪表盘

| 方法与路径 | 请求/响应 |
|---|---|
| `GET /api/admin/v1/overview?from=&to=&bucket=day` | `OverviewResponse` |

时间范围最大 366 天。`series` 用于趋势图，`totals` 用于数字卡片。

### 访问策略

| 方法与路径 | 请求/响应 |
|---|---|
| `GET /api/admin/v1/access-policy` | `AccessPolicyView` |
| `PATCH /api/admin/v1/access-policy` | `AccessPolicyUpdate` → `AccessPolicyView` |

支持 `open`、`code_required`、`closed`。修改必须写入审计事件。

### 邀请码

| 方法与路径 | 请求/响应 |
|---|---|
| `POST /api/admin/v1/access-code-batches` | `AccessCodeBatchCreate` → `201 AccessCodeBatchCreated` |
| `GET /api/admin/v1/access-codes` | `AccessCodePage` |
| `GET /api/admin/v1/access-codes/{code_id}` | `AccessCodeRecord` |
| `PATCH /api/admin/v1/access-codes/{code_id}` | `AccessCodeUpdate` → `AccessCodeRecord` |
| `POST /api/admin/v1/access-codes/{code_id}/grants` | `AccessCodeGrant` → `AccessCodeRecord` |
| `POST /api/admin/v1/access-codes/{code_id}/revoke` | `AccessCodeRevoke` → `AccessCodeRecord` |
| `GET /api/admin/v1/access-codes/{code_id}/usage-events` | `AccessCodeUsageEventPage` |

批量创建响应是唯一允许返回完整邀请码的接口。之后所有查询只返回 prefix。

### 分析记录

| 方法与路径 | 请求/响应 |
|---|---|
| `GET /api/admin/v1/analysis-runs` | `AnalysisRunPage` |
| `GET /api/admin/v1/analysis-runs/{analysis_id}` | `AnalysisRunDetail` |

建议过滤参数：status、provider、model、prompt_version、access_code_prefix、error_code、
started_from、started_to、has_down_vote。

### 模块评价

| 方法与路径 | 请求/响应 |
|---|---|
| `GET /api/admin/v1/ratings/summary` | `RatingSummary` |
| `GET /api/admin/v1/ratings` | `RatingPage` |

建议过滤参数：target、vote、reason_code、model、prompt_version、from、to。

### 问题反馈

| 方法与路径 | 请求/响应 |
|---|---|
| `GET /api/admin/v1/problem-reports` | `ProblemReportPage` |
| `GET /api/admin/v1/problem-reports/{problem_report_id}` | `ProblemReportRecord` |
| `PATCH /api/admin/v1/problem-reports/{problem_report_id}` | `ProblemReportUpdate` → `ProblemReportRecord` |

管理端可修改状态、优先级、标签和管理员备注，不能修改用户原始 message。

### 系统状态、版本和审计

| 方法与路径 | 请求/响应 |
|---|---|
| `GET /api/admin/v1/system/status` | `SystemStatus` |
| `GET /api/admin/v1/system/versions` | `SystemVersions` |
| `GET /api/admin/v1/audit-events` | `AuditEventPage` |

系统接口只读显示模型、Prompt、知识库和索引状态，禁止返回密钥和完整 Base URL
凭据。控制台 V1 不支持在线编辑 Prompt 或 API Key。

### 导出

以下接口可以后续增加 CSV 流式响应：

```text
GET /api/admin/v1/exports/analysis-runs.csv
GET /api/admin/v1/exports/ratings.csv
GET /api/admin/v1/exports/problem-reports.csv
```

导出属于敏感管理操作，必须写审计记录并再次应用当前管理员权限。

## 9. 数据保留

已确认的默认政策：

| 数据 | 保留时间 | 说明 |
|---|---:|---|
| 原始照片/Base64 | 0 天 | 永不保存 |
| 拍摄意图 | 30 天 | 可能包含敏感文字 |
| 完整结构化报告 | 30 天 | 用于关联质量反馈 |
| 分析运行指标 | 180 天 | 模型、版本、耗时、Token、错误 |
| 原始 IP | 0 天 | 永不保存 |
| 邀请码哈希和账本 | 码有效期及审计需要 | 原始码只显示一次 |
| 点赞点踩和问题反馈 | 管理员删除或项目政策期限 | 不包含联系方式 |
| 管理审计 | 至少 180 天 | 只追加，不允许普通修改 |

频率限制如需识别来源，可使用按日轮换盐值生成的短期来源哈希；它不能跨长期追踪，
也不能和分析报告一起形成用户画像。

## 10. 对应代码契约

| HTTP 领域 | Pydantic/Protocol |
|---|---|
| 分析交互扩展 | `AnalysisInteraction`, `AnalysisAccess` |
| 匿名评价 | `RatingUpsertRequest`, `RatingReceipt`, `RatingTarget` |
| 问题反馈 | `ProblemReportCreate`, `ProblemReportReceipt` |
| 次数事务 | `UsageAuthorizer`, `UsageReservation` |
| 分析生命周期 | `AnalysisRecorder`, `AnalysisRunStart`, `AnalysisRunFailure` |
| 反馈存储 | `FeedbackRepository` |
| 管理 API | `src/photography_coach/schemas/admin.py` 中的请求、详情、分页和仪表盘模型 |

这些契约是稳定边界，不等于路由已经可调用。实现状态必须以 OpenAPI 实际注册路由和
测试为准。
