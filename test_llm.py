import os
import json
from pydantic import SecretStr
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

# 1. 加载 .env 文件中的环境变量 (你的 API Key)
load_dotenv()

# 2. 初始化大模型 (如果你用的是 GPT-4o)
llm = ChatOpenAI(
    model="gpt-5.2",  # 直接替换为你服务商提供的模型代号
    temperature=0,
    api_key=SecretStr(os.environ.get("OPENAI_API_KEY", "")), # 包装成 SecretStr
    base_url=os.environ.get("OPENAI_BASE_URL")
)

def main():
    print("正在加载本地测试数据...")
    
    # 3. 读取我们刚刚创建的假数据
    file_path = "data/mock_billing.json" # 如果是网安方向，请改成 mock_alert.json
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ 找不到文件: {file_path}，请检查路径！")
        return

    # 4. 构建给大模型的 Prompt
    prompt = f"""
    你是一个资深的云架构师（或安全专家）。
    请阅读以下 JSON 数据，用一句话概括核心问题：
    
    {json.dumps(data, indent=2)}
    """
    
    print("正在呼叫大模型...\n")
    
    # 5. 发送请求并打印结果
    response = llm.invoke([HumanMessage(content=prompt)])
    
    print("🤖 大模型的回复:")
    print("-" * 30)
    print(response.content)
    print("-" * 30)

if __name__ == "__main__":
    main()