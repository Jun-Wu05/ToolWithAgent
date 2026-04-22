"""
数据映射智能助手 - Chainlit聊天界面

核心特点：
1. 对话式交互，Agent通过聊天与用户沟通
2. 支持在聊天中拖拽上传文件
3. 与Agno Team无缝集成

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
print(f"[DEBUG] sys.path[0]: {sys.path[0]}")
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


# ============= 辅助函数 =============

def decode_base64_content(content: str) -> dict:
    """解码Base64内容"""
    from agent.core.agent import simple_decode
    return simple_decode(content)


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
        "pending_mapping": None,
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
    处理用户消息
    
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
    response_parts = []
    
    # 处理上传的文件
    if message.elements:
        for element in message.elements:
            if hasattr(element, 'type') and element.type == "file":
                try:
                    # 下载文件内容
                    file_content = await element.download()
                    
                    # 解码Base64内容
                    if isinstance(file_content, bytes):
                        file_content = file_content.decode('utf-8', errors='ignore')
                    
                    result = decode_base64_content(file_content)
                    
                    if result["status"] == "success":
                        user_session["decoded_data"] = result["decoded_json"]
                        user_session["decoded_fields"] = result["fields"]
                        user_session["original_log"] = result["original_log"]
                        
                        field_count = result["field_count"]
                        response_parts.append(f"""✅ **文件解码成功！**

📊 **解码结果：**
- 字段数量：{field_count} 个
- JSON结构：{len(result['decoded_json'])} 个顶层字段

现在可以直接发送消息进行字段映射、威胁类型处理等操作。""")
                    else:
                        response_parts.append(f"❌ 解码失败：{result.get('error_message', '未知错误')}")
                        
                except Exception as e:
                    logger.error(f"文件处理异常: {str(e)}")
                    response_parts.append(f"❌ 文件处理失败：{str(e)}")
    
    # 处理文本消息
    user_text = message.content.strip()
    if user_text:
        user_lower = user_text.lower()
        
        # 检查是否有解码数据
        has_data = user_session["decoded_data"] or user_session["decoded_fields"]
        
        if any(k in user_lower for k in ["映射", "map", "字段"]):
            # 字段映射
            response_parts.append(await generate_field_mapping(user_session))
            
        elif any(k in user_lower for k in ["威胁", "threat", "攻击"]):
            # 威胁类型
            response_parts.append(await generate_threat_mapping(user_session))
            
        elif any(k in user_lower for k in ["枚举", "enum"]):
            # 枚举处理
            response_parts.append(await generate_enum_mapping(user_session))
            
        elif any(k in user_lower for k in ["查看", "显示", "show"]):
            # 查看数据
            response_parts.append(show_decoded_data(user_session))
            
        elif has_data:
            # 带上下文调用Agent
            response_parts.append(await call_agent_with_context(user_session, user_text))
        else:
            # 无数据时的通用处理
            response_parts.append("📋 暂无数据。请先上传Base64数据文件，然后告诉我需要执行什么操作（映射/威胁/枚举）。")
    
    # 发送响应
    final_response = "\n\n".join(filter(None, response_parts))
    if not final_response:
        final_response = "请上传文件或发送消息。"
    
    await cl.Message(content=final_response).send()


# ============= 功能函数 =============

async def generate_field_mapping(user_session: dict) -> str:
    """生成字段映射"""
    import sys, os
    _root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    import json
    from agent.prompts import load_standard_fields
    
    decoded_json = user_session.get("decoded_data")
    fields = user_session.get("decoded_fields")
    
    if not decoded_json and not fields:
        return "⚠️ 没有可用的解码数据"
    
    try:
        standard_fields = load_standard_fields()
        fields_str = ", ".join(str(f) for f in fields) if fields else "无"
        json_content = json.dumps(decoded_json, ensure_ascii=False, indent=2)[:3000] if decoded_json else "无"
        
        prompt = f"""你是一个字段映射专家。请根据以下信息，生成字段映射表：

## 任务
将原始日志中的字段映射到标准字段表中的中文系统属性名称。

## 输入数据

**原始日志 JSON：**
```json
{json_content}
```

**提取的原始字段列表：**
{fields_str}

## 标准字段表（只能使用以下中文名称）
```
{standard_fields}
```

## 映射规则
1. 只能使用标准字段表中的中文系统属性名称
2. 禁止自造字段名、禁止翻译字段名
3. 优先利用标准字段表中的"对象"列缩小匹配范围

## 输出要求
只输出以下格式的Markdown表格，不输出其他内容：

| 原始字段名 | 系统属性名称 | 匹配状态/说明 |
|-----------|-------------|--------------|
| 原始字段1 | 标准字段1 | 匹配成功 |
| 原始字段2 | 未匹配 | 未匹配 |

请生成映射表："""
        
        team = user_session["team"]
        result = team.run(prompt)
        
        user_session["pending_mapping"] = str(result)
        
        return f"📋 **字段映射表已生成：**\n\n{result}\n\n---\n请确认映射表是否正确，或告诉我需要修改。"
        
    except Exception as e:
        logger.error(f"字段映射异常: {str(e)}")
        return f"❌ 生成映射表异常：{str(e)}"


async def generate_threat_mapping(user_session: dict) -> str:
    """生成威胁类型映射"""
    import sys, os
    _root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    import json
    decoded_json = user_session.get("decoded_data")
    
    if not decoded_json:
        return "⚠️ 没有可用的解码数据"
    
    try:
        prompt = f"""分析以下数据中的威胁类型，并进行标准化：

**数据：**
```json
{json.dumps(decoded_json, ensure_ascii=False, indent=2)[:3000]}
```

请识别所有威胁相关字段，并按照标准威胁类型进行映射。

输出格式：
| 原始字段 | 原始值 | 标准威胁类型 | 说明 |
|---------|--------|-------------|------|
| xxx | xxx | xxx | - |"""
        
        team = user_session["team"]
        result = team.run(prompt)
        
        return f"🛡️ **威胁类型映射结果：**\n\n{result}"
        
    except Exception as e:
        logger.error(f"威胁类型处理异常: {str(e)}")
        return f"❌ 威胁类型处理异常：{str(e)}"


async def generate_enum_mapping(user_session: dict) -> str:
    """生成枚举映射"""
    import sys, os
    _root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    import json
    decoded_json = user_session.get("decoded_data")
    fields = user_session.get("decoded_fields")
    
    if not decoded_json and not fields:
        return "⚠️ 没有可用的解码数据"
    
    try:
        fields_str = ", ".join(str(f) for f in fields) if fields else "无"
        
        prompt = f"""处理枚举字段的标准化：

**数据：**
```json
{json.dumps(decoded_json, ensure_ascii=False, indent=2)[:3000] if decoded_json else '无'}
```

**字段列表：**
{fields_str}

请识别枚举类型字段，并标准化其值。"""
        
        team = user_session["team"]
        result = team.run(prompt)
        
        return f"🔢 **枚举字段处理结果：**\n\n{result}"
        
    except Exception as e:
        logger.error(f"枚举处理异常: {str(e)}")
        return f"❌ 枚举处理异常：{str(e)}"


def show_decoded_data(user_session: dict) -> str:
    """显示解码数据"""
    import json
    decoded_fields = user_session.get("decoded_fields")
    decoded_data = user_session.get("decoded_data")
    
    if not decoded_data and not decoded_fields:
        return "⚠️ 没有解码数据"
    
    parts = []
    
    if decoded_fields:
        parts.append(f"**字段列表（共 {len(decoded_fields)} 个）：**\n")
        for i, field in enumerate(decoded_fields[:20], 1):
            parts.append(f"{i}. `{field}`")
        if len(decoded_fields) > 20:
            parts.append(f"... 还有 {len(decoded_fields) - 20} 个字段")
    
    if decoded_data:
        parts.append(f"\n**JSON数据（前2000字符）：**\n```json\n{json.dumps(decoded_data, ensure_ascii=False, indent=2)[:2000]}\n```")
    
    return "\n".join(parts)


async def call_agent_with_context(user_session: dict, user_message: str) -> str:
    """带上下文的Agent调用"""
    import sys, os
    _root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    import json
    decoded_json = user_session.get("decoded_data")
    fields = user_session.get("decoded_fields")
    
    prompt = f"""当前已解码数据：

**字段列表：**
{', '.join(str(f) for f in fields) if fields else '无'}

**JSON数据：**
```json
{json.dumps(decoded_json, ensure_ascii=False, indent=2)[:2000] if decoded_json else '无'}
```

**用户请求：**
{user_message}

请根据以上上下文，处理用户的请求。"""
    
    try:
        team = user_session["team"]
        result = team.run(prompt)
        return str(result)
    except Exception as e:
        logger.error(f"Agent调用异常: {str(e)}")
        return f"❌ 处理异常：{str(e)}"
