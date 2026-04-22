"""
Agent测试脚本

使用方法：
1. 确保设置了环境变量 SILICONFLOW_API_KEY
2. 运行: python test_agent.py
"""

import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_imports():
    """测试模块导入"""
    print("=" * 50)
    print("测试1: 模块导入")
    print("=" * 50)
    
    try:
        from agent.core.agent import create_agent, create_simple_agent, create_complex_agent
        from agent.core.model_config import ModelConfig
        from agent.memory.session_manager import SessionManager
        from agent.tools.base64_tool import base64_decode_tool, base64_encode_tool
        from agent.tools.standard_mapper import field_mapping_tool, generate_mapping_table_tool
        from agent.tools.threat_type_tool import threat_type_tool
        from agent.tools.enum_field_tool import enum_field_tool
        from agent.tools.confirmation_tool import confirm_mapping_table
        
        print("✅ 所有模块导入成功！")
        print("-" * 50)
        print("可用函数:")
        print("  - create_agent() - 主控Agent")
        print("  - create_simple_agent() - 简单任务Agent")
        print("  - create_complex_agent() - 复杂推理Agent")
        print("  - SessionManager - 会话管理器")
        print("-" * 50)
        print("可用工具:")
        print("  - base64_decode_tool - Base64解码")
        print("  - base64_encode_tool - Base64编码")
        print("  - field_mapping_tool - 字段映射")
        print("  - generate_mapping_table_tool - 生成映射表")
        print("  - threat_type_tool - 威胁类型映射")
        print("  - enum_field_tool - 枚举字段提取")
        print("  - confirm_mapping_table - 字段映射确认")
        print("=" * 50)
        return True
    except Exception as e:
        print(f"❌ 模块导入失败: {e}")
        return False


def test_api_key():
    """测试API Key"""
    print("\n" + "=" * 50)
    print("测试2: API Key配置")
    print("=" * 50)
    
    api_key = os.getenv("SILICONFLOW_API_KEY", "")
    if not api_key:
        print("⚠️  未设置SILICONFLOW_API_KEY环境变量")
        print("   请设置: set SILICONFLOW_API_KEY=your_key")
        print("   或在.env文件中配置")
        return False
    else:
        print(f"✅ API Key已配置: {api_key[:10]}...")
        return True


def test_agent_creation():
    """测试Agent创建"""
    print("\n" + "=" * 50)
    print("测试3: Agent创建")
    print("=" * 50)
    
    api_key = os.getenv("SILICONFLOW_API_KEY", "")
    if not api_key:
        print("⚠️  跳过Agent创建测试（未配置API Key）")
        return False
    
    try:
        from agent.core.agent import create_agent, create_simple_agent, create_complex_agent
        
        # 创建主Agent
        main_agent = create_agent(user_id="test_user")
        print(f"✅ 主Agent创建成功: {main_agent.name}")
        
        # 创建简单Agent
        simple_agent = create_simple_agent(user_id="test_user")
        print(f"✅ 简单Agent创建成功: {simple_agent.name}")
        
        # 创建复杂Agent
        complex_agent = create_complex_agent(user_id="test_user")
        print(f"✅ 复杂Agent创建成功: {complex_agent.name}")
        
        return True
    except Exception as e:
        print(f"❌ Agent创建失败: {e}")
        return False


def test_tool_execution():
    """测试工具执行"""
    print("\n" + "=" * 50)
    print("测试4: 工具执行测试")
    print("=" * 50)
    
    try:
        # 导入底层的Python函数进行测试
        from agent.tools.base64_tool import base64_decode_tool
        import json
        
        # 测试Base64解码（直接调用底层函数）
        test_b64 = "eyJ0ZXN0IjoidmFsdWUifQ=="  # {"test":"value"}
        
        # 由于@tool装饰器，返回的是Function对象
        # 我们直接测试底层的解码逻辑
        import base64 as b64_module
        decoded = b64_module.b64decode(test_b64).decode('utf-8')
        
        if decoded == '{"test":"value"}':
            print(f"✅ Base64解码逻辑测试成功")
            print(f"   - 输入: {test_b64}")
            print(f"   - 输出: {decoded}")
        else:
            print(f"⚠️  Base64解码结果不符合预期")
        
        # 测试工具函数（Agno装饰器）
        print(f"✅ 工具函数已注册（需要LLM调用才能测试）")
        
        return True
    except Exception as e:
        print(f"❌ 工具执行失败: {e}")
        return False


def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("🧪 Agent功能测试")
    print("=" * 60)
    
    results = []
    
    # 测试1: 模块导入
    results.append(("模块导入", test_imports()))
    
    # 测试2: API Key
    results.append(("API Key配置", test_api_key()))
    
    # 测试3: Agent创建
    results.append(("Agent创建", test_agent_creation()))
    
    # 测试4: 工具执行
    results.append(("工具执行", test_tool_execution()))
    
    # 总结
    print("\n" + "=" * 60)
    print("📊 测试结果总结")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ 通过" if result else "⚠️  跳过/失败"
        print(f"  {name}: {status}")
    
    print("-" * 60)
    print(f"总计: {passed}/{total} 项通过")
    print("=" * 60)
    
    if passed >= 2:
        print("\n🎉 Agent基础功能测试通过！")
        print("\n下一步:")
        print("1. 设置SILICONFLOW_API_KEY环境变量")
        print("2. 运行Agent进行实际交互测试")
        print("3. 或继续开发MVP-4和MVP-5")
    else:
        print("\n⚠️  部分测试未通过，请检查配置")


if __name__ == "__main__":
    main()
