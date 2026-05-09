# CloudOptix - AI FinOps Agent for AWS EC2 Cost Optimization

[简体中文](README.zh-CN.md)

CloudOptix is an AI-powered FinOps assistant that analyzes AWS EC2 billing and utilization data, retrieves cloud pricing policies through RAG, and generates cost optimization recommendations with human approval before any infrastructure change.

The project is designed as a practical, job-portfolio-ready AI infrastructure application: it combines cloud automation, RAG, LangGraph agent orchestration, and safe execution controls around a real business problem — reducing cloud waste.

## Problem

Cloud infrastructure is often over-provisioned. Engineering teams may request larger instances for safety, but many resources remain underutilized for long periods, creating unnecessary monthly cloud spend.

CloudOptix helps identify these waste patterns and produces explainable rightsizing recommendations such as:

> Downgrade EC2 instance `i-03ea43d903f366fa5` from `t3.2xlarge` to `t3.large`, with an estimated monthly saving of `$185.28`.

## Solution

CloudOptix uses a multi-agent workflow to:

1. Load mock AWS billing and utilization data.
2. Detect underutilized EC2 instances.
3. Retrieve pricing rules and downgrade policies from a local RAG knowledge base.
4. Generate a Markdown cost optimization report.
5. Optionally prepare and execute an AWS EC2 resize action through `boto3` after human confirmation.

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

## Current MVP Scope

The current version focuses on AWS EC2 rightsizing.

Implemented features:

- Mock AWS billing data ingestion
- Low-utilization instance detection
- Local pricing knowledge base
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
- AWS credentials are loaded from `.env`.
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
├── build_rag.py              # Local RAG index builder
├── test_llm.py               # LLM connectivity test
├── requirements.txt          # Python dependencies
├── data/
│   ├── mock_billing.json     # Mock EC2 billing and utilization data
│   └── aws_pricing.md        # Local EC2 pricing and downgrade policy document
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

```bash
python3 build_rag.py
```

### 5. Run the optimization workflow

```bash
python3 tool.py --dry-run
```

Dry-run mode is the default and only generates the optimization report and AWS action plan. It does not modify any AWS resources.

To explicitly run with the default dry-run behavior, use `--dry-run`. To attempt a real EC2 resize after human confirmation, use:

```bash
python3 tool.py --execute
```

The workflow will:

1. Load billing data from `data/mock_billing.json`.
2. Analyze whether the EC2 instance is underutilized.
3. Retrieve relevant pricing rules from the local knowledge base.
4. Generate a cost optimization report.
5. Generate a dry-run AWS action plan by default.

In dry-run mode, no AWS change will be made.

In execute mode, the tool will ask for human approval before attempting to stop the EC2 instance, modify its instance type, and restart it. This may be blocked by AWS account permissions or free-tier restrictions.

## Example Output

```text
Inspector: CPU utilization is 6.68%, optimization needed: True
Researcher: Retrieved EC2 pricing policy from knowledge base
Advisor: Generated cost optimization report

Recommendation:
Downgrade i-03ea43d903f366fa5 from t3.2xlarge to t3.large
Estimated monthly savings: $185.28

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

- Analyze a fleet of 50+ mock EC2 instances
- Generate monthly enterprise cost optimization reports
- Add AWS Cost Explorer integration
- Support additional AWS resources such as RDS, EBS, and S3
- Generate Terraform plans instead of directly calling AWS APIs
- Add Slack or Feishu approval workflow
- Build a FastAPI + React dashboard
- Add unit tests for agent nodes, pricing logic, and AWS tool behavior

## Resume Summary

Built CloudOptix, an AI-powered FinOps agent that analyzes AWS EC2 billing and utilization data, retrieves pricing policies through a Qdrant-based RAG pipeline, and uses LangGraph multi-agent orchestration to generate cost optimization plans with human approval before execution.
