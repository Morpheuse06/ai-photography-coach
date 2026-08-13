# AI 摄影教练 Agent

一个面向摄影学习者的全栈 V1：上传一张 JPEG、PNG 或 WebP 照片后，返回基于可见证据的结构化摄影指导。

## V1 能力

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

## 请求流程

```text
客户端
  → FastAPI 上传接口
  → 图片内容验证
  → AnalysisService（总超时）
  → Mock 或可配置的模型 Provider
  → PhotographyReport
  → 结构化 JSON 响应
```

V1 是固定工作流，因此只使用普通 Python、FastAPI 和官方 SDK，没有引入 LangChain 或 LangGraph。

## 本地运行

要求 Python 3.11 或以上。

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
uvicorn photography_coach.main:app --reload
```

打开：

- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>

默认使用 Mock Provider，不需要 API Key，也不会产生模型费用。

启动前端（新终端）：

```bash
cd frontend
npm install
npm run dev
```

打开 <http://127.0.0.1:5173>。开发服务器会把 `/api` 请求转发给本地 FastAPI。

## 调用分析接口

```bash
curl -X POST http://127.0.0.1:8000/api/v1/analyze \
  -F "photo=@/absolute/path/to/photo.jpg;type=image/jpeg" \
  -F "intent=我想表现雨天街道的孤独感"
```

允许格式：JPEG、PNG、WebP。V1 限制为静态图片、最大 10 MiB、最大 2500 万像素。

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
```

使用百炼 Qwen 时，将 `MODEL_PROVIDER` 设置为 `dashscope`，填写本地 API Key、模型名称和控制台提供的区域地址。使用 Responses API 兼容服务时设置为 `responses_compatible`。

业务层依赖的是 `PhotographyProvider` 协议，而不是某家模型厂商。对于不兼容 Responses API 的服务，只需新增一个 Provider 适配器，实现同一个 `analyze()` 方法；路由、验证、业务服务和报告 Schema 不需要修改。

`.env` 已被 Git 忽略。请勿把真实 Key 写入代码、README、测试或提交记录。

当前 Responses-compatible 实现依据 OpenAI 官方的 [图片输入指南](https://developers.openai.com/api/docs/guides/images-vision) 和 [Structured Outputs 指南](https://developers.openai.com/api/docs/guides/structured-outputs)。图片通过 Base64 data URL 随单次请求发送，并设置 `store=False`。如果切换到其他 API 形状，应在对应适配器中实现同等的隐私选项。

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

## 主要目录

```text
src/photography_coach/
├── api/                 # FastAPI 路由
├── providers/           # Mock 与可替换的模型适配器
├── schemas/             # Pydantic 请求/响应契约
├── services/            # 分析业务流程
├── config.py            # 环境变量配置
├── errors.py            # 统一应用异常
├── image_validation.py  # 图片安全验证
├── main.py              # FastAPI 应用入口
└── prompts.py           # Prompt 内容与版本

frontend/src/
├── components/          # 上传表单与报告展示组件
├── api.ts               # FastAPI 请求和错误翻译
├── types.ts             # 与 Pydantic 响应对应的 TypeScript 类型
└── App.tsx              # 单页流程状态与页面组装
```

## 隐私与安全边界

- V1 不保存上传图片，也不建立用户历史。
- 不信任扩展名或客户端 MIME 声明，以 Pillow 检测真实内容。
- Prompt 明确把图片文字和拍摄意图视为不可信资料，不能当作指令执行。
- 模型不得虚构 EXIF、相机、镜头、曝光参数、地点、天气或画外条件。
- Pydantic 和 Structured Outputs 保证数据结构，不保证摄影建议一定专业；后续仍需建立测试照片集和人工评价标准。

## 暂未包含

数据库、用户系统、历史趋势、RAG、自动修图、Docker 和复杂 Agent 工作流将在后续版本按真实需求加入。
