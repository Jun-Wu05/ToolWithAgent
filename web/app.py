"""
数据映射智能助手 - Streamlit Web界面 (改进版)

改进点：
1. 异步处理避免卡死
2. 详细日志记录
3. 实时进度显示
4. 错误信息展示

使用方法：
1. 设置环境变量 SILICONFLOW_API_KEY 或在.env文件
2. 运行: streamlit run web/app.py
"""

import streamlit as st
import os
import sys
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 初始化日志
from src.logger import get_logger
logger = get_logger("web")
logger.info("=" * 60)
logger.info("Web应用启动")
logger.info("=" * 60)


# 页面配置
st.set_page_config(
    page_title="数据映射智能助手",
    page_icon="🔧",
    layout="wide"
)


def init_session_state():
    """初始化会话状态"""
    if "agent" not in st.session_state:
        try:
            from agent.core.agent import create_agent
            st.session_state.agent = create_agent(user_id="web_user")
            st.session_state.messages = []
            st.session_state.log_messages = []
            logger.info("✅ Agent初始化成功")
            st.success("✅ Agent初始化成功！")
        except ValueError as e:
            logger.error(f"❌ Agent初始化失败: {str(e)}")
            st.error(f"❌ {str(e)}")
            st.info("请设置环境变量 SILICONFLOW_API_KEY 或在.env文件中配置")
            st.stop()
        except Exception as e:
            logger.error(f"❌ 未知错误: {str(e)}")
            st.error(f"❌ 初始化失败: {str(e)}")
            st.stop()
    else:
        st.session_state.messages = st.session_state.get("messages", [])


def process_agent_request(user_input: str, task_description: str = "", timeout: int = 120):
    """
    处理Agent请求（带超时控制）
    
    Args:
        user_input: 用户输入
        task_description: 任务描述
        timeout: 超时时间（秒）
    
    Returns:
        tuple: (success: bool, response: str or error_message)
    """
    import threading
    
    start_time = datetime.now()
    logger.info(f"📥 收到请求: {user_input[:100]}...")
    
    result = {"response": None, "error": None, "success": False}
    
    try:
        # 组合输入
        full_input = user_input
        if task_description:
            full_input = f"{user_input}\n\n任务：{task_description}"
        
        logger.info(f"📝 完整输入长度: {len(full_input)} 字符")
        
        # 调用Agent
        agent = st.session_state.agent
        logger.info("🤖 Agent开始处理...")
        logger.info(f"⏱️  超时设置: {timeout}秒")
        
        # 使用线程执行，避免阻塞
        def run_agent():
            try:
                response = agent.run(full_input)
                
                # 提取响应内容
                if hasattr(response, 'content'):
                    result["response"] = response.content
                else:
                    result["response"] = str(response)
                result["success"] = True
                logger.info(f"✅ Agent处理成功")
                
            except Exception as e:
                result["error"] = str(e)
                logger.error(f"❌ Agent执行错误: {str(e)}")
                import traceback
                logger.error(f"堆栈: {traceback.format_exc()}")
        
        # 启动线程
        thread = threading.Thread(target=run_agent)
        thread.daemon = True
        thread.start()
        
        # 等待线程完成或超时
        thread.join(timeout=timeout)
        
        elapsed = (datetime.now() - start_time).total_seconds()
        
        if thread.is_alive():
            # 线程还在运行，表示超时
            logger.error(f"⏰ 请求超时（{elapsed:.2f}秒）")
            return False, f"请求超时（{timeout}秒），可能是API响应慢"
        
        if result["success"]:
            logger.info(f"✅ 处理完成，耗时: {elapsed:.2f}秒")
            return True, result["response"]
        else:
            logger.error(f"❌ 处理失败: {result['error']}")
            return False, result["error"] or "未知错误"
        
    except Exception as e:
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.error(f"❌ 处理异常 ({elapsed:.2f}秒): {str(e)}")
        import traceback
        logger.error(f"详细堆栈: {traceback.format_exc()}")
        return False, str(e)


def main():
    """主函数"""
    st.title("🔧 数据映射智能助手")
    st.markdown("**自主思考 · 智能映射 · 安全可控**")
    
    # 初始化
    init_session_state()
    
    # 侧边栏
    with st.sidebar:
        st.header("⚙️ 设置")
        
        st.subheader("日志信息")
        logger.info("正在加载侧边栏...")
        
        # 显示日志目录
        from pathlib import Path
        log_dir = Path(__file__).parent.parent / "logs"
        if log_dir.exists():
            log_files = list(log_dir.glob("web_*.log"))
            if log_files:
                latest_log = max(log_files, key=lambda f: f.stat().st_mtime)
                st.info(f"📁 日志目录: `{log_dir}`")
                st.caption(f"最新日志: `{latest_log.name}`")
            else:
                st.info(f"📁 日志目录: `{log_dir}`")
                st.caption("暂无日志文件")
        else:
            st.warning(f"📁 日志目录不存在")
        
        st.subheader("模型配置")
        st.info("当前使用：DeepSeek-V3.2")
        
        st.subheader("可用工具")
        st.markdown("""
        - **Base64**: 解码/编码
        - **字段映射**: 生成映射表
        - **威胁类型**: 标准化
        - **枚举处理**: 字段枚举
        """)
        
        st.subheader("操作说明")
        st.markdown("""
        1. 输入Base64数据
        2. 描述你的需求
        3. Agent自动处理
        4. 在关键节点确认
        """)
        
        if st.button("🗑️ 清空对话"):
            st.session_state.messages = []
            st.session_state.log_messages = []
            logger.info("🗑️ 用户清空对话")
            st.rerun()
        
        # 显示最近日志
        st.divider()
        st.subheader("📋 最近日志")
        
        if st.session_state.get("log_messages"):
            for log_msg in st.session_state.log_messages[-5:]:
                st.text(log_msg)
        else:
            st.caption("暂无日志")
    
    # 主内容区
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # 用户输入
        st.subheader("📥 输入")
        
        input_mode = st.radio(
            "输入方式",
            ["直接输入", "上传文件"],
            horizontal=True
        )
        
        user_input = None
        
        if input_mode == "直接输入":
            user_input = st.text_area(
                "输入Base64数据或描述需求",
                height=150,
                placeholder="例如：处理这个Base64，完成字段映射",
                key="user_input_direct"
            )
        else:
            uploaded_file = st.file_uploader("上传Base64文件")
            if uploaded_file:
                try:
                    user_input = uploaded_file.read().decode('utf-8')
                    logger.info(f"📄 上传文件: {uploaded_file.name} ({len(user_input)} 字符)")
                    st.text_area("文件内容预览", value=user_input[:500] + "..." if len(user_input) > 500 else user_input, height=150, disabled=True, key="file_preview")
                except Exception as e:
                    logger.error(f"读取上传文件失败: {str(e)}")
                    st.error(f"读取文件失败: {str(e)}")
            else:
                st.info("请上传Base64文件")
        
        task_description = st.text_input(
            "任务描述（可选）",
            placeholder="例如：完成字段映射和威胁类型标准化",
            key="task_description"
        )
        
        # 执行按钮
        col_btn1, col_btn2 = st.columns([1, 3])
        with col_btn1:
            execute_clicked = st.button("🚀 执行", type="primary", disabled=not user_input)
        
        if execute_clicked and user_input:
            logger.info("=" * 60)
            logger.info("开始处理请求")
            logger.info("=" * 60)
            
            # 使用spinner显示进度
            with st.spinner("🤔 Agent正在思考中..."):
                success, result = process_agent_request(user_input, task_description)
            
            if success:
                # 保存对话
                st.session_state.messages.append({
                    "role": "user",
                    "content": user_input + (f"\n\n任务：{task_description}" if task_description else "")
                })
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": result
                })
                
                # 记录到日志显示
                st.session_state.log_messages.append(f"✅ 处理成功")
                
                st.rerun()
            else:
                st.error(f"处理失败: {result}")
                st.session_state.log_messages.append(f"❌ 处理失败: {result[:50]}...")
                logger.error(f"最终错误: {result}")
    
    with col2:
        # 对话历史
        st.subheader("💬 对话历史")
        
        if st.session_state.messages:
            for i, msg in enumerate(st.session_state.messages):
                if msg["role"] == "user":
                    with st.chat_message("user"):
                        content = msg["content"]
                        st.text(content[:200] + "..." if len(content) > 200 else content)
                else:
                    with st.chat_message("assistant"):
                        st.markdown(msg["content"])
                
                # 每2条消息插入分隔线
                if (i + 1) % 2 == 0:
                    st.divider()
        else:
            st.info("暂无对话历史")
    
    # 状态显示
    st.divider()
    
    col3, col4, col5 = st.columns(3)
    
    with col3:
        status = "就绪"
        if st.session_state.agent.session_state:
            status = st.session_state.agent.session_state.get("processing_status", "就绪")
        st.metric("会话状态", status)
    
    with col4:
        st.metric("对话轮次", len(st.session_state.messages) // 2)
    
    with col5:
        if st.session_state.agent.session_state:
            decoded = st.session_state.agent.session_state.get("decoded_data")
            st.metric("解码数据", "有" if decoded else "无")
        else:
            st.metric("解码数据", "无")
    
    # 调试信息
    with st.expander("🔍 调试信息"):
        st.subheader("日志文件位置")
        st.code(str(log_dir) if 'log_dir' in dir() else "logs/")
        
        st.subheader("最近日志")
        if 'latest_log' in dir() and latest_log.exists():
            with open(latest_log, 'r', encoding='utf-8') as f:
                log_content = f.read()
                st.text(log_content[-2000:])  # 显示最后2000字符
        else:
            st.info("暂无日志内容")


if __name__ == "__main__":
    logger.info("应用入口")
    main()
