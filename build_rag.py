import json
import os
from pathlib import Path
from typing import Any

import qdrant_client
from dotenv import load_dotenv
from llama_index.core import Document, Settings, SimpleDirectoryReader, VectorStoreIndex
from llama_index.core.storage.storage_context import StorageContext
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.openai import OpenAI
from llama_index.vector_stores.qdrant import QdrantVectorStore

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
PRICING_JSON_PATH = DATA_DIR / "aws_pricing.json"
QDRANT_PATH = PROJECT_ROOT / "qdrant_data"
COLLECTION_NAME = "aws_pricing"


def common_metadata(pricing_data: dict[str, Any]) -> dict[str, Any]:
    metadata = pricing_data.get("metadata", {})
    return {
        "category": metadata.get("category", "compute"),
        "scope": metadata.get("scope", "ec2"),
        "action": metadata.get("action", "downsizing"),
        "region": metadata.get("region", "unknown"),
        "currency": metadata.get("currency", "USD"),
    }


def build_pricing_documents(pricing_data: dict[str, Any]) -> list[Document]:
    base_metadata = common_metadata(pricing_data)
    documents: list[Document] = []

    for instance_type, details in pricing_data.get("instance_types", {}).items():
        text = (
            f"EC2 instance type {instance_type}: {details['vcpu']} vCPU, "
            f"{details['memory_gib']} GiB memory, hourly price "
            f"${details['hourly_price']}, monthly estimate ${details['monthly_estimate']}."
        )
        documents.append(Document(
            text=text,
            metadata={**base_metadata, "chunk_type": "instance_pricing", "instance_type": instance_type},
        ))

    for rule in pricing_data.get("downgrade_rules", []):
        text = (
            f"Downgrade rule {rule['name']}: average CPU below {rule['avg_cpu_below_percent']}%, "
            f"peak CPU at or below {rule['peak_cpu_at_or_below_percent']}%, memory below "
            f"{rule['avg_memory_below_percent']}%. Recommendation: {rule['recommendation']} "
            f"Downgrade steps: {rule['downgrade_steps']}. Instance order: "
            f"{', '.join(rule['instance_order'])}."
        )
        documents.append(Document(
            text=text,
            metadata={**base_metadata, "chunk_type": "downgrade_rule", "rule_name": rule["name"]},
        ))

    for constraint in pricing_data.get("constraints", []):
        documents.append(Document(
            text=f"Constraint {constraint['name']}: {constraint['description']}",
            metadata={**base_metadata, "chunk_type": "constraint", "constraint_name": constraint["name"]},
        ))

    return documents


def load_pricing_documents(pricing_json_path: Path = PRICING_JSON_PATH) -> list[Document]:
    if pricing_json_path.exists():
        pricing_data = json.loads(pricing_json_path.read_text(encoding="utf-8"))
        return build_pricing_documents(pricing_data)
    return SimpleDirectoryReader(str(DATA_DIR), required_exts=[".md"]).load_data()


def main():
    load_dotenv()
    
    # 1. 配置使用的第三方大模型和 Embedding 模型
    Settings.llm = OpenAI(
        model="gpt-5.4",
        api_base=os.environ.get("OPENAI_BASE_URL"),
        api_key=os.environ.get("OPENAI_API_KEY"),
        temperature=0
    )

    # 2. 负责向量化为本地开源模型 (BAAI/bge-small-zh-v1.5）
    print("正在加载本地 Embedding 模型...")
    Settings.embed_model = HuggingFaceEmbedding(
        model_name="BAAI/bge-small-zh-v1.5"
    )

    print("正在读取结构化 AWS 价格知识库...")
    documents = load_pricing_documents()

    print("正在初始化本地 Qdrant 向量数据库...")
    # 3. 初始化 Qdrant 本地客户端（数据会保存在本地的 qdrant_data 文件夹中）
    client = qdrant_client.QdrantClient(path=str(QDRANT_PATH))
    vector_store = QdrantVectorStore(client=client, collection_name=COLLECTION_NAME)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    print("正在建立索引 (将文档切块并存入数据库)...")
    # 4. 创建 RAG 索引
    index = VectorStoreIndex.from_documents(
        documents,
        storage_context=storage_context,
    )

    print("建立完毕！开始进行检索测试：")
    print("-" * 30)
    
    # 5. 提一个具体的业务问题
    query_engine = index.as_query_engine()
    question = "我的 t3.2xlarge 实例利用率只有 4.2%，根据文档中的降级标准，我应该把它降级成什么？降级后每月能省多少钱？"
    
    print(f"问题: {question}\n")
    response = query_engine.query(question)
    print(f"RAG 引擎的回答:\n{response}")

if __name__ == "__main__":
    main()