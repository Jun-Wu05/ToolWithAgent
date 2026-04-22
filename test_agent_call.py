"""
Agent调用测试脚本

用于诊断Agent调用是否正常
"""

import os
import sys
import time
from pathlib import Path

# 加载.env文件
from dotenv import load_dotenv
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

print(f"API Key: {os.getenv('SILICONFLOW_API_KEY', 'NOT SET')[:10]}..." if os.getenv("SILICONFLOW_API_KEY") else "API Key: NOT SET")

from agent.core.agent import create_agent


def test_agent_call():
    """测试Agent调用"""
    print("=" * 60)
    print("开始测试Agent调用")
    print("=" * 60)
    
    # 创建Agent
    print("1. 创建Agent...")
    start = time.time()
    agent = create_agent(user_id="test_user")
    print(f"   Agent创建成功: {agent.name}")
    print(f"   耗时: {time.time() - start:.2f}秒")
    
    # 简单测试
    print("\n2. 测试简单调用...")
    start = time.time()
    print("   发送: '你好'")
    
    try:
        response = agent.run("你好")
        elapsed = time.time() - start
        print(f"   ✅ 成功!")
        print(f"   耗时: {elapsed:.2f}秒")
        print(f"   响应: {response.content if hasattr(response, 'content') else response}")
    except Exception as e:
        print(f"   ❌ 失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    # 测试Base64解码
    print("\n3. 测试Base64解码...")
    test_b64 = "eyJ0ZXN0IjoidmFsdWUifQ=="  # {"test":"value"}
    start = time.time()
    print(f"   发送: '解码这个Base64: {test_b64}'")
    
    try:
        response = agent.run(f"解码这个Base64: {test_b64}")
        elapsed = time.time() - start
        print(f"   ✅ 成功!")
        print(f"   耗时: {elapsed:.2f}秒")
        print(f"   响应: {response.content[:300] if hasattr(response, 'content') else str(response)[:300]}")
    except Exception as e:
        print(f"   ❌ 失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n" + "=" * 60)
    print("✅ 所有测试通过!")
    print("=" * 60)
    return True


if __name__ == "__main__":
    test_agent_call()
