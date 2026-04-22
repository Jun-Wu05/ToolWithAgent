"""
配置模块 - 加载配置文件
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st


def load_standard_fields_from_config() -> list:
    """从配置文件加载标准字段列表"""
    from web.utils import log_info, log_error
    
    standard_fields = []
    
    # 方案1：从 agent/data/标准字段.txt 加载
    data_path = Path(__file__).parent.parent / "agent" / "data" / "标准字段.txt"
    if data_path.exists():
        content = data_path.read_text(encoding='utf-8')
        # 解析文件内容，提取系统属性名称
        for line in content.split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):
                # 格式可能是 "系统属性名称 | 对象 | 字段名称"
                parts = line.split('|')
                if len(parts) >= 1:
                    prop_name = parts[0].strip()
                    if prop_name:
                        standard_fields.append(prop_name)
        log_info(f"从标准字段.txt加载了 {len(standard_fields)} 个标准字段")
        return standard_fields
    
    # 方案2：从 config/对象.xlsx 加载
    config_path = Path(__file__).parent.parent / "config" / "对象.xlsx"
    if config_path.exists():
        try:
            from openpyxl import load_workbook
            wb = load_workbook(config_path, read_only=True, data_only=True)
            
            if '对应关系' in wb.sheetnames:
                ws = wb['对应关系']
                headers = []
                if ws.max_row >= 1:
                    for col in range(1, ws.max_column + 1):
                        cell_value = ws.cell(row=1, column=col).value
                        headers.append(str(cell_value) if cell_value is not None else '')
                
                prop_col_index = None
                for i, header in enumerate(headers):
                    if '系统属性' in header or '属性名称' in header:
                        prop_col_index = i + 1
                        break
                
                if prop_col_index:
                    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, values_only=True):
                        if len(row) >= prop_col_index:
                            prop_name = row[prop_col_index - 1]
                            if prop_name:
                                prop_name = str(prop_name).strip()
                                if prop_name and prop_name not in standard_fields:
                                    standard_fields.append(prop_name)
            
            wb.close()
            log_info(f"从对象.xlsx加载了 {len(standard_fields)} 个标准字段")
        except Exception as e:
            log_error(f"加载标准字段失败: {str(e)}")
    
    return standard_fields


def init_session_state():
    """初始化 session state"""
    import os
    from dotenv import load_dotenv
    
    # 加载 .env 文件
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    if "decoded_data" not in st.session_state:
        st.session_state.decoded_data = None
    if "fields" not in st.session_state:
        st.session_state.fields = []
    if "original_log" not in st.session_state:
        st.session_state.original_log = None
    if "mapping_df" not in st.session_state:
        st.session_state.mapping_df = None
    if "mapping_confirmed" not in st.session_state:
        st.session_state.mapping_confirmed = False
    if "processed_data" not in st.session_state:
        st.session_state.processed_data = None
    if "final_result" not in st.session_state:
        st.session_state.final_result = None
    
    if "threat_decoded_data" not in st.session_state:
        st.session_state.threat_decoded_data = None
    if "threat_mapping_df" not in st.session_state:
        st.session_state.threat_mapping_df = None
    if "threat_confirmed" not in st.session_state:
        st.session_state.threat_confirmed = False
    if "threat_final_result" not in st.session_state:
        st.session_state.threat_final_result = None
    if "threat_target_field" not in st.session_state:
        st.session_state.threat_target_field = None
    if "threat_target_field_specified" not in st.session_state:
        st.session_state.threat_target_field_specified = False
    
    if "current_mode" not in st.session_state:
        st.session_state.current_mode = None
    
    if "api_key_configured" not in st.session_state:
        st.session_state.api_key_configured = bool(os.getenv("SILICONFLOW_API_KEY", ""))
    
    if "pending_file" not in st.session_state:
        st.session_state.pending_file = None
    if "pending_file_name" not in st.session_state:
        st.session_state.pending_file_name = None
    
    # 字段提取前置处理相关
    if "pending_log" not in st.session_state:
        st.session_state.pending_log = None
    if "pending_log_name" not in st.session_state:
        st.session_state.pending_log_name = None
    if "extracted_field_values" not in st.session_state:
        st.session_state.extracted_field_values = None
    if "extracted_mapping_table" not in st.session_state:
        st.session_state.extracted_mapping_table = None
    if "current_extract_field" not in st.session_state:
        st.session_state.current_extract_field = None
    
    # 枚举在线映射表
    if "enum_online_table" not in st.session_state:
        st.session_state.enum_online_table = []
    if "enum_confirmed" not in st.session_state:
        st.session_state.enum_confirmed = False
    if "enum_final_result" not in st.session_state:
        st.session_state.enum_final_result = None
    if "pending_excel" not in st.session_state:
        st.session_state.pending_excel = None
    if "pending_excel_name" not in st.session_state:
        st.session_state.pending_excel_name = None
    
    # 处理状态标志
    if "is_processing" not in st.session_state:
        st.session_state.is_processing = False
    if "processing_mode" not in st.session_state:
        st.session_state.processing_mode = None
    
    # 标准字段配置 - 从配置文件加载
    if "standard_fields_list" not in st.session_state:
        st.session_state.standard_fields_list = load_standard_fields_from_config()
    
    # 是否显示使用指南
    if "show_guide" not in st.session_state:
        st.session_state.show_guide = True
    
    # 交互优化相关
    if "action_history" not in st.session_state:
        st.session_state.action_history = []
    if "batch_mode" not in st.session_state:
        st.session_state.batch_mode = False
    if "batch_files" not in st.session_state:
        st.session_state.batch_files = []
    if "show_shortcuts" not in st.session_state:
        st.session_state.show_shortcuts = False
