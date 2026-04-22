"""
数据映射智能助手 - 聊天式交互界面

核心特点：
1. 对话式交互，Agent通过聊天与用户沟通
2. 关键节点暂停，等待用户确认
3. 支持多轮对话

使用方法：
1. 设置环境变量 SILICONFLOW_API_KEY 或在.env文件
2. 运行: streamlit run web/app_chat.py
"""

import streamlit as st
import os
import sys
import json
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 初始化日志
from src.logger import get_logger
logger = get_logger("web_chat")
logger.info("=" * 60)
logger.info("聊天式Web应用启动")
logger.info("=" * 60)


# 页面配置
st.set_page_config(
    page_title="数据映射智能助手 - 聊天版",
    page_icon="💬",
    layout="wide"
)


# ============= 状态常量 =============

class ProcessingState:
    """处理状态枚举"""
    IDLE = "idle"                    # 空闲，等待输入
    DECODED = "decoded"              # 已解码，等待指令
    MAPPING = "mapping"              # 正在映射
    MAPPING_CONFIRM = "mapping_confirm"  # 映射待确认
    THREAT = "threat"                # 正在处理威胁类型
    THREAT_CONFIRM = "threat_confirm"    # 威胁类型待确认
    COMPLETE = "complete"            # 完成


# ============= 初始化 =============

def init_session_state():
    """初始化会话状态"""
    if "team_manager" not in st.session_state:
        try:
            from agent.core.team_web import get_team_manager
            st.session_state.team_manager = get_team_manager()
            logger.info("✅ Team初始化成功")
            # 初始化聊天状态
            st.session_state.messages = []
            # 欢迎消息
            welcome_msg = """👋 你好！我是数据映射智能助手（Team模式）。

我可以帮你处理以下任务：
- **字段映射** - FieldMappingAgent 将原始字段映射到标准字段
- **威胁类型标准化** - ThreatAgent 统一威胁类型格式
- **枚举处理** - EnumAgent 处理字段枚举值

请上传Base64数据或直接描述你的需求！"""
            st.session_state.messages.append({
                "role": "assistant",
                "content": welcome_msg
            })
            logger.info("💬 初始化欢迎消息")
        except ValueError as e:
            logger.error(f"❌ Team初始化失败: {str(e)}")
            st.error(f"❌ {str(e)}")
            st.info("请设置环境变量 SILICONFLOW_API_KEY")
            st.stop()
        except Exception as e:
            logger.error(f"❌ 未知错误: {str(e)}")
            st.error(f"❌ 初始化失败: {str(e)}")
            st.stop()
    
    # 初始化处理状态
    if "processing_state" not in st.session_state:
        st.session_state.processing_state = ProcessingState.IDLE
    
    # 初始化解码数据
    if "decoded_data" not in st.session_state:
        st.session_state.decoded_data = None
    if "decoded_fields" not in st.session_state:
        st.session_state.decoded_fields = None
    if "original_log" not in st.session_state:
        st.session_state.original_log = None


def is_base64(text: str) -> bool:
    """检测文本是否是Base64编码"""
    import re
    cleaned = "".join(text.split())
    if not cleaned or len(cleaned) < 4:
        return False
    if not re.match(r'^[A-Za-z0-9+/]*={0,2}$', cleaned):
        return False
    return True


def handle_base64_input(b64_text: str) -> dict:
    """
    处理Base64输入
    使用simple_decode提取字段信息
    """
    from agent.core.agent import simple_decode
    
    logger.info("🔍 处理Base64输入...")
    
    result = simple_decode(b64_text)
    
    if result["status"] == "success":
        # 保存到会话
        st.session_state.decoded_data = result["decoded_json"]
        st.session_state.decoded_fields = result["fields"]
        st.session_state.original_log = result["original_log"]
        st.session_state.processing_state = ProcessingState.DECODED
        
        logger.info(f"✅ 解码成功，提取到 {len(result['fields'])} 个字段")
        
        # 构建响应
        field_count = result["field_count"]
        field_list = result["fields"][:20]  # 只显示前20个
        
        response = f"""✅ **Base64解码成功！**

📊 **解码结果：**
- 字段数量：{field_count} 个
- JSON结构：{len(result['decoded_json'])} 个顶层字段
"""
        if result["fields"]:
            response += f"\n**提取的字段（前20个）：**\n"
            for i, field in enumerate(field_list, 1):
                response += f"{i}. `{field}`\n"
            if len(result["fields"]) > 20:
                response += f"\n... 还有 {len(result['fields']) - 20} 个字段\n"
        
        response += """

🎯 **我可以帮你完成以下操作：**

1. **字段映射** - 根据标准字段表，生成映射表
2. **威胁类型标准化** - 统一威胁类型格式
3. **枚举处理** - 处理字段枚举值
4. **查看原始日志** - 查看解码后的原始日志

请告诉我你需要什么帮助？"""

        return {
            "success": True,
            "response": response,
            "data": result
        }
    else:
        logger.error(f"❌ 解码失败: {result.get('error_message')}")
        return {
            "success": False,
            "response": f"❌ 解码失败：{result.get('error_message', '未知错误')}",
            "data": None
        }


def handle_user_message(user_input: str) -> str:
    """
    处理用户消息，返回Agent响应
    """
    import threading
    
    logger.info(f"📥 用户消息: {user_input[:100]}...")
    
    # 检查状态
    state = st.session_state.processing_state
    
    # 1. 空闲状态 - 检查是否Base64
    if state == ProcessingState.IDLE:
        if is_base64(user_input):
            return handle_base64_input(user_input)["response"]
        else:
            # 非Base64，发给Agent处理
            return call_agent(user_input)
    
    # 2. 已解码状态 - 处理用户指令
    elif state == ProcessingState.DECODED:
        return handle_decoded_state(user_input)
    
    # 3. 映射待确认状态
    elif state == ProcessingState.MAPPING_CONFIRM:
        return handle_mapping_confirm(user_input)
    
    # 4. 其他状态 - 发给Agent
    else:
        return call_agent(user_input)


def handle_decoded_state(user_input: str) -> str:
    """处理已解码状态的用户输入"""
    user_lower = user_input.lower().strip()
    
    # 检查用户意图
    if any(k in user_lower for k in ["映射", "map", "字段"]):
        return start_field_mapping()
    elif any(k in user_lower for k in ["威胁", "threat", "攻击"]):
        return start_threat_processing()
    elif any(k in user_lower for k in ["枚举", "enum"]):
        return start_enum_processing()
    elif any(k in user_lower for k in ["原始日志", "log", "原始"]):
        return show_original_log()
    elif any(k in user_lower for k in ["查看", "显示", "show", "display"]):
        return show_decoded_data()
    else:
        # 其他指令，发给Agent处理
        return call_agent_with_context(user_input)


def start_field_mapping() -> str:
    """开始字段映射"""
    logger.info("🗺️ 开始字段映射...")
    st.session_state.processing_state = ProcessingState.MAPPING
    
    response = """🔄 **正在分析字段，准备生成映射表...**

请稍候，我会根据标准字段表为你生成映射表。"""

    # 后台调用Agent生成映射表
    import threading
    
    def background_task():
        try:
            prompt = build_mapping_prompt()
            result = call_agent_sync(prompt)
            if result["success"]:
                st.session_state.pending_mapping = result["response"]
                st.session_state.processing_state = ProcessingState.MAPPING_CONFIRM
                st.rerun()
            else:
                st.session_state.error_message = result["error"]
                st.rerun()
        except Exception as e:
            logger.error(f"映射处理异常: {str(e)}")
            st.session_state.error_message = str(e)
            st.rerun()
    
    thread = threading.Thread(target=background_task)
    thread.daemon = True
    thread.start()
    
    return response


def build_mapping_prompt() -> str:
    """构建字段映射提示词"""
    decoded_json = st.session_state.decoded_data
    fields = st.session_state.decoded_fields
    
    fields_str = ", ".join(str(f) for f in fields) if fields else "无"
    
    prompt = f"""根据以下已解码的数据完成字段映射：

**原始日志 JSON：**
```json
{json.dumps(decoded_json, ensure_ascii=False, indent=2)[:3000]}
```

**提取的字段列表：**
{fields_str}

请严格按照标准字段表要求，输出标准字段映射表（Markdown表格格式）。

输出格式：
| 原始字段 | 标准字段 | 匹配度 | 说明 |
|---------|---------|-------|------|
| xxx | xxx | 高/中/低 | - |

只输出映射表，不要其他解释。"""
    
    return prompt


def handle_mapping_confirm(user_input: str) -> str:
    """处理映射确认"""
    user_lower = user_input.lower().strip()
    
    # 检查是否有待确认的映射
    if not hasattr(st.session_state, 'pending_mapping'):
        st.session_state.processing_state = ProcessingState.DECODED
        return "⚠️ 映射表已过期，请重新请求。"
    
    if any(k in user_lower for k in ["确认", "ok", "yes", "y", "好的", "是"]):
        # 保存映射表
        mapping = st.session_state.pending_mapping
        st.session_state.mapping_result = mapping
        st.session_state.processing_state = ProcessingState.COMPLETE
        
        return f"""✅ **映射表已保存！**

{mapping}

---

还需要其他帮助吗？
- 威胁类型标准化
- 枚举处理
- 导出结果"""
    
    elif any(k in user_lower for k in ["修改", "改", "change", "重新"]):
        return "🔄 请描述你想要如何修改映射表？"
    
    elif any(k in user_lower for k in ["取消", "cancel", "no", "否", "算了"]):
        st.session_state.processing_state = ProcessingState.DECODED
        return "❌ 已取消映射。还有什么需要帮助的吗？"
    
    else:
        return f"""📋 **请确认映射表：**

{st.session_state.pending_mapping}

---

请回复：
- **确认** - 保存映射表
- **修改** - 描述需要的修改
- **取消** - 取消当前操作"""


def start_threat_processing() -> str:
    """开始威胁类型处理"""
    logger.info("🛡️ 开始威胁类型处理...")
    
    response = """🔄 **正在处理威胁类型标准化...**

请稍候。"""

    import threading
    
    def background_task():
        try:
            prompt = build_threat_prompt()
            result = call_agent_sync(prompt)
            if result["success"]:
                st.session_state.pending_threat = result["response"]
                st.rerun()
            else:
                st.session_state.error_message = result["error"]
                st.rerun()
        except Exception as e:
            logger.error(f"威胁处理异常: {str(e)}")
    
    thread = threading.Thread(target=background_task)
    thread.daemon = True
    thread.start()
    
    return response


def build_threat_prompt() -> str:
    """构建威胁类型提示词"""
    decoded_json = st.session_state.decoded_data
    
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
    
    return prompt


def start_enum_processing() -> str:
    """开始枚举处理"""
    return "🔄 正在处理枚举字段...\n\n请稍候。"


def show_original_log() -> str:
    """显示原始日志"""
    original_log = st.session_state.original_log
    
    if not original_log:
        return "⚠️ 没有找到原始日志数据。"
    
    response = f"📜 **原始日志（共 {len(original_log)} 条）：**\n\n"
    
    for i, item in enumerate(original_log[:10], 1):
        response += f"{i}. `{item}`\n"
    
    if len(original_log) > 10:
        response += f"\n... 还有 {len(original_log) - 10} 条\n"
    
    return response


def show_decoded_data() -> str:
    """显示解码后的数据"""
    decoded = st.session_state.decoded_data
    
    if not decoded:
        return "⚠️ 没有解码数据。"
    
    return f"""📊 **解码后的JSON数据：**

```json
{json.dumps(decoded, ensure_ascii=False, indent=2)[:2000]}
```"""


def call_agent(user_input: str, timeout: int = 300) -> str:
    """调用Team处理用户输入"""
    team_manager = st.session_state.team_manager
    
    logger.info("🤖 Team开始处理...")
    
    team_result = team_manager.run_task(user_input, timeout)
    
    if team_result["success"]:
        logger.info("✅ Team响应成功")
        return team_result["response"]
    else:
        logger.error(f"❌ Team错误: {team_result['error']}")
        return f"❌ 处理失败：{team_result['error'] or '未知错误'}"


def call_agent_sync(prompt: str, timeout: int = 120) -> dict:
    """同步调用Team（用于后台任务）"""
    team_manager = st.session_state.team_manager
    return team_manager.run_task(prompt, timeout)


def call_agent_with_context(user_input: str) -> str:
    """带上下文的Agent调用"""
    decoded_data = st.session_state.decoded_data
    fields = st.session_state.decoded_fields
    
    prompt = f"""当前已解码数据：

**字段列表：**
{', '.join(str(f) for f in fields) if fields else '无'}

**JSON数据：**
```json
{json.dumps(decoded_data, ensure_ascii=False, indent=2)[:2000]}
```

**用户请求：**
{user_input}

请根据以上上下文，处理用户的请求。"""

    return call_agent(prompt)


# ============= 主界面 =============

def main():
    """主函数"""
    st.title("💬 数据映射智能助手")
    st.markdown("**对话式交互 · 关键节点确认 · 多轮沟通**")
    
    # 初始化
    init_session_state()
    
    # 侧边栏
    with st.sidebar:
        st.header("⚙️ 设置")
        
        # 状态显示
        st.subheader("📊 当前状态")
        state = st.session_state.processing_state
        state_display = {
            ProcessingState.IDLE: "🟢 空闲",
            ProcessingState.DECODED: "🔵 已解码",
            ProcessingState.MAPPING: "🟡 映射中",
            ProcessingState.MAPPING_CONFIRM: "🟠 待确认",
            ProcessingState.COMPLETE: "✅ 完成"
        }
        st.info(state_display.get(state, state))
        
        # 数据统计
        if st.session_state.decoded_data:
            st.metric("解码数据", "✅ 有")
        if st.session_state.decoded_fields:
            st.metric("字段数量", len(st.session_state.decoded_fields))
        
        st.divider()
        
        # 操作
        st.subheader("🛠️ 快速操作")
        
        if st.button("🔄 重置会话"):
            st.session_state.messages = []
            st.session_state.processing_state = ProcessingState.IDLE
            st.session_state.decoded_data = None
            st.session_state.decoded_fields = None
            st.session_state.original_log = None
            st.rerun()
        
        # 显示可用工具
        st.subheader("📋 可用功能")
        st.markdown("""
        - Base64解码
        - 字段映射
        - 威胁类型标准化
        - 枚举处理
        """)
    
    # 主聊天区域
    st.subheader("💬 对话")
    
    # 显示消息历史
    chat_container = st.container()
    with chat_container:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
    
    # 检查是否有后台任务完成
    if st.session_state.processing_state == ProcessingState.MAPPING_CONFIRM:
        if hasattr(st.session_state, 'pending_mapping'):
            with st.chat_message("assistant"):
                st.markdown(f"""📋 **映射表已生成，请确认：**

{st.session_state.pending_mapping}

---

请回复：
- **确认** - 保存映射表
- **修改** - 描述需要的修改
- **取消** - 取消当前操作""")
    
    # 用户输入
    if prompt := st.chat_input("输入消息或上传Base64数据..."):
        # 添加用户消息
        st.session_state.messages.append({
            "role": "user",
            "content": prompt
        })
        
        # 处理消息
        with st.spinner("🤔 处理中..."):
            response = handle_user_message(prompt)
        
        # 添加助手响应
        st.session_state.messages.append({
            "role": "assistant",
            "content": response
        })
        
        st.rerun()
    
    # 文件上传
    st.divider()
    st.subheader("📁 或者上传文件")
    
    uploaded_file = st.file_uploader("选择Base64文件", type=['txt', 'b64', 'log'])
    
    if uploaded_file:
        try:
            content = uploaded_file.read().decode('utf-8')
            st.text_area("文件内容预览", value=content[:500] + "..." if len(content) > 500 else content, height=100, disabled=True)
            
            if st.button("🚀 处理此文件"):
                response = handle_base64_input(content)["response"]
                st.session_state.messages.append({
                    "role": "user",
                    "content": f"[上传文件: {uploaded_file.name}]"
                })
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response
                })
                st.rerun()
        except Exception as e:
            st.error(f"读取文件失败: {str(e)}")


if __name__ == "__main__":
    main()
