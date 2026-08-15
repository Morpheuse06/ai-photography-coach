# 管理端 Agent 开发交接

最后更新：2026-08-15  
目标：实现 AI 摄影教练的持久化控制面、管理 API 和管理页面

> 状态：**已完成**（2026-08-15，分支 `codex/control-plane-admin`）。实现与验收结果见
> `docs/CONTROL_PLANE_ACCEPTANCE.md`；契约细节以 `docs/CONTROL_PLANE_API.md` 为准。

## 1. 开始前必须阅读

1. `docs/PROJECT_KNOWLEDGE.md`
2. `docs/CONTROL_PLANE_API.md`
3. `src/photography_coach/schemas/interaction.py`
4. `src/photography_coach/schemas/admin.py`
5. `src/photography_coach/ports/control_plane.py`
6. `src/photography_coach/schemas/analysis.py`
7. `src/photography_coach/services/rag_analysis.py`

接口路径、字段和错误码以 `CONTROL_PLANE_API.md` 为准。若实现发现契约存在无法满足
的矛盾，应先修改契约和测试，不要在前后端各自发明不同字段。

## 2. 已完成的基础

- 公共分析已有 `/api/v1/analyze` 和 `/api/v2/analyze`。
- V2 已完成图片验证、多模态检索规划、Embedding、Chroma、Reranker 和结构化报告。
- `AnalysisResponse` 已加入可选 `interaction` 扩展；未启用控制面时不会序列化。
- 公共评价、问题反馈、邀请码和管理页面需要的数据 Schema 已定义。
- `UsageAuthorizer`、`AnalysisRecorder`、`FeedbackRepository` Protocol 已定义。
- 原有系统不保存上传照片。
- 当前没有 SQLAlchemy、Alembic、管理员鉴权或管理路由。

## 3. 你的实现范围

### 后端

- 加入 SQLite、SQLAlchemy 2.x 和 Alembic。
- 实现并测试三个 Protocol。
- 把额度预占和分析记录接入 V2 分析流程。
- 实现匿名评价和问题反馈公开路由。
- 实现 `/api/admin/v1` 管理 API。
- 实现管理员认证、短期会话、登出和审计。
- 实现保留期清理任务。
- 为未来 PostgreSQL 保持兼容的数据模型和事务写法。

### 管理前端

- 单独的管理入口和登录页。
- 数据总览和趋势。
- 邀请码批量创建、复制一次、列表、追加次数和撤销。
- 分析记录列表与详情。
- 模块点赞点踩统计和明细。
- 问题反馈收件箱和处理状态。
- 系统状态、版本和审计日志。

### 公开前端

- 在控制面启用后发送 `Idempotency-Key` 和可选 `X-Access-Code`。
- 保存本次响应的 `analysis_id` 和 `feedback_token`，不要写入日志。
- 为八个 target 提供点赞点踩和可选原因。
- 页面底部接入问题反馈表单。
- 明确展示剩余次数和邀请码错误。

## 4. 推荐数据库表

### `admin_users`

- `id`
- `username`（唯一）
- `password_hash`
- `is_active`
- `created_at`, `updated_at`, `last_login_at`

管理员密码使用 Argon2id 或框架认可的现代密码哈希。禁止明文和普通 SHA-256。

### `admin_sessions`

- `id`
- `admin_user_id`
- `token_hash`（唯一）
- `expires_at`, `revoked_at`, `created_at`

原始 Bearer Token 只在创建会话时返回一次。

### `access_policy`

单行或版本化配置：

- `mode`
- `per_source_hour_limit`
- `global_daily_limit`
- `concurrent_analysis_limit`
- `updated_by`, `updated_at`

### `access_code_batches`

- `id`
- `label`
- `quantity`
- `uses_per_code`
- `expires_at`
- `created_by`, `created_at`

### `access_codes`

- `id`, `batch_id`
- `code_hash`（唯一）
- `prefix`
- `label`
- `uses_total`, `uses_consumed`, `uses_reserved`
- `status`
- `expires_at`, `revoked_at`
- `created_at`, `updated_at`

原始邀请码使用密码学安全随机数生成。只在批量创建响应中返回一次，数据库不存原文。

### `usage_reservations`

- `id`
- `analysis_id`（唯一）
- `access_code_id`（open 模式可为空）
- `idempotency_hash`（唯一或与访问主体组成唯一约束）
- `status`: reserved/consumed/released
- `expires_at`
- `release_reason`
- `created_at`, `updated_at`

### `access_code_usage_events`

追加式账本：

- `id`, `reservation_id`, `code_id`, `analysis_id`
- `event_type`: reserved/consumed/released/granted/revoked
- `delta`
- `reason`
- `occurred_at`

余额字段用于高效查询，账本用于审计和重建。两者必须在同一事务更新。

### `analysis_runs`

- `analysis_id`
- `api_version`, `status`
- `started_at`, `completed_at`
- 图片媒体类型、宽、高、字节数
- `shooting_intent`（30 天后清空）
- `report_json`（30 天后清空）
- Provider、模型、Prompt 版本
- 知识库、Embedding、Reranker 和命中 Chunk
- 输入、输出、总 Token
- 检索耗时、总耗时
- `error_code`, `sanitized_diagnostic`
- `access_code_id`, `reservation_id`
- `feedback_token_hash`（不要保存原 token）
- `report_retained_until`

禁止加入原始图片、Base64 或 EXIF 列。

### `dimension_ratings`

- `id`
- `analysis_id`
- `target`
- `vote`
- `reason_codes_json` 或关联表
- `comment`
- `created_at`, `updated_at`

唯一约束建议使用 `(analysis_id, target)`。因为每次分析只返回一个 feedback token，
该 token 代表本次匿名评价能力。

### `problem_reports`

- `id`, `analysis_id`（可空）
- `category`, `message`
- `status`, `priority`
- `tags_json`
- `admin_note`
- `created_at`, `updated_at`

### `admin_audit_events`

- `id`
- `admin_subject`
- `action`
- `resource_type`, `resource_id`
- `details_json`（必须过滤秘密）
- `occurred_at`

此表只追加。普通管理 API 不提供更新和删除。

## 5. 最关键的事务

### 5.1 预占次数

在一个数据库事务中：

1. 锁定或条件更新邀请码记录。
2. 验证 active、未过期且 `consumed + reserved < total`。
3. `uses_reserved += 1`。
4. 创建 reservation 和 reserved 账本事件。
5. 提交事务。

SQLite 本地实现可以使用短事务和条件 UPDATE；PostgreSQL 迁移后可使用行锁。不能用
“先 SELECT 看余额，再独立 UPDATE”的非原子写法。

### 5.2 成功确认

在一个事务中：

1. 确认 reservation 仍为 reserved 且 analysis_id 匹配。
2. `uses_reserved -= 1`。
3. `uses_consumed += 1`。
4. reservation 标记 consumed。
5. 写入 consumed 账本事件。

重复确认必须返回同一最终结果，不能再次扣次数。

### 5.3 失败释放

在一个事务中把 reserved 改为 released，并把 `uses_reserved` 减一。重复释放无副作用。
后台需要定期释放已经过期的 reserved 记录，以处理进程崩溃。

### 5.4 分析与额度的协调

数据库事务不能覆盖几分钟的外部模型调用。推荐顺序：

```text
短事务预占
→ 提交
→ 外部模型调用
→ 短事务记录成功并确认消费
```

如果“报告已生成但数据库确认失败”，不能立刻重复调用模型。应保留 analysis_id 和
幂等记录，通过恢复任务完成确认或明确标记需要人工处理。

## 6. 接入现有分析流程的位置

不要把 SQL 写进 `api/routes.py`。建议增加一个控制面编排服务，包围现有
`RagAnalysisService`：

```text
路由完成图片验证
→ ControlPlaneAnalysisService 创建 analysis_id
→ UsageAuthorizer.reserve
→ AnalysisRecorder.start
→ 调用 RagAnalysisService.analyze
→ AnalysisRecorder.succeed / fail
→ UsageAuthorizer.commit / release
→ 生成 feedback token
→ 填充 AnalysisResponse.interaction
```

依赖装配放在 `dependencies.py`，数据库生命周期放在 FastAPI lifespan。测试使用内存
Fake 实现覆盖依赖，不能连接真实数据库或模型服务。

## 7. 安全红线

- 永不保存上传图片和 Base64。
- 永不把原始邀请码、反馈 token、幂等键、管理员密码或 API Key 写入日志。
- 邀请码生成使用 `secrets`，不能使用 `random`。
- 管理员密码使用专用慢哈希。
- 所有管理路由默认拒绝，不能因认证服务异常而放行。
- `open` 模式仍应用全站限额、并发限制和来源限流。
- 来源限流不保存原始 IP；使用短期轮换盐哈希，并按保留期删除。
- 用户反馈是未可信文本，React 正常文本渲染，不使用 `dangerouslySetInnerHTML`。
- CSV 导出防止公式注入：以 `=`, `+`, `-`, `@` 开头的用户单元格必须转义。
- 数据库诊断信息必须裁剪和脱敏，不能保存原始 Provider 响应。
- 管理端不能读取或修改 `.env`、API Key 和完整凭据 URL。

## 8. 保留期任务

至少每天执行一次：

- 清空 30 天前的 `shooting_intent` 和 `report_json`。
- 删除或聚合超过 180 天的分析运行指标。
- 释放过期 reservation。
- 撤销过期管理会话。
- 清理短期来源限流哈希。

清理任务要记录数量和执行状态，但不能把被清理的敏感内容写入日志。

## 9. 推荐实施顺序

每一步独立提交并测试：

1. SQLAlchemy 基础、SQLite 配置和 Alembic 初始迁移。
2. `analysis_runs` 与 `AnalysisRecorder`。
3. 邀请码、账本和 `UsageAuthorizer` 原子事务测试。
4. 控制面分析编排服务和 `AnalysisResponse.interaction`。
5. 匿名评价与问题反馈存储及公开路由。
6. 管理员账号、会话和认证依赖。
7. 管理 API 查询、过滤、分页和审计。
8. 管理 React 页面。
9. 公开前端的邀请码、点赞点踩和反馈组件。
10. 保留期任务、导出和部署配置。
11. SQLite 到 PostgreSQL 的集成测试。

## 10. 最低验收标准

### 额度

- 两个并发请求争抢最后一次额度时只能一个预占成功。
- 成功消费一次，模型失败释放一次。
- 重复 commit/release 不改变第二次余额。
- 无效、过期、撤销和耗尽邀请码均被拒绝。
- 原始邀请码不出现在数据库、日志和普通查询响应。
- open/code_required/closed 三种模式都有 API 测试。

### 分析记录

- 成功和每类失败都产生一个终态记录。
- 不保存图片字节。
- 报告与意图能按 30 天规则清理。
- 日志和管理详情不含秘密或原始上游响应。

### 反馈

- 每个 analysis/target 只有一个当前评价。
- PUT 可更新，DELETE 幂等。
- feedback token 不能评价其他 analysis。
- 八个 target 都有契约和路由测试。
- 问题反馈状态流转写入审计。

### 管理端

- 未认证访问全部返回 401。
- 管理员会话过期和撤销后不可使用。
- 邀请码原文只在创建响应显示一次。
- 分页、过滤、空结果和最大时间范围都有测试。
- 管理修改全部产生审计事件。
- 前端不展示 API Key、邀请码哈希或反馈 token。

### 回归

- 当前 178 项后端测试继续通过。
- 现有 9 项前端测试继续通过。
- Mock V2 分析在控制面 open 模式下完成。
- 数据库或管理服务不可用时不能绕过额度限制。

## 11. 明确不在第一版管理端中实现

- 多角色 RBAC
- 用户注册和普通用户账号
- 在线编辑 Prompt、知识库或 API Key
- 保存或浏览用户照片
- 自动重新调用失败的付费模型请求
- 实时 WebSocket 仪表盘
- 复杂消息队列或微服务拆分

先完成可审计、可恢复、事务正确的单体实现，再根据真实使用量决定是否扩展。
