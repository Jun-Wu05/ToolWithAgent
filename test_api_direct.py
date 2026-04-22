"""
直接测试Siliconflow API

用于诊断API调用是否正常
"""

import os
import requests
import json
from pathlib import Path
from dotenv import load_dotenv

# 加载.env
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

api_key = os.getenv("SILICONFLOW_API_KEY")
print(f"API Key: {api_key[:10]}..." if api_key else "NOT SET")

url = "https://api.siliconflow.cn/v1/chat/completions"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

data = {
    "model": "deepseek-ai/DeepSeek-V3.2",
    "messages": [
        {"role": "user", "content": "你好"}
    ],
    "stream": False
}

print("\n" + "=" * 60)
print("测试Siliconflow API直接调用")
print("=" * 60)

try:
    print("发送请求...")
    response = requests.post(url, headers=headers, json=data, timeout=30)
    print(f"状态码: {response.status_code}")
    print(f"响应: {response.text[:500]}")
except Exception as e:
    print(f"错误: {str(e)}")

print("=" * 60)
