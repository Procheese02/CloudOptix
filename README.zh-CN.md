# CloudOptix - AI FinOps 云成本优化 Agent

[English](README.md)

CloudOptix 是一个基于 AI 的 FinOps 云成本优化助手。它能够分析 AWS EC2 fleet 的账单和资源利用率数据，通过 RAG 检索云资源价格政策，并在任何基础设施变更前，先生成需要人工确认的成本优化建议。

这个项目被设计成一个适合求职展示的 AI 基础设施应用：它围绕“降低云资源浪费”这一真实业务问题，结合了云自动化、RAG、LangGraph 多 Agent 编排和安全执行控制。

## 项目痛点

云基础设施经常存在资源过度配置的问题。工程团队为了稳定性，往往会申请更大的实例规格，但这些资源可能长期处于低利用率状态，从而造成不必要的云成本支出。

CloudOptix 可以识别这类浪费模式，并生成可解释的实例规格优化建议，例如：

> 建议将 EC2 实例 `i-03ea43d903f366fa5` 从 `t3.2xlarge` 降级到 `t3.large`，预计每月节省 `$185.28`。

## 解决方案

CloudOptix 使用多 Agent 工作流完成以下任务：

1. 默认加载多台 EC2 实例的模拟 AWS 账单和资源利用率数据，也可以可选地读取 AWS Cost Explorer 的只读真实成本数据，并导出成相同 JSON 结构。
2. 检测低利用率 EC2 实例，并识别不应该调整的资源。
3. 从本地 RAG 知识库中检索价格规则和降级策略。
4. 生成 Markdown 格式的 fleet-level 成本优化报告，包含 top savings opportunities、风险等级和推荐执行顺序。
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

## Product Roadmap（产品路线图）

当前版本聚焦于 AWS EC2 实例规格优化，并拆成两条安全的数据路径：

- 默认 mock 工作流：完整、可复现的 demo，可以生成优化建议。
- 可选 Cost Explorer 工作流：导入真实只读账单数据，用于成本分析和账单导入展示。
- 下一阶段：接入 CloudWatch / Compute Optimizer 补充 utilization 数据，再生成真实 rightsizing 建议。

已实现能力：

- 模拟 AWS fleet 账单数据摄入
- 账单特征分析：CPU 分布、按实例类型聚合利用率、异常检测、成本占比和数据质量检查
- 可选的只读 AWS Cost Explorer 成本导出，输出为相同账单 JSON 结构
- 可复现的动态 EC2 mock fleet 生成器，支持 50+ 台实例
- 多台 EC2 实例的低利用率检测
- 识别不应该调整的受保护资源
- Fleet-level 月度成本和节省金额汇总
- Top savings opportunities 和推荐执行顺序
- 结构化本地价格知识库，并在 RAG 入库前添加标签
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
- 默认 demo 使用生成的 mock 数据，免费、稳定、可复现。
- 只有使用可选 AWS 集成时，才会从 `.env` 加载 AWS 凭证。
- Cost Explorer 导入脚本只读取账单数据，并只写入本地 JSON 文件。
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
├── generate_mock.py          # 可复现的动态 EC2 mock fleet 生成器
├── fetch_cost_explorer.py    # 可选的只读 AWS Cost Explorer 导出脚本
├── analyze_billing.py        # 账单特征分析和数据质量检查
├── build_rag.py              # 本地 RAG 索引构建脚本
├── test_llm.py               # LLM 连接测试
├── requirements.txt          # Python 依赖
├── data/
│   ├── mock_billing.json     # 生成的 EC2 账单和利用率模拟数据
│   ├── aws_pricing.json      # 结构化 EC2 价格、降级规则和约束条件
│   └── aws_pricing.md        # 人类可读的 EC2 价格和降级策略文档
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

`build_rag.py` 会从 `data/aws_pricing.json` 加载结构化价格和降级规则，把它们转换成带有 `category=compute`、`scope=ec2`、`action=downsizing` 等标签的 chunk，然后写入 Qdrant。Markdown 价格文档会继续作为人类可读文档和 fallback context 保留。

```bash
python3 build_rag.py
```

### 5. 生成模拟 EC2 fleet 数据

默认工作流使用 `generate_mock.py`。这条路径免费、稳定、可复现，因此推荐作为 demo 默认模式。

```bash
python3 generate_mock.py --fleet-size 60 --seed 42 --output data/mock_billing.json
```

生成器会创建一个可复现的 50+ 台 EC2 fleet，包含健康实例、低利用率实例、受保护生产实例、最低规格实例和临时 autoscaling 实例。生成的 JSON 默认只保留在本地，因为 `data/*.json` 已被忽略；需要刷新 demo 数据时重新运行该命令即可。

### 可选：导出只读 AWS Cost Explorer 数据

如果你想查看真实 AWS 账单成本数据，同时不替换默认 mock demo，可以运行可选的 Cost Explorer 导出脚本：

```bash
python3 fetch_cost_explorer.py --start 2026-04-01 --end 2026-05-01 --output data/cost_explorer_billing.json
```

该脚本只读取 AWS Cost Explorer，并写出一个与 `data/mock_billing.json` 顶层结构一致的本地 JSON 文件。它需要带有 Cost Explorer 只读权限的 AWS 凭证，例如 `ce:GetCostAndUsage`。Cost Explorer 不包含 CPU、内存、owner 或 workload 数据，因此导出的记录默认标记为 `protected`。这让导出的文件适合展示真实账单导入和成本分析，但不适合直接生成自动降级执行建议。

如果想让 agent 读取导出的 Cost Explorer 文件，同时不替换默认 mock demo 输入，可以显式传入账单文件：

```bash
python3 tool.py --dry-run --billing-file data/cost_explorer_billing.json
```

### 6. 在优化前分析账单特征

运行特征分析脚本，先检查 utilization 分布、按实例类型聚合的平均利用率、成本占比、低负载高成本异常和数据质量，再生成执行计划：

```bash
python3 analyze_billing.py --billing-file data/mock_billing.json --output data/billing_analysis.json
```

这个输出可以帮助优先处理真正有意义的节省机会，并标记账单文件是否有足够的 utilization 覆盖率用于 rightsizing。Cost Explorer 导出文件也可以用同样方式分析，但在接入 CloudWatch 或 Compute Optimizer utilization 数据前，它仍然是受保护的 cost-only 记录。

### 7. 运行优化工作流

```bash
python3 tool.py --dry-run
```

Dry-run 是默认模式，只会生成优化报告和 AWS 执行计划，不会修改任何 AWS 资源。

如果想显式使用默认 dry-run 行为，可以传入 `--dry-run`。如果想在人工确认后尝试真实 EC2 规格调整，可以运行：

```bash
python3 tool.py --execute
```

工作流会执行以下步骤：

1. 使用 `generate_mock.py` 生成或刷新 `data/mock_billing.json` 中的模拟账单数据。
2. 可选地把真实只读 AWS Cost Explorer 数据导出到单独 JSON 文件，用于手动实验。
3. 从 `data/mock_billing.json` 加载账单数据。
4. 判断哪些 EC2 实例低利用率，以及哪些资源不应该调整。
5. 从本地知识库中检索相关价格规则。
6. 生成 fleet-level 成本优化报告。
7. 默认针对符合条件的实例生成 dry-run AWS 执行计划。

在 dry-run 模式下，不会执行任何 AWS 修改。

在 execute 模式下，工具会先请求人工确认，然后尝试停止 EC2 实例、修改实例规格并重新启动。该操作可能会被 AWS 账号权限或免费计划限制阻止。

## 示例输出

```text
Inspector: Found 20+ optimizable resources and 40+ resources that should not be changed
Researcher: Retrieved EC2 pricing policy from knowledge base
Advisor: Generated fleet-level cost optimization report

Fleet summary:
Total monthly cost: generated from the current mock fleet
Optimizable resources: based on current utilization simulation
Estimated monthly savings: calculated from rightsizing candidates
Risk level: Low to Medium

Top opportunity:
Downgrade the largest low-utilization t3 instance to the recommended smaller type

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

- 生成企业级月度云成本优化报告
- 扩展 AWS Cost Explorer 集成，并补充利用率数据 enrich
- 支持 RDS、EBS、S3 等更多 AWS 资源
- 生成 Terraform Plan，而不是直接调用 AWS API
- 接入 Slack 或飞书审批工作流
- 构建 FastAPI + React Dashboard
- 为 Agent 节点、价格逻辑和 AWS 工具行为增加单元测试

## 简历描述

构建 CloudOptix，一个 AI 驱动的 FinOps 云成本优化 Agent。该项目能够分析 AWS EC2 fleet 账单和资源利用率数据，通过基于 Qdrant 的 RAG 管道检索价格策略，并使用 LangGraph 多 Agent 编排生成带人工审批机制的 fleet-level 云成本优化方案。
