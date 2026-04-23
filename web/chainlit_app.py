"""
数据映射智能助手 - Chainlit聊天界面

核心特点：
1. 对话式交互，Agent通过聊天与用户沟通
2. 支持在聊天中拖拽上传文件
3. 与Agno Team无缝集成（纯UI层）

使用方法：
1. 设置环境变量 SILICONFLOW_API_KEY 或在.env文件
2. 运行: chainlit run web/chainlit_app.py
"""

# === CRITICAL: 这必须在所有其他导入之前 ===
import sys
import os

# 获取项目根目录（web的父目录）
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_current_dir)

# 确保项目根目录在sys.path的最前面
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# 验证路径
print(f"[DEBUG] 项目根目录: {_project_root}")
print(f"[DEBUG] agent目录存在: {os.path.exists(os.path.join(_project_root, 'agent'))}")
# =========================================

# 加载.env文件
from dotenv import load_dotenv
load_dotenv()

import chainlit as cl

# 初始化日志
from src.logger import get_logger
logger = get_logger("chainlit_app")
logger.info("=" * 60)
logger.info("Chainlit聊天式Web应用启动")
logger.info("=" * 60)


# ============= Chainlit 事件处理 =============

@cl.on_chat_start
async def start():
    """聊天开始时初始化"""
    # 创建用户会话状态
    user_session = {
        "team": None,
        "decoded_data": None,
        "decoded_fields": None,
        "original_log": None,
    }
    cl.user_session.set("user_session", user_session)
    
    # 发送欢迎消息
    await cl.Message(
        content="""👋 **数据映射智能助手已就绪！**

📋 **功能说明：**
- **上传文件**：支持拖拽或点击上传 Base64/TXT/JSON/Excel 文件
- **字段映射**：发送"映射"生成字段映射表
- **威胁类型**：发送"威胁"进行威胁类型标准化
- **枚举处理**：发送"枚举"处理枚举字段

请上传数据文件或直接发送消息开始对话。""",
    ).send()


@cl.on_message
async def main(message: cl.Message):
    """
    处理用户消息 - 纯UI层
    
    Args:
        message: 用户消息，包含文本和可能上传的文件
    """
    # 重新设置sys.path（Chainlit可能在不同线程中运行）
    import sys, os
    _root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    
    user_session = cl.user_session.get("user_session")
    
    # 初始化Team
    if user_session["team"] is None:
        try:
            from agent.core.team import create_data_mapping_team
            user_session["team"] = create_data_mapping_team()
            logger.info("✅ Team初始化成功")
        except ValueError as e:
            await cl.Message(content=f"❌ Team初始化失败: {str(e)}").send()
            return
        except Exception as e:
            logger.error(f"❌ Team初始化失败: {str(e)}")
            await cl.Message(content=f"❌ Team初始化失败: {str(e)}").send()
            return
    
    team = user_session["team"]
    
    # 处理上传的文件
    if message.elements:
        for element in message.elements:
            if hasattr(element, 'type') and element.type == "file":
                await handle_file_upload(user_session, element)
    
    # 处理文本消息 - 纯UI，直接传递给Team
    user_text = message.content.strip()
    if user_text:
        await handle_user_message(user_session, team, user_text)


# ============= 文件处理 =============

async def handle_file_upload(user_session: dict, element):
    """处理文件上传"""
    try:
        # 获取文件路径并读取内容
        if hasattr(element, 'path') and element.path:
            with open(element.path, 'r', encoding='utf-8', errors='ignore') as f:
                file_content = f.read()
        elif hasattr(element, 'content'):
            file_content = element.content
            if isinstance(file_content, bytes):
                file_content = file_content.decode('utf-8', errors='ignore')
        else:
            file_content = str(element)
        
        # 解码Base64内容
        from agent.core.agent import simple_decode
        result = simple_decode(file_content)
        
        if result["status"] == "success":
            user_session["decoded_data"] = result["decoded_json"]
            user_session["decoded_fields"] = result["fields"]
            user_session["original_log"] = result["original_log"]
            
            field_count = result["field_count"]
            await cl.Message(
                content=f"""✅ **文件解码成功！**

📊 **解码结果：**
- 字段数量：{field_count} 个
- JSON结构：{len(result['decoded_json'])} 个顶层字段

现在可以直接发送消息进行字段映射、威胁类型处理等操作。"""
            ).send()
        else:
            await cl.Message(content=f"❌ 解码失败：{result.get('error_message', '未知错误')}").send()
            
    except Exception as e:
        logger.error(f"文件处理异常: {str(e)}")
        await cl.Message(content=f"❌ 文件处理失败：{str(e)}").send()


# ============= 用户消息处理 =============

async def handle_user_message(user_session: dict, team, user_text: str):
    """处理用户消息 - 纯UI层，传递给Team处理"""
    user_lower = user_text.lower()
    
    # 检查是否有解码数据
    has_data = user_session.get("decoded_data") or user_session.get("decoded_fields")
    
    # 构建用户输入
    if has_data:
        # 有数据时，附带上下文
        import json
        decoded_json = user_session.get("decoded_data")
        fields = user_session.get("decoded_fields")
        
        fields_str = ", ".join(str(f) for f in fields) if fields else "无"
        json_preview = json.dumps(decoded_json, ensure_ascii=False, indent=2)[:2000] if decoded_json else "无"
        
        full_input = f"""用户请求：{user_text}

已上传数据的字段列表：
{fields_str}

数据预览：
{json_preview}

请根据用户请求处理。"""
    else:
        # 无数据时，直接传递用户输入
        full_input = user_text
    
    # 调用Team处理（创建流式消息）
    msg = cl.Message(content="")
    await msg.send()
    
    try:
        # 使用Team处理
        import asyncio
        result = await asyncio.to_thread(team.run, full_input)
        
        # 提取内容并流式输出
        result_content = result.content if hasattr(result, 'content') else str(result)
        
        # 逐字符/逐块输出（模拟流式）
        for i in range(0, len(result_content), 50):
            chunk = result_content[i:i+50]
            await msg.stream_token(chunk)
        
        await msg.update()
        
    except Exception as e:
        logger.error(f"Team调用异常: {str(e)}")
        await cl.Message(content=f"❌ 处理异常：{str(e)}").send()
