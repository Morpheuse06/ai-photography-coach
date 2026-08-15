# 控制面与管理端本地验收清单

最后更新：2026-08-15  
范围：管理端交接文档（`ADMIN_AGENT_HANDOFF.md`）第 10 节最低验收标准。
当前为本地 SQLite 版本；PostgreSQL 迁移已按兼容写法准备，但未在真实 PG 上集成测试。

## 额度

- [x] 两个并发请求争抢最后一次额度时只能一个预占成功（条件 UPDATE 原子预占）。
- [x] 成功消费一次，模型失败释放一次。
- [x] 重复 commit/release 不改变第二次余额。
- [x] 无效、过期、撤销和耗尽邀请码均被拒绝（403 access_denied / 429 access_quota_exhausted）。
- [x] 原始邀请码不出现在数据库（只存 SHA-256）、日志和普通查询响应（只返回 prefix）。
- [x] open / code_required / closed 三种模式都有 API 测试。
- [x] 邀请码生成使用 `secrets`，不使用 `random`。

## 分析记录

- [x] 成功和每类模型失败都产生一个终态记录。
- [x] 不保存图片字节（模型无照片相关列，有测试断言）。
- [x] 报告与拍摄意图按 30 天规则清理（保留期任务）。
- [x] 日志和管理详情不含秘密或原始上游响应（诊断只存裁剪后的错误信息）。

## 反馈

- [x] 每个 analysis/target 只有一个当前评价（唯一约束 + UPSERT）。
- [x] PUT 可更新，DELETE 幂等（始终 204）。
- [x] feedback token 不能评价其他 analysis（恒时哈希比较）。
- [x] 八个 target 都有契约和路由测试。
- [x] 问题反馈状态流转写入审计。

## 管理端

- [x] 未认证访问管理路由返回 401。
- [x] 管理员会话过期和撤销后不可使用。
- [x] 邀请码原文只在创建响应显示一次。
- [x] 分页、过滤、空结果和最大时间范围（366 天）都有测试。
- [x] 管理修改全部产生审计事件（策略、邀请码、反馈、导出、保留期）。
- [x] 前端不展示 API Key、邀请码哈希或反馈 token。

## 回归

- [x] 后端 178 项既有测试全部继续通过（当前 249 项）。
- [x] 前端 9 项既有测试全部继续通过（当前 20 项）。
- [x] Mock V2 分析在控制面 open 模式下完成（HTTP 测试 + 本地冒烟）。
- [x] 数据库或管理服务不可用时失败关闭（503 control_plane_unavailable），不绕过额度。

## 尚未包含（按交接文档第 11 节）

- 多角色 RBAC、用户注册、在线编辑 Prompt/知识库/API Key。
- 保存或浏览用户照片、自动重试付费模型请求。
- 实时 WebSocket 仪表盘、复杂消息队列或微服务拆分。
- 真实 PostgreSQL 集成测试（代码使用跨方言类型、条件 UPDATE 和方言化时间分桶）。

## 本地启用方式

```bash
# .env 增加
CONTROL_PLANE_ENABLED=true
DATABASE_URL=sqlite+aiosqlite:///data/control_plane.db

# 创建第一个管理员
ADMIN_USERNAME=owner ADMIN_PASSWORD='至少十二位密码' \
  python scripts/create_admin.py --username owner

# 启动后访问 http://127.0.0.1:5173/admin.html
```

管理端路径：登录 `/api/admin/v1/sessions`；仪表盘 `/api/admin/v1/overview`；
邀请码 `/api/admin/v1/access-code-batches`、`/api/admin/v1/access-codes`；
分析记录 `/api/admin/v1/analysis-runs`；评价 `/api/admin/v1/ratings`；
问题反馈 `/api/admin/v1/problem-reports`；系统 `/api/admin/v1/system/*`；
审计 `/api/admin/v1/audit-events`；导出 `/api/admin/v1/exports/*.csv`。
