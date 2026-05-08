import os
from dotenv import load_dotenv
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings
from llama_index.vector_stores.qdrant import QdrantVectorStore
from llama_index.core.storage.storage_context import StorageContext
from llama_index.llms.openai import OpenAI
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
import qdrant_client

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

    print("正在读取 AWS 价格文档...")
    # 2. 读取 data 目录下的 markdown 文件
    documents = SimpleDirectoryReader("./data", required_exts=[".md"]).load_data()

    print("正在初始化本地 Qdrant 向量数据库...")
    # 3. 初始化 Qdrant 本地客户端（数据会保存在本地的 qdrant_data 文件夹中）
    client = qdrant_client.QdrantClient(path="./qdrant_data")
    vector_store = QdrantVectorStore(client=client, collection_name="aws_pricing")
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