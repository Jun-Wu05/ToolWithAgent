"""
工具模块 - 日志配置和通用工具函数
"""
import logging
import streamlit as st
from pathlib import Path


def setup_logging_once():
    """配置日志（仅执行一次）"""
    if "logging_initialized" in st.session_state:
        return logging.getLogger(__name__)
    
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    log_file = log_dir / "app.log"
    log_file.write_text("")
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    
    st.session_state.logging_initialized = True
    return logging.getLogger(__name__)


def log_info(message: str):
    """记录 Info 日志"""
    if "logger" not in st.session_state:
        st.session_state.logger = setup_logging_once()
    st.session_state.logger.info(message)


def log_error(message: str):
    """记录 Error 日志"""
    if "logger" not in st.session_state:
        st.session_state.logger = setup_logging_once()
    st.session_state.logger.error(message)
