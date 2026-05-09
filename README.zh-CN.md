# CloudOptix - AI FinOps 云成本优化 Agent

[English](README.md)

CloudOptix 是一个基于 AI 的 FinOps 云成本优化助手。它能够分析 AWS EC2 的账单和资源利用率数据，通过 RAG 检索云资源价格政策，并在任何基础设施变更前，先生成需要人工确认的成本优化建议。

这个项目被设计成一个适合求职展示的 AI 基础设施应用：它围绕“降低云资源浪费”这一真实业务问题，结合了云自动化、RAG、LangGraph 多 Agent 编排和安全执行控制。

## 项目痛点

云基础设施经常存在资源过度配置的问题。工程团队为了稳定性，往往会申请更大的实例规格，但这些资源可能长期处于低利用率状态，从而造成不必要的云成本支出。

CloudOptix 可以识别这类浪费模式，并生成可解释的实例规格优化建议，例如：

> 建议将 EC2 实例 `i-03ea43d903f366fa5` 从 `t3.2xlarge` 降级到 `t3.large`，预计每月节省 `$185.28`。

## 解决方案

CloudOptix 使用多 Agent 工作流完成以下任务：

1. 加载模拟的 AWS 账单和资源利用率数据。
2. 检测低利用率 EC2 实例。
3. 从本地 RAG 知识库中检索价格规则和降级策略。
4. 生成 Markdown 格式的成本优化报告。
5. 在人工确认后，可选地通过 `boto3` 执行 AWS EC2 实例规格调整。

默认情况下，项目强调安全的 FinOps 自动化，而不是让 AI 不受控制地直接修改云资源。

## 系统架构

```text
CloudOptix
├── Billing Ingestor（账单数据摄入）
│   └── 从 JSON 加载 AWS 账单和 EC2 利用率数据
│
├── RAG Pricing Service（价格知识库检索服务）
│   └── 从 Qdrant 检索 EC2 价格和内部降级策略
│
├── LangGraph Optimization Agent（优化编排 Agent）
│   ├── Inspector Agent：检测低利用率资源
│   ├── Researcher Agent：检索价格和降级规则
│   └── Advisor Agent：生成优化报告
│
├── Approval Gateway（审批网关）
│   └── 在真实 AWS 变更前要求人工确认
│
└── Execution Tool（执行工具）
    └── 基于 boto3 的可选 EC2 规格调整，并包含 AWS 错误处理
```

## 当前 MVP 范围

当前版本聚焦于 AWS EC2 实例规格优化。

已实现功能：

- 模拟 AWS 账单数据摄入
- 低利用率实例检测
- 本地价格知识库
- 基于 Qdrant 的 RAG 检索
- LangGraph Agent 工作流
- Markdown 优化报告生成
- Dry-run 模式，用于安全生成执行计划
- 显式 execute 模式，用于人工批准后的 AWS 修改
- 执行前人工确认
- AWS 区域校验
- AWS 免费计划限制处理
- 通过 `.env` 安全加载凭证

MVP 暂不包含：

- 完整多云支持
- 无审批的生产环境自动执行
- 实时监控管道
- Slack / 飞书审批工作流
- 前端 Dashboard

这些功能会作为后续扩展方向。

## 安全设计

CloudOptix 特意加入了基础设施安全控制：

- 不在源代码中硬编码云凭证。
- AWS 凭证通过 `.env` 加载。
- 修改 EC2 实例前必须进行人工确认。
- 校验 AWS 区域配置，并将 `us-east-2c` 这样的可用区自动修正为 `us-east-2` 这样的区域。
- 优雅处理 AWS 权限错误和免费计划限制。
- 即使真实 AWS 执行被账号权限阻止，项目仍然可以完整展示 AI 决策链路。

## 技术栈

- Python
- LangGraph
- LangChain
- LlamaIndex
- Qdrant
- OpenAI-compatible LLM API
- AWS SDK for Python (`boto3`)
- python-dotenv

## 项目结构

```text
.
├── agent.py                  # LangGraph 优化工作流
├── tool.py                   # 需要人工确认的 AWS 执行工具
├── build_rag.py              # 本地 RAG 索引构建脚本
├── test_llm.py               # LLM 连接测试
├── requirements.txt          # Python 依赖
├── data/
│   ├── mock_billing.json     # 模拟 EC2 账单和利用率数据
│   └── aws_pricing.md        # 本地 EC2 价格和降级策略文档
└── qdrant_data/              # 本地 Qdrant 向量数据库
```

## 安装与运行

### 1. 创建并激活虚拟环境

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

在项目根目录创建 `.env` 文件：

```env
OPENAI_API_KEY="your_openai_api_key"
OPENAI_BASE_URL="your_openai_compatible_base_url"

AWS_ACCESS_KEY_ID="your_aws_access_key_id"
AWS_SECRET_ACCESS_KEY="your_aws_secret_access_key"
AWS_DEFAULT_REGION="us-east-2"
```

不要把 `.env` 提交到 GitHub。

### 4. 构建本地 RAG 索引

```bash
python3 build_rag.py
```

### 5. 运行优化工作流

```bash
python3 tool.py --dry-run
```

Dry-run 是默认模式，只会生成优化报告和 AWS 执行计划，不会修改任何 AWS 资源。

如果想显式使用默认 dry-run 行为，可以传入 `--dry-run`。如果想在人工确认后尝试真实 EC2 规格调整，可以运行：

```bash
python3 tool.py --execute
```

工作流会执行以下步骤：

1. 从 `data/mock_billing.json` 加载账单数据。
2. 判断 EC2 实例是否存在低利用率问题。
3. 从本地知识库中检索相关价格规则。
4. 生成成本优化报告。
5. 默认生成 dry-run AWS 执行计划。

在 dry-run 模式下，不会执行任何 AWS 修改。

在 execute 模式下，工具会先请求人工确认，然后尝试停止 EC2 实例、修改实例规格并重新启动。该操作可能会被 AWS 账号权限或免费计划限制阻止。

## 示例输出

```text
Inspector: CPU utilization is 6.68%, optimization needed: True
Researcher: Retrieved EC2 pricing policy from knowledge base
Advisor: Generated cost optimization report

Recommendation:
Downgrade i-03ea43d903f366fa5 from t3.2xlarge to t3.large
Estimated monthly savings: $185.28

Human approval required before execution.
```

## 项目价值

这个项目展示了与 AI 基础设施和云工程岗位高度相关的能力：

- 使用 LangGraph 构建 Agentic Workflow
- 将 RAG 应用于业务文档和基础设施策略
- 使用 AWS SDK 进行云自动化
- 设计 Human-in-the-loop 的安全 AI 执行系统
- 将 AI 输出转化为可量化的业务价值
- 处理真实云环境中的区域、权限和账号限制问题

## 后续计划

计划扩展：

- 分析 50+ 台模拟 EC2 实例组成的资源池
- 生成企业级月度云成本优化报告
- 接入 AWS Cost Explorer
- 支持 RDS、EBS、S3 等更多 AWS 资源
- 生成 Terraform Plan，而不是直接调用 AWS API
- 接入 Slack 或飞书审批工作流
- 构建 FastAPI + React Dashboard
- 为 Agent 节点、价格逻辑和 AWS 工具行为增加单元测试

## 简历描述

构建 CloudOptix，一个 AI 驱动的 FinOps 云成本优化 Agent。该项目能够分析 AWS EC2 账单和资源利用率数据，通过基于 Qdrant 的 RAG 管道检索价格策略，并使用 LangGraph 多 Agent 编排生成带人工审批机制的云成本优化方案。
