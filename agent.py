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


PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / ".env"
QDRANT_PATH = PROJECT_ROOT / "qdrant_data"
BILLING_PATH = PROJECT_ROOT / "data" / "mock_billing.json"
PRICING_DOC_PATH = PROJECT_ROOT / "data" / "aws_pricing.md"
COLLECTION_NAME = "aws_pricing"
EMBED_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
LLM_MODEL_NAME = "gpt-5.4"

load_dotenv(dotenv_path=ENV_PATH)
qdrant_clients: list[qdrant_client.QdrantClient] = []


# ==========================================
# 1. 定义全局状态 (共享白板)
# ==========================================
class AgentState(TypedDict, total=False):
    billing_data: dict[str, Any]  # 原始 JSON 账单
    needs_optimization: bool  # 是否需要优化
    rag_context: str  # 从数据库查到的规则
    final_report: str  # 最终生成的报告


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


def read_pricing_doc() -> str:
    if not PRICING_DOC_PATH.exists():
        fatal(f"找不到本地价格文档：{PRICING_DOC_PATH}")
    return PRICING_DOC_PATH.read_text(encoding="utf-8").strip()


def configure_embedding_model() -> None:
    try:
        # 强制 LlamaIndex 检索时使用 Step 2 建库时同一个本地 Embedding 模型。
        Settings.embed_model = HuggingFaceEmbedding(
            model_name=EMBED_MODEL_NAME,
            local_files_only=True,
        )
    except Exception as exc:
        fatal(f"加载本地 Embedding 模型失败：{exc}")


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


# ==========================================
# 2. 初始化大模型和 RAG 引擎 (全局就绪)
# ==========================================
print("⚙️ 正在启动 AI 团队及挂载本地数据库...")

configure_embedding_model()
llm = build_llm()
retriever = build_retriever()
pricing_doc = read_pricing_doc()


# ==========================================
# 3. 定义各个 Agent 节点的工作逻辑
# ==========================================
def inspector_node(state: AgentState) -> AgentState:
    """节点 1：巡检员。判断利用率是否过低。"""
    print("👀 [Inspector] 正在审阅账单...")
    data = state["billing_data"]
    cpu_str = str(data.get("metrics", {}).get("avg_cpu_utilization", "100%"))

    try:
        cpu_val = float(cpu_str.strip().strip("%"))
    except ValueError:
        fatal(f"账单中的 avg_cpu_utilization 无法解析：{cpu_str!r}")

    # CPU 小于 10% 认定为浪费。
    is_waste = cpu_val < 10.0
    print(f"👀 [Inspector] 发现 CPU 利用率为 {cpu_val}%，需要优化: {is_waste}")
    return {"needs_optimization": is_waste}


def researcher_node(state: AgentState) -> AgentState:
    """节点 2：研究员。从本地知识库查价格规则。"""
    print("📚 [Researcher] 正在查询内部计费文档...")
    instance_type = state["billing_data"].get("instance_type")
    if not instance_type:
        fatal("账单缺少 instance_type，无法查询降级规则。")

    query = f"{instance_type} 降级标准是什么？降级两档后的型号和价格各是多少？"

    if retriever is None:
        context = pricing_doc
    else:
        try:
            nodes = retriever.retrieve(query)
        except Exception as exc:
            print(f"⚠️ 查询向量数据库失败，将改用 Markdown 价格文档。原因：{exc}")
            context = pricing_doc
        else:
            context = "\n\n".join(node.node.get_content() for node in nodes).strip()

    if not context:
        fatal(f"本地知识库没有检索到 {instance_type} 的降级规则。")

    print("📚 [Researcher] 已获取最新价格政策！")
    return {"rag_context": context}


def advisor_node(state: AgentState) -> AgentState:
    """节点 3：架构师。撰写最终报告。"""
    print("✍️  [Advisor] 正在撰写成本优化执行方案...")
    data = state["billing_data"]
    context = state["rag_context"]

    sys_msg = SystemMessage(content="你是一名资深的 FinOps 云架构师。")
    prompt = f"""
请基于以下云服务器账单信息和我们的内部降级规则，写一份简明的 Markdown 优化报告。

【原始账单】
{json.dumps(data, indent=2, ensure_ascii=False)}

【知识库规则与价格】
{context}

要求：包含当前现状、建议动作、以及预计每月节省金额。
"""

    try:
        response = llm.invoke([sys_msg, HumanMessage(content=prompt)])
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
