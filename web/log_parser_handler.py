"""
Chainlit 日志解析处理器 - 从 chainlit_app.py 提取

本模块处理日志解析 Pipeline，独立成单独模块方便测试。
"""

import chainlit as cl
import json
from agent.shared.logger import get_logger
from agent.tools.log_parser_pipeline import (
    _do_identify_log_format,
    _do_classify_log_features,
    fill_sample_logs
)
from web.utils import parse_json_safe, render_log_parser_result

logger = get_logger("log_parser_handler")


async def handle_log_parser(user_session, user_text):
    """
    处理日志解析请求 - 完整的 Pipeline
    
    职责：
    1. 获取原始日志文本
    2. Step 1: 格式识别
    3. Step 2: 特征分类
    4. Step 3: 用 feature_identifier 替换真实样例
    5. 渲染结果并发送 Action 按钮
    6. 保存 classification 到会话
    
    Args:
        user_session: 用户会话状态
        user_text: 用户输入的文本
    """
    logger.info("[ROUTE] 命中日志解析关键词，直接调用 Pipeline（跳过 Agent 路由）")
    loading_msg = cl.Message(
        content="⏳ **AI正在分析日志，请稍候...**\n\n🔍 正在识别格式并提取特征..."
    )
    await loading_msg.send()
    
    try:
        # 获取原始日志文本
        raw_log_lines = getattr(user_session, "raw_log_lines", None) or user_session.get("raw_log_lines")
        if raw_log_lines:
            # 移除 [:200] 截断，让 _aggregate_by_log_type 能发现低频日志类型（如 ssoaccess）
            # 内部函数（identify/classify）已各自采样 3~5 行供 LLM，无需外部截断
            logs_str = "\n".join(str(line) for line in raw_log_lines)
            logger.info(f"[ROUTE][LogParser] 使用完整输入：{len(raw_log_lines)} 行原始日志")
        else:
            logs_str = user_text
            logger.info(f"[ROUTE][LogParser] 无 raw_log_lines，回退使用 user_text")

        # Step 1: 格式识别
        logger.info("[ROUTE][LogParser] Step 1: identify_log_format")
        format_info_str = _do_identify_log_format(logs_str)
        format_info = parse_json_safe(format_info_str)
        format_type = format_info.get("format", "unknown") if isinstance(format_info, dict) else "unknown"
        format_detail = format_info.get("format_detail", "") if isinstance(format_info, dict) else ""
        # feature_field 由 Step 1 (log_format_identifier) 中 LLM 识别，Step 2 中使用
        feature_field = format_info.get("feature_field", "log_type") if isinstance(format_info, dict) else "log_type"
        header_end_marker = format_info.get("header_end_marker", "") if isinstance(format_info, dict) else ""
        logger.info(f"[ROUTE][LogParser] 格式识别结果: format={format_type}, detail={format_detail}, header_end_marker='{header_end_marker}'")

        # Step 2: 特征分类
        # 路由逻辑已内置到 _do_classify_log_features 中
        # （含 Step 2a 特征定位 → Path A / Path Main），无需在 chainlit_app 层判断
        logger.info("[ROUTE][LogParser] Step 2: classify_log_features (统一入口)")
        classification_str = _do_classify_log_features(
            logs_str=logs_str,
            format_type=format_type,
            format_detail=format_detail,
            feature_field=feature_field,
            format_info=format_info if isinstance(format_info, str) else json.dumps(format_info, ensure_ascii=False),
            header_end_marker=header_end_marker,
        )
        classification = parse_json_safe(classification_str)

        # Step 3: 用 feature_identifier 替换真实样例
        logger.info("[ROUTE][LogParser] Step 3: fill_sample_logs")
        if isinstance(classification, dict):
            classification = fill_sample_logs(classification, logs_str)

        # 保存分类结果到会话（供规则导出使用）
        if hasattr(user_session, "log_classification"):
            user_session.log_classification = classification
        else:
            user_session["log_classification"] = classification

        # 渲染结果
        result_content = render_log_parser_result(classification, format_info)
        
    except Exception as e:
        logger.error(f"[ROUTE][LogParser] Pipeline 异常: {type(e).__name__}: {e}")
        result_content = f"❌ 日志解析失败: {e}"
        classification = None
    
    finally:
        try:
            await loading_msg.remove()
        except Exception:
            pass

    await cl.Message(
        content=result_content,
        actions=[
            cl.Action(
                name="export_rules",
                label="📥 导出入口规则",
                description="生成入口分发规则并导出 base64",
                payload={}
            ),
            cl.Action(
                name="export_sub_rules",
                label="📥 导出子规则",
                description="生成子类分发规则并导出 base64",
                payload={}
            ),
            cl.Action(
                name="apply_field_mapping",
                label="🔍 标准字段映射",
                description="对子规则进行标准字段映射分析",
                payload={}
            ),
        ],
    ).send()
    
    # 附加完整 JSON 文件下载
    if classification and isinstance(classification, dict):
        try:
            json_bytes = json.dumps(classification, ensure_ascii=False, indent=2).encode("utf-8")
            json_file = cl.File(
                name="日志解析结果.json",
                content=json_bytes,
                mime="application/json",
            )
            await cl.Message(content="📥 **完整结果下载：**", elements=[json_file]).send()
        except Exception as json_err:
            logger.error(f"[ROUTE][LogParser] 生成 JSON 下载文件失败: {json_err}")