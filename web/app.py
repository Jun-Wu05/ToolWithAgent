"""
数据映射解析工具 - Streamlit Web 应用

基于 Agno Agent 的对话式智能体（纯自然语言交互）
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd

# 页面配置
st.set_page_config(
    page_title="数据映射解析助手",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 导入模块
from web.config import init_session_state
from web.utils import log_info
from web.handlers import (
    handle_user_message,
    add_message,
    display_chat_history,
    process_standard_field,
    process_threat_type,
    process_threat_type_by_input,
    process_enum_field,
    confirm_enum_mapping,
    get_mode_name,
    process_log_upload,
    extract_log_field
)
from web.parsers import parse_markdown_to_dataframe, parse_threat_markdown_to_dataframe
from agent.tools.threat_type_tool import load_threat_types_from_config
from datetime import datetime


# 初始化
init_session_state()
log_info("应用启动")


# ============= 侧边栏配置 =============
with st.sidebar:
    st.title("📎 文件上传")
    
    uploaded_file = st.file_uploader(
        "选择 Base64 文件",
        type=["txt", "b64", "json"],
        key="file_uploader"
    )
    
    if uploaded_file is not None and st.session_state.pending_file is None:
        st.session_state.pending_file = uploaded_file.read().decode("utf-8")
        st.session_state.pending_file_name = uploaded_file.name
        add_message("system", f"📁 已上传文件：{uploaded_file.name}")
        st.rerun()
    
    if st.session_state.pending_file is not None:
        st.success(f"✅ 已上传：{st.session_state.pending_file_name}")
        if st.button("清除文件"):
            st.session_state.pending_file = None
            st.session_state.pending_file_name = None
            st.rerun()
    
    # 日志文件上传 - 字段提取前置处理
    st.divider()
    st.title("📄 日志文件（字段提取）")
    
    uploaded_log = st.file_uploader(
        "选择日志文件",
        type=["txt", "log"],
        key="log_uploader"
    )
    
    # 使用 session_state 避免重复处理
    if uploaded_log is not None and st.session_state.get("log_uploaded_name") != uploaded_log.name:
        result = process_log_upload(uploaded_log)
        if result["status"] == "success":
            st.session_state.pending_log = result["log_content"]
            st.session_state.pending_log_name = result["log_name"]
            st.session_state.log_uploaded_name = result["log_name"]
            st.success(result["message"])
            st.rerun()
        else:
            st.error(result["message"])
    
    if st.session_state.get("pending_log"):
        st.info(f"日志：{st.session_state.pending_log_name}")
        if st.button("清除日志", key="clear_log"):
            st.session_state.pending_log = None
            st.session_state.pending_log_name = None
            st.session_state.extracted_field_values = None
            st.rerun()
    
    # 枚举字段处理：Excel 映射表上传
    st.divider()
    st.title("📊 映射表 Excel（枚举字段处理）")
    
    uploaded_excel = st.file_uploader(
        "选择映射表 Excel",
        type=["xlsx", "xls"],
        key="excel_uploader"
    )
    
    if uploaded_excel is not None:
        st.session_state.pending_excel = uploaded_excel
        st.session_state.pending_excel_name = uploaded_excel.name
        st.success(f"✅ 已上传：{uploaded_excel.name}")
    
    if st.session_state.get("pending_excel"):
        st.info(f"映射表：{st.session_state.pending_excel_name}")
        if st.button("清除映射表"):
            st.session_state.pending_excel = None
            st.session_state.pending_excel_name = None
            st.rerun()
    
    st.divider()
    st.title("⚙️ 配置")
    
    if st.session_state.api_key_configured:
        st.success("✅ API Key 已配置")
    else:
        st.error("❌ API Key 未配置")
        st.info("请在 .env 文件中配置 SILICONFLOW_API_KEY")
    
    st.divider()
    
    if st.button("🗑️ 清空聊天"):
        for key in list(st.session_state.keys()):
            if key not in ["logging_initialized", "logger", "api_key_configured"]:
                del st.session_state[key]
        init_session_state()
        log_info("聊天已清空")
        st.rerun()
    
    st.divider()
    st.subheader("📊 当前状态")
    if st.session_state.current_mode:
        st.info(f"模式：{get_mode_name(st.session_state.current_mode)}")
        if st.session_state.current_mode == "threat_type" and st.session_state.threat_target_field:
            st.text(f"目标字段：{st.session_state.threat_target_field}")
    else:
        st.text("等待选择处理模式")
    
    if st.session_state.pending_file:
        st.success(f"已上传：{st.session_state.pending_file_name}")
    else:
        st.text("未上传文件")
    
    # 操作历史
    st.divider()
    with st.expander("📜 操作历史", expanded=False):
        history = st.session_state.get("action_history", [])
        if history:
            for record in reversed(history[-5:]):
                status = "✅" if record.get("success", True) else "❌"
                st.text(f"{status} {record.get('description', '')}")
        else:
            st.text("暂无操作历史")
        
        if st.button("🗑️ 清空历史", use_container_width=True):
            st.session_state.action_history = []
            st.rerun()
    
    # 快捷键提示
    st.divider()
    with st.expander("⌨️ 快捷键", expanded=False):
        st.markdown("""
| 快捷键 | 功能 |
|--------|------|
| `Ctrl+1` | 标准字段处理 |
| `Ctrl+2` | 枚举字段处理 |
| `Ctrl+3` | 威胁类型处理 |
| `Ctrl+Enter` | 确认映射 |
        """)
    
    # 批量处理
    st.divider()
    with st.expander("📦 批量处理", expanded=False):
        st.markdown("**批量上传多个文件**")
        
        batch_files = st.file_uploader(
            "选择多个文件",
            type=["txt", "b64", "json"],
            accept_multiple_files=True,
            key="batch_uploader"
        )
        
        if batch_files:
            st.success(f"已选择 {len(batch_files)} 个文件")
            for f in batch_files:
                st.text(f"📄 {f.name}")
        
        if st.button("🚀 批量处理", use_container_width=True):
            if batch_files:
                st.session_state.batch_mode = True
                st.session_state.batch_files = [f.read().decode("utf-8") for f in batch_files]
                st.session_state.batch_names = [f.name for f in batch_files]
                st.info(f"已添加到批量队列，等待处理...")
            else:
                st.warning("请先选择文件")


# ============= 主界面 =============
st.markdown("""
<style>
    .main-header {
        font-size: 2rem;
        font-weight: bold;
        color: #1f77b4;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<p class="main-header">🤖 数据映射解析助手</p>', unsafe_allow_html=True)
st.markdown("基于 Agno Agent 的对话式智能体 - 纯自然语言交互")

# ============= 使用指南 =============
if st.session_state.get("show_guide", True):
    with st.expander("📖 使用指南", expanded=True):
        st.markdown("""
**操作流程：**

1. **上传配置文件** - 通过侧边栏上传 Base64 编码的配置文件
2. **选择处理模式** - 点击下方快速处理按钮
3. **编辑映射表** - 根据需要调整映射关系
4. **确认并下载** - 确认后下载处理结果

**三种处理模式：**
- 📋 **标准字段** - 将原始字段映射到标准字段名
- 📝 **枚举字段** - 填写/上传映射表，批量处理枚举值
- ⚠️ **威胁类型** - 输入威胁类型，自动生成标准化映射
    """)
        if st.button("我知道了，不再显示"):
            st.session_state.show_guide = False
            st.rerun()

# ============= 快速处理 =============
st.markdown("### 🚀 快速处理")

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("📋 标准字段处理", use_container_width=True, type="secondary"):
        if st.session_state.pending_file:
            st.session_state.current_mode = "standard_field"
            st.session_state.is_processing = True
            st.session_state.processing_mode = "standard_field"
            add_message("assistant", "⏳ 正在处理标准字段...")
            st.rerun()
        else:
            st.warning("请先上传 Base64 配置文件")

with col2:
    if st.button("📊 枚举字段处理", use_container_width=True, type="secondary"):
        if st.session_state.pending_file and st.session_state.get("pending_excel"):
            st.session_state.current_mode = "enum_field"
            st.session_state.is_processing = True
            st.session_state.processing_mode = "enum_field"
            add_message("assistant", "⏳ 正在处理枚举字段...")
            st.rerun()
        elif st.session_state.pending_file:
            st.warning("枚举字段处理需要上传映射表 Excel")
        else:
            st.warning("请先上传配置文件")

with col3:
    if st.button("⚠️ 威胁类型处理", use_container_width=True, type="secondary"):
        if st.session_state.pending_file:
            st.session_state.current_mode = "threat_type"
            add_message("assistant", "📁 请在下方输入您想要处理的威胁类型（多个用逗号分隔）")
            st.rerun()
        else:
            st.warning("请先上传 Base64 数据文件")

# ============= 字段提取前置处理区域 =============
st.divider()
st.markdown("### 🔍 字段提取（前置处理）")

if st.session_state.get("pending_log"):
    # 字段提取表单
    col_field1, col_field2, col_field3 = st.columns([2, 2, 1])
    
    with col_field1:
        field_key = st.text_input(
            "字段名（field）",
            placeholder="如：威胁类型",
            help="作为映射表中的 field 字段值"
        )
    
    with col_field2:
        default_pattern = f'"{field_key or "xxx"}"\\s*:\\s*"([^"]*)"' if field_key else ""
        pattern = st.text_input(
            "正则表达式",
            value=default_pattern,
            placeholder="可选，默认匹配 \"字段名\": \"值\" 格式"
        )
    
    with col_field3:
        st.markdown("<br>", unsafe_allow_html=True)  # 对齐
        if st.button("🚀 提取字段值", use_container_width=True):
            if field_key:
                from agent.tools.extract_field_tool import extract_field_values, generate_mapping_table
                result = extract_field_values(st.session_state.pending_log, field_key, pattern or None)
                
                if result["status"] == "success":
                    st.session_state.extracted_field_values = result
                    st.session_state.extracted_mapping_table = generate_mapping_table(
                        field_key,
                        result["unique_values"],
                        "EQUAL"  # 默认 EQUAL
                    )
                    st.session_state.current_extract_field = field_key
                    st.rerun()
                else:
                    st.error(f"提取失败：{result.get('error_message', '未知错误')}")
            else:
                st.warning("请输入字段名")
    
    # 显示提取结果
    if st.session_state.get("extracted_field_values"):
        extract_result = st.session_state.extracted_field_values
        
        st.success(f"✅ 提取完成！共找到 {extract_result['unique_count']} 个非重复值（共匹配 {extract_result['total_count']} 行，未匹配 {extract_result['unmatched_count']} 行）")
        
        # 映射表预览
        if st.session_state.get("extracted_mapping_table"):
            st.markdown("**📋 生成的映射表预览：**")
            preview_df = pd.DataFrame(st.session_state.extracted_mapping_table)
            st.dataframe(preview_df, hide_index=True)
            
            # 导入到在线映射表
            col_imp1, col_imp2 = st.columns(2)
            with col_imp1:
                if st.button("📥 导入到映射表", use_container_width=True):
                    st.session_state.enum_online_table = st.session_state.extracted_mapping_table.copy()
                    st.success("✅ 已导入到映射表，请编辑 mappingValue 后确认")
                    st.rerun()
            
            with col_imp2:
                # 下载映射表 Excel
                import tempfile
                from agent.tools.extract_field_tool import save_mapping_to_excel
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                    tmp_path = tmp.name
                
                save_mapping_to_excel(st.session_state.extracted_mapping_table, tmp_path)
                
                with open(tmp_path, "rb") as f:
                    excel_data = f.read()
                
                import os as os_module
                os_module.unlink(tmp_path)
                
                st.download_button(
                    "📥 下载 Excel",
                    data=excel_data,
                    file_name=f"映射表_{st.session_state.current_extract_field}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )

st.divider()

# 显示欢迎消息
if not st.session_state.messages:
    from web.handlers import get_help_message
    add_message("assistant", get_help_message())

display_chat_history()


# ============= 处理"正在处理中"状态 =============
if st.session_state.is_processing:
    processing_mode = st.session_state.processing_mode
    pending_file = st.session_state.pending_file
    pending_excel = st.session_state.get("pending_excel")
    
    with st.spinner("⏳ 正在处理中...."):
        if processing_mode == "standard_field" and pending_file:
            result = process_standard_field(pending_file)
            st.session_state.pending_file = None
            st.session_state.pending_file_name = None
            st.session_state.is_processing = False
            st.session_state.processing_mode = None
            add_message("assistant", result["message"])
            st.rerun()
        
        elif processing_mode == "threat_type" and pending_file:
            result = process_threat_type(pending_file)
            st.session_state.pending_file = None
            st.session_state.pending_file_name = None
            st.session_state.is_processing = False
            st.session_state.processing_mode = None
            add_message("assistant", result["message"])
            st.rerun()
        
        elif processing_mode == "threat_type_by_input" and pending_file:
            threat_text = st.session_state.get("pending_threat_text", "")
            result = process_threat_type_by_input(pending_file, threat_text)
            st.session_state.pending_file = None
            st.session_state.pending_file_name = None
            st.session_state.is_processing = False
            st.session_state.processing_mode = None
            add_message("assistant", result["message"])
            st.rerun()
        
        elif processing_mode == "enum_field" and pending_file:
            result = process_enum_field(pending_file, pending_excel)
            st.session_state.pending_file = None
            st.session_state.pending_file_name = None
            # 保留 Excel 文件
            st.session_state.is_processing = False
            st.session_state.processing_mode = None
            add_message("assistant", result["message"])
            st.rerun()


# ============= 显示可编辑表格 =============
# 标准字段映射表
if st.session_state.mapping_df is not None:
    if not st.session_state.mapping_confirmed:
        st.markdown("**📝 字段映射表（可直接编辑）：**")
        
        edited_df = st.data_editor(
            st.session_state.mapping_df,
            column_config={
                "原始字段名": st.column_config.TextColumn("原始字段名", disabled=True),
                "系统属性名称": st.column_config.TextColumn("系统属性名称"),
                "匹配状态/说明": st.column_config.TextColumn("匹配状态/说明")
            },
            hide_index=True,
            key="mapping_editor"
        )
        st.session_state.mapping_df = edited_df
        
        st.markdown("")
        if st.button("✅ 确认映射", type="primary", key="confirm_standard_mapping"):
            from web.handlers import confirm_standard_mapping
            result = confirm_standard_mapping()
            add_message("assistant", result["message"])
            st.rerun()
    else:
        # 确认后显示只读表格
        st.markdown("**📋 字段映射表（已确认）：**")
        st.dataframe(
            st.session_state.mapping_df,
            hide_index=True
        )

# 威胁类型映射表
if st.session_state.threat_mapping_df is not None:
    if not st.session_state.threat_confirmed:
        st.markdown("**📝 威胁类型映射表（可直接编辑）：**")
        
        all_types = st.session_state.get("threat_types_list", load_threat_types_from_config())
        
        edited_df = st.data_editor(
            st.session_state.threat_mapping_df,
            column_config={
                "mappingType": st.column_config.TextColumn("mappingType"),
                "orgValue": st.column_config.TextColumn("orgValue"),
                "mappingValue": st.column_config.SelectboxColumn(
                    "mappingValue",
                    options=all_types
                )
            },
            hide_index=True,
            key="threat_mapping_editor"
        )
        st.session_state.threat_mapping_df = edited_df
        
        st.markdown("")
        if st.button("✅ 确认映射", type="primary", key="confirm_threat_mapping"):
            from web.handlers import confirm_threat_mapping
            result = confirm_threat_mapping()
            add_message("assistant", result["message"])
            st.rerun()
    else:
        # 确认后显示只读表格
        st.markdown("**📋 威胁类型映射表（已确认）：**")
        st.dataframe(
            st.session_state.threat_mapping_df,
            hide_index=True
        )


# ============= 下载结果区域 =============
if st.session_state.final_result and st.session_state.mapping_confirmed:
    # 生成文件名：在原始文件名后加"_处理后"
    original_name = st.session_state.get("pending_file_name", "result")
    base_name = original_name.rsplit(".", 1)[0] if "." in original_name else original_name
    ext = original_name.rsplit(".", 1)[1] if "." in original_name else "txt"
    download_name = f"{base_name}_处理后.{ext}"
    
    st.download_button(
        label="⬇️ 下载标准字段处理结果",
        data=st.session_state.final_result,
        file_name=download_name,
        mime="text/plain",
        type="primary"
    )
    st.write("")

if st.session_state.threat_confirmed and st.session_state.threat_final_result:
    # 生成文件名：在原始文件名后加"_处理后"
    original_name = st.session_state.get("pending_file_name", "threat_type_result")
    base_name = original_name.rsplit(".", 1)[0] if "." in original_name else original_name
    ext = original_name.rsplit(".", 1)[1] if "." in original_name else "txt"
    download_name = f"{base_name}_处理后.{ext}"
    
    st.download_button(
        label="⬇️ 下载处理结果（Base64）",
        data=st.session_state.threat_final_result,
        file_name=download_name,
        mime="text/plain",
        type="primary"
    )
    st.write("")

# ============= 枚举字段处理 - 在线填写/上传表格区域 =============
# 仅在有数据或需要处理时显示
has_enum_data = bool(st.session_state.enum_online_table)

if has_enum_data:
    with st.expander("📝 枚举字段映射表（在线填写）", expanded=True):
        # 说明
        st.info("💡 填写格式：mappingType | orgValue | mappingValue | field")
        
        # 在线编辑表格
        st.markdown("**在线填写映射表（可直接编辑）：**")
        
        # 创建可编辑的 DataFrame
        online_df = pd.DataFrame(st.session_state.enum_online_table)
        
        edited_online_df = st.data_editor(
            online_df,
            column_config={
                "mappingType": st.column_config.TextColumn("mappingType", default="EQUAL"),
                "orgValue": st.column_config.TextColumn("orgValue"),
                "mappingValue": st.column_config.TextColumn("mappingValue"),
                "field": st.column_config.TextColumn("field")
            },
            hide_index=True,
            num_rows="dynamic",  # 允许动态添加行
            key="enum_online_editor"
        )
        
        # 保存编辑后的数据
        st.session_state.enum_online_table = edited_online_df.to_dict("records")
        
        col_btn1, col_btn2 = st.columns(2)
        
        with col_btn1:
            if st.button("📊 从Excel加载映射表", use_container_width=True):
                if st.session_state.get("pending_excel"):
                    import tempfile
                    import os as os_module
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                        tmp.write(st.session_state.pending_excel.getvalue())
                        tmp_path = tmp.name
                    try:
                        from agent.tools.enum_field_tool import load_mapping_from_excel
                        loaded_table = load_mapping_from_excel(tmp_path)
                        st.session_state.enum_online_table = loaded_table
                        st.success(f"✅ 已加载 {len(loaded_table)} 条映射规则")
                        st.rerun()
                    finally:
                        os_module.unlink(tmp_path)
                else:
                    st.warning("请先上传映射表 Excel 文件")
        
        with col_btn2:
            if st.button("🗑️ 清空表格", use_container_width=True):
                st.session_state.enum_online_table = []
                st.rerun()
        
        st.markdown("")
        
        # 确认映射按钮
        if st.session_state.enum_online_table and not st.session_state.get("enum_confirmed"):
            if st.button("✅ 确认映射并处理", type="primary", use_container_width=True):
                if st.session_state.pending_file:
                    result = confirm_enum_mapping(st.session_state.enum_online_table)
                    if result["status"] == "success":
                        st.rerun()
                    else:
                        st.error(result["message"])
                else:
                    st.warning("请先上传 Base64 配置文件")
        
        # 枚举字段处理结果下载
        if st.session_state.get("enum_confirmed") and st.session_state.get("enum_final_result"):
            original_name = st.session_state.get("pending_file_name", "enum_result")
            base_name = original_name.rsplit(".", 1)[0] if "." in original_name else original_name
            ext = original_name.rsplit(".", 1)[1] if "." in original_name else "txt"
            download_name = f"{base_name}_枚举映射后.{ext}"
            
            st.success("✅ 枚举字段映射完成！")
            st.download_button(
                label="⬇️ 下载枚举字段处理结果",
                data=st.session_state.enum_final_result,
                file_name=download_name,
                mime="text/plain",
                type="primary"
            )
            st.write("")


# ============= 聊天输入 =============
if prompt := st.chat_input("输入您的需求或指令..."):
    add_message("user", prompt)
    response = handle_user_message(prompt)
    add_message("assistant", response)
    st.rerun()


# ============= 底部信息 =============
st.divider()
st.markdown(
    """
    <div style="text-align: center; color: #666; font-size: 0.8rem;">
        <p>数据映射解析助手 | 基于 Agno Agent + DeepSeek-V3.2 + SiliconFlow</p>
    </div>
    """,
    unsafe_allow_html=True
)
