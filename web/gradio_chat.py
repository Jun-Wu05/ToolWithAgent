"""
数据映射智能助手 - Gradio聊天界面

核心特点：
1. 对话式交互，Agent通过聊天与用户沟通
2. 支持拖拽上传文件
3. 与Agno Team无缝集成

使用方法：
1. 设置环境变量 SILICONFLOW_API_KEY 或在.env文件
2. 运行: python -m web.gradio_chat 或 gradio web/gradio_chat.py
"""

import os
import sys
import json
import base64
from pathlib import Path
from dotenv import load_dotenv

# 自动加载 .env 文件
load_dotenv()

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gradio as gr
from gradio import File

# 初始化日志
from src.logger import get_logger
logger = get_logger("gradio_chat")
logger.info("=" * 60)
logger.info("Gradio聊天式Web应用启动")
logger.info("=" * 60)


# ============= 全局状态 =============

class ChatState:
    """聊天状态管理"""
    def __init__(self):
        self.team = None
        self.decoded_data = None
        self.decoded_fields = None
        self.original_log = None
        self.pending_mapping = None
        
    def reset(self):
        self.decoded_data = None
        self.decoded_fields = None
        self.original_log = None
        self.pending_mapping = None


# 全局状态
chat_state = ChatState()


# ============= 初始化Team =============

def init_team():
    """初始化Agno Team"""
    if chat_state.team is None:
        try:
            from agent.core.team import create_data_mapping_team
            chat_state.team = create_data_mapping_team()
            logger.info("✅ Team初始化成功")
            return True
        except ValueError as e:
            logger.error(f"❌ Team初始化失败: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"❌ 未知错误: {str(e)}")
            return False
    return True


# ============= 解码函数 =============

def decode_base64_content(content: str) -> dict:
    """解码Base64内容"""
    from agent.core.agent import simple_decode
    return simple_decode(content)


def process_uploaded_file(file) -> str:
    """处理上传的文件"""
    if file is None:
        return None
    
    try:
        # 读取文件内容
        if hasattr(file, 'read'):
            content = file.read()
            if isinstance(content, bytes):
                content = content.decode('utf-8', errors='ignore')
        else:
            content = str(file)
        
        # 检查是否是Base64
        cleaned = "".join(content.split())
        if cleaned and len(cleaned) >= 4:
            result = decode_base64_content(content)
            if result["status"] == "success":
                chat_state.decoded_data = result["decoded_json"]
                chat_state.decoded_fields = result["fields"]
                chat_state.original_log = result["original_log"]
                
                field_count = result["field_count"]
                return f"""✅ **文件解码成功！**

📊 **解码结果：**
- 字段数量：{field_count} 个
- JSON结构：{len(result['decoded_json'])} 个顶层字段

现在可以直接发送消息进行字段映射、威胁类型处理等操作。"""
            else:
                return f"❌ 解码失败：{result.get('error_message', '未知错误')}"
        
        return "⚠️ 文件内容不是有效的Base64格式"
        
    except Exception as e:
        logger.error(f"文件处理异常: {str(e)}")
        return f"❌ 文件处理失败：{str(e)}"


# ============= 文件上传处理 =============

def handle_file_upload(file) -> tuple:
    """处理文件上传，返回消息和可见性更新"""
    if file is None:
        return "请上传文件", gr.update(visible=False)
    
    result = process_uploaded_file(file)
    return result, gr.update(visible=True)


# ============= Chat处理 =============

def process_message(message: str, history: list, file: File = None) -> tuple:
    """
    处理用户消息
    
    Args:
        message: 用户输入的文本
        history: 对话历史
        file: 上传的文件（如果有）
    
    Returns:
        tuple: (response, history)
    """
    # 初始化Team
    if not init_team():
        return "❌ Team初始化失败，请检查环境变量 SILICONFLOW_API_KEY", history
    
    response = ""
    
    # 处理上传的文件
    if file is not None:
        file_result = process_uploaded_file(file)
        if file_result:
            response += file_result + "\n\n"
    
    # 处理文本消息
    if message:
        # 检查状态
        if not chat_state.decoded_data and not chat_state.decoded_fields:
            if any(k in message.lower() for k in ["映射", "map", "字段"]):
                response = "📋 字段映射需要先上传数据文件。\n\n请先在下方上传Base64数据文件，然后告诉我'映射'来生成字段映射表。"
                return response, history
            
            # 非映射请求，发送给Agent
            try:
                result = chat_state.team.run_task(message)
                if result["success"]:
                    response += result["response"]
                else:
                    response += f"❌ 处理失败：{result['error'] or '未知错误'}"
            except Exception as e:
                logger.error(f"Agent处理异常: {str(e)}")
                response += f"❌ 处理异常：{str(e)}"
        else:
            # 有解码数据，检查意图
            user_lower = message.lower().strip()
            
            if any(k in user_lower for k in ["映射", "map", "字段"]):
                # 执行字段映射
                response += generate_field_mapping()
                
            elif any(k in user_lower for k in ["威胁", "threat", "攻击"]):
                # 执行威胁类型处理
                response += generate_threat_mapping()
                
            elif any(k in user_lower for k in ["查看", "显示", "show"]):
                # 显示解码数据
                response += show_decoded_data()
                
            else:
                # 其他请求，带上下文发送给Agent
                response += call_agent_with_context(message)
    
    return response, history


def generate_field_mapping() -> str:
    """生成字段映射"""
    if not chat_state.decoded_data and not chat_state.decoded_fields:
        return "⚠️ 没有可用的解码数据"
    
    try:
        from agent.prompts import load_standard_fields
        
        decoded_json = chat_state.decoded_data
        fields = chat_state.decoded_fields
        
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
        
        result = chat_state.team.run_task(prompt)
        if result["success"]:
            chat_state.pending_mapping = result["response"]
            return f"📋 **字段映射表已生成：**\n\n{result['response']}\n\n---\n请确认映射表是否正确，或告诉我需要修改。"
        else:
            return f"❌ 生成映射表失败：{result['error'] or '未知错误'}"
            
    except Exception as e:
        logger.error(f"字段映射异常: {str(e)}")
        return f"❌ 生成映射表异常：{str(e)}"


def generate_threat_mapping() -> str:
    """生成威胁类型映射"""
    if not chat_state.decoded_data:
        return "⚠️ 没有可用的解码数据"
    
    try:
        from agent.prompts import load_threat_type_prompt
        
        decoded_json = chat_state.decoded_data
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
        
        result = chat_state.team.run_task(prompt)
        if result["success"]:
            return f"🛡️ **威胁类型映射结果：**\n\n{result['response']}"
        else:
            return f"❌ 生成威胁类型映射失败：{result['error'] or '未知错误'}"
            
    except Exception as e:
        logger.error(f"威胁类型处理异常: {str(e)}")
        return f"❌ 威胁类型处理异常：{str(e)}"


def show_decoded_data() -> str:
    """显示解码数据"""
    if not chat_state.decoded_data and not chat_state.decoded_fields:
        return "⚠️ 没有解码数据"
    
    parts = []
    
    if chat_state.decoded_fields:
        parts.append(f"**字段列表（共 {len(chat_state.decoded_fields)} 个）：**\n")
        for i, field in enumerate(chat_state.decoded_fields[:20], 1):
            parts.append(f"{i}. `{field}`")
        if len(chat_state.decoded_fields) > 20:
            parts.append(f"... 还有 {len(chat_state.decoded_fields) - 20} 个字段")
    
    if chat_state.decoded_data:
        parts.append(f"\n**JSON数据（前2000字符）：**\n```json\n{json.dumps(chat_state.decoded_data, ensure_ascii=False, indent=2)[:2000]}\n```")
    
    return "\n".join(parts)


def call_agent_with_context(user_message: str) -> str:
    """带上下文的Agent调用"""
    prompt = f"""当前已解码数据：

**字段列表：**
{', '.join(str(f) for f in chat_state.decoded_fields) if chat_state.decoded_fields else '无'}

**JSON数据：**
```json
{json.dumps(chat_state.decoded_data, ensure_ascii=False, indent=2)[:2000] if chat_state.decoded_data else '无'}
```

**用户请求：**
{user_message}

请根据以上上下文，处理用户的请求。"""
    
    try:
        result = chat_state.team.run_task(prompt)
        if result["success"]:
            return result["response"]
        else:
            return f"❌ 处理失败：{result['error'] or '未知错误'}"
    except Exception as e:
        logger.error(f"Agent调用异常: {str(e)}")
        return f"❌ 处理异常：{str(e)}"


# ============= 清除历史 =============

def clear_history():
    """清除对话历史和状态"""
    chat_state.reset()
    return [], None, None, ""


# ============= 主界面 =============

def create_gradio_app():
    """创建Gradio应用"""
    
    with gr.Blocks(
        title="数据映射智能助手",
    ) as demo:
        gr.Markdown("""
        # 💬 数据映射智能助手
        *对话式交互 · 支持拖拽上传 · 多轮沟通*
        """)
        
        gr.Markdown("""
        ### 📋 功能说明
        - **文件上传**：支持拖拽或点击上传 Base64/TXT/JSON/Excel 文件
        - **字段映射**：上传数据后，发送"映射"生成字段映射表
        - **威胁类型**：发送"威胁"进行威胁类型标准化
        - **智能对话**：支持多轮对话交互
        """)
        
        with gr.Row():
            with gr.Column(scale=3):
                # 聊天界面
                chatbot = gr.Chatbot(
                    label="对话历史",
                    height=500,
                )
                
                with gr.Row():
                    msg_input = gr.Textbox(
                        label="输入消息",
                        placeholder="输入消息或描述您的需求...",
                        scale=4,
                    )
                    submit_btn = gr.Button("发送", variant="primary", scale=1)
            
            with gr.Column(scale=1):
                # 文件上传
                file_input = gr.File(
                    label="📁 上传文件",
                    file_count="single",
                    file_types=[".txt", ".b64", ".log", ".json", ".xlsx", ".xls"],
                    height=100,
                )
                
                upload_status = gr.Textbox(
                    label="上传状态",
                    interactive=False,
                    visible=True,
                )
                
                # 功能说明
                gr.Markdown("""
                ### 🎯 快捷指令
                - `映射` / `字段` - 生成字段映射表
                - `威胁` / `攻击` - 威胁类型标准化
                - `查看` / `显示` - 查看解码数据
                """)
                
                # 清除按钮
                clear_btn = gr.Button("🗑️ 清除历史", variant="secondary")
        
        # 事件绑定
        submit_btn.click(
            process_message,
            inputs=[msg_input, chatbot, file_input],
            outputs=[msg_input, chatbot],
        )
        
        msg_input.submit(
            process_message,
            inputs=[msg_input, chatbot, file_input],
            outputs=[msg_input, chatbot],
        )
        
        file_input.change(
            handle_file_upload,
            inputs=[file_input],
            outputs=[upload_status, chatbot],
        )
        
        clear_btn.click(
            clear_history,
            outputs=[chatbot, file_input, upload_status, msg_input],
        )
        
        # 初始化检查
        demo.load(fn=init_team)
    
    return demo


# ============= 启动 =============

def main():
    """主函数"""
    # 检查API Key
    api_key = os.getenv("SILICONFLOW_API_KEY", "")
    if not api_key:
        print("⚠️ 警告：未找到 SILICONFLOW_API_KEY")
        print("请确保 .env 文件中已设置 SILICONFLOW_API_KEY")
    
    # 创建并启动应用
    print("\n🚀 启动数据映射智能助手...")
    print("📍 访问地址: http://localhost:7860")
    print("🔑 按 Ctrl+C 停止服务\n")
    
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
    )


if __name__ == "__main__":
    main()
