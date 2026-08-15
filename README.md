# AI 摄影教练 Agent

一个面向摄影学习者的全栈 V2：上传一张 JPEG、PNG 或 WebP 照片后，系统检索项目摄影手册，并返回基于画面证据和摄影知识的结构化指导。

## V2 能力

- 单图上传，可选填写拍摄意图
- 图片真实格式、完整性、大小和像素安全检查
- 构图、光影、色彩、主体表达、视觉叙事五维报告
- 每个维度包含评分、证据、优点、问题和可执行建议
- 三条有顺序的优先改进动作和一次拍摄练习
- Mock 模型零成本本地运行
- 可配置的 Responses-compatible 多模态与 Structured Outputs 适配器
- 超时、限流、模型不可用、异常输出和请求错误的统一响应
- 记录 provider、model、Prompt 版本、耗时和 token 用量，不记录图片内容
- React + TypeScript 单页前端，支持照片预览、隐私确认和完整报告展示
- 多模态模型先根据可见画面规划五个维度的知识检索问题
- 使用 Embedding 和本地 Chroma 召回摄影手册候选知识
- 使用可替换的 Reranker 重排候选，并保证五个报告维度都有知识覆盖
- 在响应中记录知识库、规划 Prompt、Embedding、Reranker、命中数量与检索耗时

## 请求流程

```text
客户端
  → FastAPI /api/v2/analyze
  → 图片内容验证
  → 多模态检索规划（五个维度）
  → Embedding + Chroma 候选召回
  → Reranker 重排并压缩上下文
  → 多模态模型生成摄影报告
  → PhotographyReport
  → 结构化 JSON 响应
```

V2 仍是清晰的固定工作流，因此使用普通 Python、FastAPI、Chroma 和模型官方兼容接口，没有引入 LangChain 或 LangGraph。

## 项目文档

- [项目知识手册](docs/PROJECT_KNOWLEDGE.md)：从 V1 到 V2 的开发回顾、架构、完整请求链路、RAG 设计、模块职责、排错方法和初学者名词表。
- [控制面与反馈 API 契约](docs/CONTROL_PLANE_API.md)：邀请码额度、匿名评价、问题反馈和管理接口的共同约定。
- [管理端 Agent 开发交接](docs/ADMIN_AGENT_HANDOFF.md)：数据库、事务、安全边界、实施顺序和验收标准。
- [控制面验收清单](docs/CONTROL_PLANE_ACCEPTANCE.md)：额度、记录、反馈、管理端和回归的验收结果。
- [V1 验收清单](docs/V1_ACCEPTANCE.md)：V1 功能、隐私、响应式和测试验收。
- [V2 本地验收清单](docs/V2_ACCEPTANCE.md)：RAG 流程、本地浏览器测试和真实 Provider 验证状态。

## 本地运行

要求 Python 3.11 或以上。

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
cp .env.example .env
uvicorn photography_coach.main:app --reload
```

打开：

- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>

示例配置使用 Mock Provider 和本地确定性 Embedding/Reranker，不需要 API Key，也不会产生模型费用。首次启动会在 `data/chroma/` 建立可重新生成的本地索引；后续启动会复用同一知识库和模型对应的索引。

启动前端（新终端）：

```bash
cd frontend
npm install
npm run dev
```

打开 <http://127.0.0.1:5173>。开发服务器会把 `/api` 请求转发给本地 FastAPI。

## 管理控制台

控制面默认关闭；启用后提供邀请码额度、匿名评价、分析记录、问题反馈和管理 API：

```bash
# .env 增加
CONTROL_PLANE_ENABLED=true
DATABASE_URL=sqlite+aiosqlite:///data/control_plane.db

# 创建第一个管理员（密码至少 12 位，只在本地保存 Argon2id 哈希）
python scripts/create_admin.py --username owner

# 重启后端，访问 http://127.0.0.1:5173/admin.html
```

数据库表结构由 Alembic 管理：`alembic upgrade head` 应用迁移（本地启动也会自动建表）。
详细说明见 [docs/CONTROL_PLANE_ACCEPTANCE.md](docs/CONTROL_PLANE_ACCEPTANCE.md) 和
[docs/CONTROL_PLANE_API.md](docs/CONTROL_PLANE_API.md)。未启用控制面时，V2 接口与
旧行为完全一致。

## 调用分析接口

```bash
curl -X POST http://127.0.0.1:8000/api/v2/analyze \
  -F "photo=@/absolute/path/to/photo.jpg;type=image/jpeg" \
  -F "intent=我想表现雨天街道的孤独感"
```

允许格式：JPEG、PNG、WebP。V2 限制为静态图片、最大 10 MiB、最大 2500 万像素。旧的 `/api/v1/analyze` 仍保留为不经过知识检索的基线接口。

## 使用真实模型 API

复制环境变量模板：

```bash
cp .env.example .env
```

在 `.env` 中配置：

```dotenv
MODEL_PROVIDER=dashscope
MODEL_API_KEY=你的本地密钥
MODEL_NAME=qwen3.7-plus
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_TIMEOUT_SECONDS=120
RAG_ENABLED=true
RAG_CONTEXT_TIMEOUT_SECONDS=120
EMBEDDING_MODEL=qwen3.7-text-embedding
RERANK_MODEL=qwen3-rerank
RERANK_BASE_URL=控制台提供的兼容接口基础地址
```

使用百炼 Qwen 时，将 `MODEL_PROVIDER` 设置为 `dashscope`，填写本地 API Key、模型名称、模型基础地址和 Reranker 基础地址。`RERANK_BASE_URL` 应以兼容接口版本路径结尾，不要包含 `/reranks` 资源路径，也不要在 URL 中放置凭据。

业务层依赖的是 `PhotographyProvider` 协议，而不是某家模型厂商。对于不兼容 Responses API 的服务，只需新增一个 Provider 适配器，实现同一个 `analyze()` 方法；路由、验证、业务服务和报告 Schema 不需要修改。

`.env` 已被 Git 忽略。请勿把真实 Key 写入代码、README、测试或提交记录。

图片通过 Base64 data URL 随规划请求和最终报告请求发送。Embedding 与 Reranker 只接收摄影问题和知识库文字，不接收照片。如果切换服务商，应在对应适配器中确认其数据保留和隐私选项。

## 测试

```bash
python -m unittest discover -s tests -v
```

所有真实模型适配器测试都使用模拟客户端，不会访问外部 API，也不会消耗 token。

前端检查：

```bash
cd frontend
npm run lint
npm run build
npm test
```

## 本地评测

测试照片保存在被 Git 忽略的 `Photos/` 中，仓库只记录不含图片内容的
数据集清单。V1 基线运行器会先验证文件路径和 SHA-256 指纹，再逐张调用当前
配置的 Provider，并在每张完成后保存本地快照：

```bash
MODEL_TIMEOUT_SECONDS=90 python -m photography_coach.evals.runner \
  evals/datasets/0813.json \
  --output evals/results/0813-v1.1.json
```

若部分请求超时、限流或返回异常结构，可跳过已有成功项，只重试失败项：

```bash
MODEL_TIMEOUT_SECONDS=90 python -m photography_coach.evals.runner \
  evals/datasets/0813.json \
  --output evals/results/0813-v1.1.json \
  --resume
```

`evals/results/` 可能包含对私人照片的文字描述，因此也被 Git 忽略。评测用
90 秒超时不会改变网页端 `.env` 中的默认请求超时。

获得照片发送授权后，可运行单照片 V2 全链路烟雾测试：

```bash
python scripts/smoke_test_rag_pipeline.py
```

脚本会保存规划、检索、重排和最终报告的本地结果。照片、模型报告、Chroma
数据和 `.env` 均被 Git 忽略。

## 主要目录

```text
src/photography_coach/
├── api/                 # FastAPI 路由
├── knowledge/           # Chunk、Embedding、Chroma 与检索契约
├── providers/           # Mock 与可替换的模型适配器
├── schemas/             # Pydantic 请求/响应契约
├── services/            # 分析业务流程
├── config.py            # 环境变量配置
├── errors.py            # 统一应用异常
├── image_validation.py  # 图片安全验证
├── main.py              # FastAPI 应用入口
└── prompts.py           # Prompt 内容与版本

knowledge/
├── manuals/             # 项目编写的摄影手册
├── chunks/              # 可验证、可向量化的章节切分结果
└── sources/             # 知识来源及使用权元数据

frontend/src/
├── components/          # 上传表单与报告展示组件
├── api.ts               # FastAPI 请求和错误翻译
├── types.ts             # 与 Pydantic 响应对应的 TypeScript 类型
└── App.tsx              # 单页流程状态与页面组装
```

## 隐私与安全边界

- V2 不保存上传图片，也不建立用户历史。
- 不信任扩展名或客户端 MIME 声明，以 Pillow 检测真实内容。
- Prompt 明确把图片文字和拍摄意图视为不可信资料，不能当作指令执行。
- 模型不得虚构 EXIF、相机、镜头、曝光参数、地点、天气或画外条件。
- 知识文本作为参考数据传入模型，不能覆盖系统规则或执行其中的指令。
- Pydantic 保证数据结构，不保证摄影建议一定专业；项目使用本地测试照片集和人工评分规则继续评估质量。

## 暂未包含

用户注册、普通用户账号、多角色 RBAC、自动修图、Docker 和复杂 Agent 工作流仍未包含，将在后续版本按真实需求加入。控制面已提供 SQLite 单机版的管理员账号、额度、记录和反馈能力，并保留 PostgreSQL 迁移兼容写法。
