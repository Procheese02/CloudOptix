import json
import os
import sys
import warnings
from pathlib import Path
from typing import Any, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

warnings.filterwarnings(
    "ignore",
    message="The default value of `allowed_objects` will change in a future version.*",
)

from langgraph.graph import END, START, StateGraph
from llama_index.core import Settings, VectorStoreIndex
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAIError
import qdrant_client

import analyze_billing


PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / ".env"
QDRANT_PATH = PROJECT_ROOT / "qdrant_data"
BILLING_PATH = PROJECT_ROOT / "data" / "mock_billing.json"
PRICING_DOC_PATH = PROJECT_ROOT / "data" / "aws_pricing.md"
PRICING_JSON_PATH = PROJECT_ROOT / "data" / "aws_pricing.json"
COLLECTION_NAME = "aws_pricing"
EMBED_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
LLM_MODEL_NAME = "gpt-5.4"
INSTANCE_DOWNGRADE_ORDER = [
    "t3.micro",
    "t3.small",
    "t3.medium",
    "t3.large",
    "t3.xlarge",
    "t3.2xlarge",
]

load_dotenv(dotenv_path=ENV_PATH)
qdrant_clients: list[qdrant_client.QdrantClient] = []
llm: ChatOpenAI | None = None
retriever: Any | None = None
pricing_context: str | None = None
embedding_configured = False
retriever_configured = False


# ==========================================
# 1. 定义全局状态 (共享白板)
# ==========================================
class AgentState(TypedDict, total=False):
    billing_data: dict[str, Any]
    billing_analysis: dict[str, Any]
    enterprise_summary: dict[str, Any]
    data_quality: dict[str, Any]
    top_candidates: list[dict[str, Any]]
    needs_optimization: bool
    optimizable_instances: list[dict[str, Any]]
    protected_instances: list[dict[str, Any]]
    fleet_summary: dict[str, Any]
    rag_context: str
    final_report: str


def fatal(message: str, exit_code: int = 1) -> None:
    """Print a clean, user-facing error and stop the workflow."""
    sys.stdout.flush()
    print(f"\n❌ {message}", file=sys.stderr)
    close_qdrant_clients()
    raise SystemExit(exit_code)


def close_qdrant_clients() -> None:
    while qdrant_clients:
        client = qdrant_clients.pop()
        try:
            client.close()
        except Exception:
            pass


def read_required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        fatal(f"缺少环境变量 {name}。请在 {ENV_PATH} 中配置后再运行。")
    if value.lower() in {"your_api_key", "your_openai_api_key", "sk-xxx", "changeme"}:
        fatal(f"{name} 看起来仍是占位符，请替换成真实可用的 API key。")
    return value


def build_llm() -> ChatOpenAI:
    api_key = read_required_env("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip() or None

    if base_url and not base_url.startswith(("http://", "https://")):
        fatal("OPENAI_BASE_URL 格式不正确，必须以 http:// 或 https:// 开头。")

    return ChatOpenAI(
        model=LLM_MODEL_NAME,
        api_key=api_key,
        base_url=base_url,
        temperature=0,
    )


def read_pricing_context() -> str:
    if PRICING_JSON_PATH.exists():
        return PRICING_JSON_PATH.read_text(encoding="utf-8").strip()
    if PRICING_DOC_PATH.exists():
        return PRICING_DOC_PATH.read_text(encoding="utf-8").strip()
    fatal(f"找不到本地价格知识库：{PRICING_JSON_PATH} 或 {PRICING_DOC_PATH}")


def configure_embedding_model() -> None:
    global embedding_configured
    if embedding_configured:
        return
    try:
        # 强制 LlamaIndex 检索时使用 Step 2 建库时同一个本地 Embedding 模型。
        Settings.embed_model = HuggingFaceEmbedding(
            model_name=EMBED_MODEL_NAME,
            local_files_only=True,
        )
    except Exception as exc:
        fatal(f"加载本地 Embedding 模型失败：{exc}")
    embedding_configured = True


def build_retriever():
    if not QDRANT_PATH.exists():
        print(f"⚠️ 找不到本地向量数据库目录：{QDRANT_PATH}，将改用 Markdown 价格文档。")
        return None

    try:
        client = qdrant_client.QdrantClient(path=str(QDRANT_PATH))
        qdrant_clients.append(client)
        vector_store = QdrantVectorStore(client=client, collection_name=COLLECTION_NAME)
        index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
        return index.as_retriever(similarity_top_k=2)
    except Exception as exc:
        print(f"⚠️ 本地向量检索不可用，将改用 Markdown 价格文档。原因：{exc}")
        return None


def get_llm() -> ChatOpenAI:
    global llm
    if llm is None:
        llm = build_llm()
    return llm


def get_retriever():
    global retriever, retriever_configured
    if not retriever_configured:
        configure_embedding_model()
        retriever = build_retriever()
        retriever_configured = True
    return retriever


def get_pricing_context() -> str:
    global pricing_context
    if pricing_context is None:
        pricing_context = read_pricing_context()
    return pricing_context


def _parse_percent(value: Any, field_name: str) -> float:
    try:
        return float(str(value).strip().strip("%"))
    except ValueError:
        fatal(f"账单中的 {field_name} 无法解析：{value!r}")


def _get_instances(billing_data: dict[str, Any]) -> list[dict[str, Any]]:
    instances = billing_data.get("instances")
    if isinstance(instances, list):
        return instances
    if billing_data.get("instance_id"):
        return [billing_data]
    fatal("账单缺少 instances 列表，无法进行 EC2 fleet 分析。")


def _get_target_instance_type(instance_type: str) -> str | None:
    if instance_type not in INSTANCE_DOWNGRADE_ORDER:
        return None
    current_index = INSTANCE_DOWNGRADE_ORDER.index(instance_type)
    target_index = max(0, current_index - 2)
    if target_index == current_index:
        return None
    return INSTANCE_DOWNGRADE_ORDER[target_index]


def _build_fleet_summary(billing_data: dict[str, Any], optimizable_instances: list[dict[str, Any]]) -> dict[str, Any]:
    billing_analysis = analyze_billing.analyze_billing_data(billing_data)
    enterprise_savings = billing_analysis.get("enterprise_summary", {}).get("enterprise_savings_summary", {})
    if enterprise_savings:
        return {
            "total_monthly_cost": enterprise_savings.get("total_monthly_cost", 0),
            "optimizable_resource_count": enterprise_savings.get("eligible_candidate_count", len(optimizable_instances)),
            "estimated_monthly_savings": enterprise_savings.get("estimated_monthly_savings", 0),
            "top_savings_opportunities": enterprise_savings.get("top_candidates", []),
        }

    instances = _get_instances(billing_data)
    opportunities = []
    total_monthly_cost = sum(float(instance.get("monthly_cost", 0)) for instance in instances)
    estimated_monthly_savings = 0.0

    for instance in optimizable_instances:
        current_type = instance.get("instance_type", "")
        target_type = _get_target_instance_type(current_type)
        current_cost = float(instance.get("monthly_cost", 0))
        target_monthly_cost = None
        estimated_savings = 0.0

        if target_type:
            target_monthly_cost = current_cost / 4
            estimated_savings = current_cost - target_monthly_cost
            estimated_monthly_savings += estimated_savings

        opportunities.append({
            "instance_id": instance.get("instance_id"),
            "current_type": current_type,
            "target_type": target_type,
            "monthly_cost": current_cost,
            "estimated_monthly_savings": round(estimated_savings, 2),
            "risk_level": "low" if instance.get("environment") != "production" else "medium",
        })

    return {
        "total_monthly_cost": round(total_monthly_cost, 2),
        "optimizable_resource_count": len(optimizable_instances),
        "estimated_monthly_savings": round(estimated_monthly_savings, 2),
        "top_savings_opportunities": sorted(
            opportunities,
            key=lambda opportunity: opportunity["estimated_monthly_savings"],
            reverse=True,
        ),
    }


def _is_low_utilization(instance: dict[str, Any]) -> bool:
    return analyze_billing.is_low_utilization(instance)


# ==========================================
# 3. 定义各个 Agent 节点的工作逻辑
# ==========================================
def inspector_node(state: AgentState) -> AgentState:
    print("👀 [Inspector] 正在审阅 EC2 fleet 账单...")
    billing_data = state["billing_data"]
    instances = _get_instances(billing_data)
    billing_analysis = analyze_billing.analyze_billing_data(billing_data)
    enterprise_summary = billing_analysis.get("enterprise_summary", {})
    enterprise_savings = enterprise_summary.get("enterprise_savings_summary", {})
    candidate_ids = {
        candidate["instance_id"]
        for candidate in analyze_billing.savings_candidates(billing_data, instances)
    }
    optimizable_instances = []
    protected_instances = []

    for instance in instances:
        instance_id = instance.get("instance_id", "unknown")
        low_utilization = _is_low_utilization(instance)
        protected = bool(instance.get("protected"))

        if instance_id in candidate_ids:
            optimizable_instances.append(instance)
            print(f"👀 [Inspector] {instance_id} 利用率偏低，可进入优化候选。")
        elif low_utilization and protected:
            protected_instances.append(instance)
            print(f"👀 [Inspector] {instance_id} 利用率偏低，但已标记为不该动。")
        else:
            protected_instances.append({
                **instance,
                "do_not_touch_reason": "utilization is not low enough for downgrade",
            })
            print(f"👀 [Inspector] {instance_id} 利用率健康，不建议调整。")

    print(f"👀 [Inspector] 可优化资源 {len(optimizable_instances)} 个，不建议调整资源 {len(protected_instances)} 个。")
    fleet_summary = _build_fleet_summary(billing_data, optimizable_instances)
    return {
        "billing_analysis": billing_analysis,
        "enterprise_summary": enterprise_summary,
        "data_quality": billing_analysis.get("data_quality", {}),
        "top_candidates": enterprise_savings.get("top_candidates", []),
        "needs_optimization": bool(optimizable_instances),
        "optimizable_instances": optimizable_instances,
        "protected_instances": protected_instances,
        "fleet_summary": fleet_summary,
    }


def researcher_node(state: AgentState) -> AgentState:
    print("📚 [Researcher] 正在查询内部计费文档...")
    instance_types = sorted({
        instance.get("instance_type", "")
        for instance in state.get("optimizable_instances", [])
        if instance.get("instance_type")
    })
    if not instance_types:
        fatal("没有可优化实例类型，无法查询降级规则。")

    query = "、".join(instance_types) + " 降级标准是什么？降级两档后的型号和价格各是多少？"

    active_retriever = get_retriever()
    if active_retriever is None:
        context = get_pricing_context()
    else:
        try:
            nodes = active_retriever.retrieve(query)
        except Exception as exc:
            print(f"⚠️ 查询向量数据库失败，将改用 Markdown 价格文档。原因：{exc}")
            context = get_pricing_context()
        else:
            context = "\n\n".join(node.node.get_content() for node in nodes).strip()

    if not context:
        fatal(f"本地知识库没有检索到 {', '.join(instance_types)} 的降级规则。")

    print("📚 [Researcher] 已获取最新价格政策！")
    return {"rag_context": context}


def _top_rows(value: Any, limit: int = 10) -> Any:
    if isinstance(value, list):
        return value[:limit]
    return value


def build_advisor_context(state: AgentState) -> dict[str, Any]:
    billing_data = state["billing_data"]
    billing_analysis = state.get("billing_analysis") or analyze_billing.analyze_billing_data(billing_data)
    enterprise_summary = billing_analysis.get("enterprise_summary", {})
    enterprise_savings = enterprise_summary.get("enterprise_savings_summary", {})

    summarized_enterprise = {
        "cost_by_team_service_environment": _top_rows(enterprise_summary.get("cost_by_team_service_environment", []), 15),
        "cost_by_business_unit": _top_rows(enterprise_summary.get("cost_by_business_unit", []), 10),
        "cost_by_service": _top_rows(enterprise_summary.get("cost_by_service", []), 10),
        "cost_by_region": _top_rows(enterprise_summary.get("cost_by_region", []), 10),
        "cost_by_pricing_model": _top_rows(enterprise_summary.get("cost_by_pricing_model", []), 10),
        "criticality_mix": _top_rows(enterprise_summary.get("criticality_mix", []), 10),
        "utilization_pattern_summary": _top_rows(enterprise_summary.get("utilization_pattern_summary", []), 10),
        "top_waste_owners": _top_rows(enterprise_summary.get("top_waste_owners", []), 10),
        "protected_resources_summary": _top_rows(enterprise_summary.get("protected_resources_summary", []), 10),
        "missing_metrics_coverage": enterprise_summary.get("missing_metrics_coverage", {}),
        "enterprise_savings_summary": {
            **enterprise_savings,
            "top_candidates": _top_rows(enterprise_savings.get("top_candidates", []), 10),
        },
    }

    return {
        "report": {
            "report_id": billing_data.get("report_id"),
            "source": billing_analysis.get("source"),
            "generated_at": billing_analysis.get("generated_at"),
            "resource_type": billing_data.get("resource_type"),
            "primary_region": billing_data.get("region"),
            "fleet_size": billing_analysis.get("fleet_size"),
        },
        "fleet_summary": state.get("fleet_summary", {}),
        "data_quality": billing_analysis.get("data_quality", {}),
        "enterprise_summary": summarized_enterprise,
    }


def build_advisor_prompt(state: AgentState, rag_context: str) -> str:
    advisor_context = build_advisor_context(state)
    return f"""
请基于以下 EC2 fleet 企业级分析摘要和内部降级规则，写一份简明的 Markdown fleet-level 成本优化报告。

【企业级分析上下文】
{json.dumps(advisor_context, indent=2, ensure_ascii=False)}

【知识库规则与价格】
{rag_context}

要求：
1. 输出总月成本、可优化资源数量、预计节省金额和 savings rate。
2. 输出 top savings opportunities，优先使用 enterprise_savings_summary.top_candidates。
3. 说明 top waste owners、受保护资源、缺失指标覆盖率和主要风险。
4. 输出 fleet-level 风险等级和推荐执行顺序。
5. 金额、候选实例、风险等级必须来自企业级分析上下文；不要重新计算或编造实例明细。
"""


def advisor_node(state: AgentState) -> AgentState:
    print("✍️  [Advisor] 正在撰写 fleet-level 成本优化执行方案...")
    context = state["rag_context"]

    sys_msg = SystemMessage(content="你是一名资深的 FinOps 云架构师。")
    prompt = build_advisor_prompt(state, context)

    try:
        response = get_llm().invoke([sys_msg, HumanMessage(content=prompt)])
    except AuthenticationError as exc:
        fatal(f"API key 认证失败，请检查 OPENAI_API_KEY 是否正确。接口返回：{exc}")
    except APIStatusError as exc:
        if exc.status_code in {401, 403}:
            fatal(
                "API key 或账号权限有问题，模型调用被拒绝。"
                f"HTTP {exc.status_code}: {exc.response.text}"
            )
        fatal(f"模型接口返回错误。HTTP {exc.status_code}: {exc.response.text}")
    except APIConnectionError as exc:
        fatal(f"无法连接到模型接口，请检查 OPENAI_BASE_URL 和网络。详情：{exc}")
    except OpenAIError as exc:
        fatal(f"模型接口调用失败：{exc}")

    return {"final_report": response.content}


# ==========================================
# 4. 定义路由逻辑 (条件边)
# ==========================================
def should_optimize(state: AgentState) -> str:
    if state["needs_optimization"]:
        return "researcher"
    return END


# ==========================================
# 5. 编排工作流并编译成图
# ==========================================
workflow = StateGraph(AgentState)

workflow.add_node("inspector", inspector_node)
workflow.add_node("researcher", researcher_node)
workflow.add_node("advisor", advisor_node)

workflow.add_edge(START, "inspector")
workflow.add_conditional_edges("inspector", should_optimize)
workflow.add_edge("researcher", "advisor")
workflow.add_edge("advisor", END)

app = workflow.compile()


# ==========================================
# 6. 主程序运行测试
# ==========================================
def load_billing_data() -> dict[str, Any]:
    if not BILLING_PATH.exists():
        fatal(f"找不到测试账单文件：{BILLING_PATH}")

    try:
        with BILLING_PATH.open("r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as exc:
        fatal(f"账单 JSON 格式错误：{exc}")


def main() -> None:
    print("\n" + "=" * 50)
    print("🚀 CloudOptix 智能体工作流启动")
    print("=" * 50 + "\n")

    initial_state: AgentState = {"billing_data": load_billing_data()}
    final_state = app.invoke(initial_state)

    print("\n[DEBUG] Researcher 从库里翻出了什么原文：")
    print("-" * 30)
    print(final_state.get("rag_context", "没查到或者跳过了"))
    print("-" * 30 + "\n")
    
    if "final_report" in final_state:
        print("\n✅ 最终生成的优化方案：\n")
        print(final_state["final_report"])


    final_report = final_state.get("final_report")
    if final_report:
        print("\n✅ 最终生成的优化方案：\n")
        print(final_report)
    else:
        print("\n✅ 巡检结束：该实例运行良好，无需优化。")


if __name__ == "__main__":
    try:
        main()
    finally:
        close_qdrant_clients()
