"""
数据映射智能助手 - Streamlit Web界面

使用方法：
1. 设置环境变量 SILICONFLOW_API_KEY
2. 运行: streamlit run web/app.py
"""

import streamlit as st
import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.core.agent import create_agent


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
            st.session_state.agent = create_agent(user_id="web_user")
            st.session_state.messages = []
            st.success("✅ Agent初始化成功！")
        except ValueError as e:
            st.error(f"❌ {str(e)}")
            st.info("请设置环境变量 SILICONFLOW_API_KEY")
            st.stop()
    else:
        st.session_state.messages = st.session_state.get("messages", [])


def handle_confirmation():
    """处理确认请求"""
    # TODO: 实现确认界面
    st.info("确认功能需要前端配合实现")
    return None


def main():
    """主函数"""
    st.title("🔧 数据映射智能助手")
    st.markdown("**自主思考 · 智能映射 · 安全可控**")
    
    # 初始化
    init_session_state()
    
    # 侧边栏
    with st.sidebar:
        st.header("⚙️ 设置")
        
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
            st.rerun()
    
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
        
        if input_mode == "直接输入":
            user_input = st.text_area(
                "输入Base64数据或描述需求",
                height=150,
                placeholder="例如：处理这个Base64，完成字段映射"
            )
        else:
            uploaded_file = st.file_uploader("上传Base64文件")
            if uploaded_file:
                user_input = uploaded_file.read().decode('utf-8')
                st.text_area("文件内容", value=user_input, height=150, disabled=True)
            else:
                user_input = None
        
        task_description = st.text_input(
            "任务描述（可选）",
            placeholder="例如：完成字段映射和威胁类型标准化"
        )
        
        if st.button("🚀 执行", type="primary", disabled=not user_input):
            with st.spinner("Agent正在思考中..."):
                try:
                    # 组合输入
                    full_input = user_input
                    if task_description:
                        full_input = f"{user_input}\n\n任务：{task_description}"
                    
                    # 调用Agent
                    agent = st.session_state.agent
                    response = agent.run(full_input)
                    
                    # 保存对话
                    st.session_state.messages.append({
                        "role": "user",
                        "content": full_input
                    })
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": response.content if hasattr(response, 'content') else str(response)
                    })
                    
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"处理失败: {str(e)}")
    
    with col2:
        # 对话历史
        st.subheader("💬 对话历史")
        
        if st.session_state.messages:
            for msg in st.session_state.messages:
                if msg["role"] == "user":
                    with st.chat_message("user"):
                        st.text(msg["content"][:200] + "..." if len(msg["content"]) > 200 else msg["content"])
                else:
                    with st.chat_message("assistant"):
                        st.markdown(msg["content"])
        else:
            st.info("暂无对话历史")
    
    # 状态显示
    st.divider()
    
    col3, col4, col5 = st.columns(3)
    
    with col3:
        st.metric("会话状态", st.session_state.agent.session_state.get("processing_status", "idle") if st.session_state.agent.session_state else "N/A")
    
    with col4:
        st.metric("对话轮次", len(st.session_state.messages) // 2)
    
    with col5:
        if st.session_state.agent.session_state:
            decoded = st.session_state.agent.session_state.get("decoded_data")
            st.metric("解码数据", "有" if decoded else "无")


if __name__ == "__main__":
    main()
