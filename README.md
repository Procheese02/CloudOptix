# CloudOptix - AI FinOps Agent for AWS EC2 Cost Optimization

[简体中文](README.zh-CN.md)

CloudOptix is an AI-powered FinOps assistant that analyzes AWS EC2 billing and utilization data across a fleet, retrieves cloud pricing policies through RAG, and generates cost optimization recommendations with human approval before any infrastructure change.

The project is designed as a practical, job-portfolio-ready AI infrastructure application: it combines cloud automation, RAG, LangGraph agent orchestration, and safe execution controls around a real business problem — reducing cloud waste.

## Problem

Cloud infrastructure is often over-provisioned. Engineering teams may request larger instances for safety, but many resources remain underutilized for long periods, creating unnecessary monthly cloud spend.

CloudOptix helps identify these waste patterns and produces explainable rightsizing recommendations such as:

> Downgrade EC2 instance `i-03ea43d903f366fa5` from `t3.2xlarge` to `t3.large`, with an estimated monthly saving of `$185.28`.

## Solution

CloudOptix uses a multi-agent workflow to:

1. Load mock AWS billing and utilization data for multiple EC2 instances by default, or optionally load read-only AWS Cost Explorer cost data exported into the same JSON shape.
2. Detect underutilized EC2 instances and resources that should not be changed.
3. Retrieve pricing rules and downgrade policies from a local RAG knowledge base.
4. Generate a Markdown fleet-level cost optimization report with top savings opportunities, risk levels, and execution order.
5. Optionally prepare and execute AWS EC2 resize actions through `boto3` after human confirmation.

By default, the project is structured around safe FinOps automation rather than uncontrolled AI execution.

## Architecture

```text
CloudOptix
├── Billing Ingestor
│   └── Loads AWS billing and EC2 utilization data from JSON
│
├── RAG Pricing Service
│   └── Retrieves EC2 pricing and internal downgrade policies from Qdrant
│
├── LangGraph Optimization Agent
│   ├── Inspector Agent: detects underutilized resources
│   ├── Researcher Agent: retrieves pricing and downgrade rules
│   └── Advisor Agent: generates optimization reports
│
├── Approval Gateway
│   └── Requires human confirmation before real AWS changes
│
└── Execution Tool
    └── Optional boto3-based EC2 resize with AWS error handling
```

## Product Roadmap

The current version focuses on AWS EC2 rightsizing and is split into two safe data paths:

- Default mock workflow: a complete, reproducible demo that can generate optimization recommendations.
- Optional Cost Explorer workflow: real read-only billing import for cost analysis and bill-import demos.
- Next stage: connect CloudWatch / Compute Optimizer utilization data before generating real rightsizing recommendations.

Implemented capabilities:

- Mock AWS fleet billing data ingestion
- Billing feature analysis for CPU distribution, instance-type utilization, anomaly detection, cost share, and data quality
- Optional read-only AWS Cost Explorer cost export into the same billing JSON structure
- Dynamic mock EC2 fleet generator with 50+ reproducible instances
- Low-utilization instance detection across multiple EC2 instances
- Protected-resource detection for instances that should not be changed
- Fleet-level monthly cost and savings summary
- Top savings opportunities with recommended execution order
- Local structured pricing knowledge base with tagged RAG chunks
- Qdrant-backed RAG retrieval
- LangGraph agent workflow
- Markdown optimization report generation
- Dry-run mode for safe action planning
- Explicit execute mode for approved AWS changes
- Human-in-the-loop approval before execution
- AWS region validation
- AWS free-tier restriction handling
- Secure credential loading through `.env`

Out of scope for the MVP:

- Full multi-cloud support
- Automatic production execution without approval
- Real-time monitoring pipeline
- Slack / Feishu approval workflow
- Frontend dashboard

These are planned as future extensions.

## Safety Design

CloudOptix is intentionally designed with infrastructure safety controls:

- No cloud credentials are hardcoded in source code.
- The default demo uses generated mock data, so it is free, stable, and reproducible.
- AWS credentials are loaded from `.env` only when using optional AWS integrations.
- The Cost Explorer importer is read-only and only writes a local JSON file.
- Human confirmation is required before EC2 modification.
- AWS region values are validated and availability zones such as `us-east-2c` are corrected to regions such as `us-east-2`.
- AWS permission errors and free-tier restrictions are handled gracefully.
- The project can still demonstrate the complete AI decision workflow even when real AWS execution is blocked by account limitations.

## Tech Stack

- Python
- LangGraph
- LangChain
- LlamaIndex
- Qdrant
- OpenAI-compatible LLM API
- AWS SDK for Python (`boto3`)
- python-dotenv

## Project Structure

```text
.
├── agent.py                  # LangGraph optimization workflow
├── tool.py                   # Human-approved AWS execution tool
├── generate_mock.py          # Reproducible dynamic EC2 mock fleet generator
├── fetch_cost_explorer.py    # Optional read-only AWS Cost Explorer exporter
├── fetch_cloudwatch_metrics.py # Optional CloudWatch metrics and EC2 tag enricher
├── fetch_aws_pricing.py      # Optional AWS Pricing API exporter for real EC2 On-Demand prices
├── sync_mock_costs.py        # Sync mock billing costs from structured pricing data
├── analyze_billing.py        # Billing feature analysis and data quality checks
├── build_rag.py              # Local RAG index builder
├── test_llm.py               # LLM connectivity test
├── requirements.txt          # Python dependencies
├── data/
│   ├── mock_billing.json     # Generated mock EC2 billing and utilization data
│   ├── aws_pricing.json      # Structured EC2 pricing, downgrade rules, and constraints
│   └── aws_pricing.md        # Human-readable EC2 pricing and downgrade policy document
└── qdrant_data/              # Local Qdrant vector database
```

## Setup

### 1. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY="your_openai_api_key"
OPENAI_BASE_URL="your_openai_compatible_base_url"

AWS_ACCESS_KEY_ID="your_aws_access_key_id"
AWS_SECRET_ACCESS_KEY="your_aws_secret_access_key"
AWS_DEFAULT_REGION="us-east-2"
```

Do not commit `.env` to GitHub.

### 4. Build the local RAG index

`build_rag.py` loads structured pricing and downgrade rules from `data/aws_pricing.json`, converts them into tagged chunks such as `category=compute`, `scope=ec2`, and `action=downsizing`, and then stores them in Qdrant. The bundled JSON is a local demo baseline; the Markdown pricing document remains as human-readable documentation and fallback context.

To refresh the pricing baseline with real AWS Linux shared-tenancy On-Demand EC2 prices, run the optional AWS Pricing API exporter first:

```bash
python3 fetch_aws_pricing.py --region us-east-1 --output data/aws_pricing.json
```

This only updates the pricing knowledge base. Real rightsizing still requires utilization data from the mock workflow today, or from future CloudWatch / Compute Optimizer enrichment.

```bash
python3 build_rag.py
```

### 5. Generate mock EC2 fleet data

The default workflow uses `generate_mock.py`. This path is free, stable, and reproducible, so it is the recommended demo mode.

```bash
python3 generate_mock.py --fleet-size 60 --seed 42 --output data/mock_billing.json
```

The generator creates a reproducible 50+ instance EC2 fleet with healthy, underutilized, protected, minimum-size, and temporary autoscaling instances. The baseline mock billing file is committed as static demo data, so local development, tests, and offline demos can run without AWS credentials.

To keep the static mock data aligned with current AWS On-Demand prices, let the sync script refresh AWS Pricing API data first and then update the mock billing costs:

```bash
python3 sync_mock_costs.py --refresh-aws-pricing --billing-file data/mock_billing.json --pricing-file data/aws_pricing.json --output data/mock_billing.json
```

This keeps the demo story consistent: simulated utilization with real AWS On-Demand price estimates. If AWS credentials or network access are unavailable, skip `--refresh-aws-pricing` and the workflow will continue using the committed static pricing baseline.

### Optional: export read-only AWS Cost Explorer data

If you want to inspect real AWS billing cost data without replacing the mock demo, run the optional Cost Explorer exporter:

```bash
python3 fetch_cost_explorer.py --start 2026-04-01 --end 2026-05-01 --output data/cost_explorer_billing.json
```

This script only reads AWS Cost Explorer and writes a local JSON file with the same top-level shape as `data/mock_billing.json`. It requires AWS credentials with Cost Explorer read permissions, such as `ce:GetCostAndUsage`. Cost Explorer does not include CPU, memory, ownership, or workload data, so exported records are marked `protected` by default. This makes the exported file suitable for real cost analysis and bill-import demos, but not for automatic downgrade execution.

To add read-only CloudWatch utilization and EC2 tag metadata, enrich the Cost Explorer export:

```bash
python3 fetch_cloudwatch_metrics.py --billing-file data/cost_explorer_billing.json --region us-east-1 --output data/cloudwatch_enriched_billing.json
```

This requires `cloudwatch:GetMetricData`, `cloudwatch:GetMetricStatistics`, `cloudwatch:ListMetrics`, `ec2:DescribeInstances`, `ec2:DescribeTags`, and `ec2:DescribeRegions`. Default EC2 CloudWatch metrics include CPU, network, and disk activity, but not memory. Enriched records remain protected when memory is missing, so they are safe for cost and utilization review without automatic rightsizing execution.

To try the agent against the enriched CloudWatch file without replacing the mock demo input, pass it explicitly:

```bash
python3 tool.py --dry-run --billing-file data/cloudwatch_enriched_billing.json
```

To try the agent against the exported Cost Explorer file without replacing the mock demo input, pass it explicitly:

```bash
python3 tool.py --dry-run --billing-file data/cost_explorer_billing.json
```

### 6. Analyze billing features before optimization

Run the feature analysis script to inspect utilization distribution, average utilization by instance type, cost share, low-load high-cost anomalies, and data quality before generating execution plans:

```bash
python3 analyze_billing.py --billing-file data/mock_billing.json --output data/billing_analysis.json
```

The output helps prioritize meaningful savings opportunities and flags whether the billing file has enough utilization coverage for rightsizing. Cost Explorer exports can also be analyzed this way, but they remain protected cost-only records until CloudWatch or Compute Optimizer utilization data is joined.

### 7. Run the optimization workflow

```bash
python3 tool.py --dry-run
```

Dry-run mode is the default and only generates the optimization report and AWS action plan. It does not modify any AWS resources.

To explicitly run with the default dry-run behavior, use `--dry-run`. To attempt a real EC2 resize after human confirmation, use:

```bash
python3 tool.py --execute
```

The recommended demo chain is:

```bash
python3 fetch_aws_pricing.py --region us-east-1 --output data/aws_pricing.json
python3 generate_mock.py --fleet-size 60 --seed 42 --output data/mock_billing.json
python3 sync_mock_costs.py --billing-file data/mock_billing.json --pricing-file data/aws_pricing.json --output data/mock_billing.json
python3 build_rag.py
python3 analyze_billing.py --billing-file data/mock_billing.json
python3 tool.py --dry-run --billing-file data/mock_billing.json
```

The workflow will:

1. Generate or refresh mock billing data in `data/mock_billing.json` with `generate_mock.py`.
2. Optionally export real read-only AWS Cost Explorer data to a separate JSON file for manual experiments.
3. Load billing data from `data/mock_billing.json`.
4. Analyze which EC2 instances are underutilized and which resources should not be changed.
5. Retrieve relevant pricing rules from the local knowledge base.
6. Generate a fleet-level cost optimization report.
7. Generate dry-run AWS action plans by default for eligible instances.

In dry-run mode, no AWS change will be made.

In execute mode, the tool will ask for human approval before attempting to stop the EC2 instance, modify its instance type, and restart it. This may be blocked by AWS account permissions or free-tier restrictions.

## Example Output

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

## Why This Project Matters

This project demonstrates skills that are directly relevant to AI infrastructure and cloud engineering roles:

- Building agentic workflows with LangGraph
- Applying RAG to business and infrastructure documents
- Working with cloud automation through AWS SDKs
- Designing human-in-the-loop systems for safe AI execution
- Translating AI output into measurable business value
- Handling real-world cloud constraints such as regions, permissions, and account limits

## Future Work

Planned extensions:

- Generate monthly enterprise cost optimization reports
- Add richer AWS Cost Explorer integration with utilization enrichment
- Support additional AWS resources such as RDS, EBS, and S3
- Generate Terraform plans instead of directly calling AWS APIs
- Add Slack or Feishu approval workflow
- Build a FastAPI + React dashboard
- Add unit tests for agent nodes, pricing logic, and AWS tool behavior

## Resume Summary

Built CloudOptix, an AI-powered FinOps agent that analyzes AWS EC2 fleet billing and utilization data, retrieves pricing policies through a Qdrant-based RAG pipeline, and uses LangGraph multi-agent orchestration to generate fleet-level cost optimization plans with human approval before execution.
