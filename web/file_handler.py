"""
文件上传处理业务逻辑（从 chainlit_app.py 提取）

本模块仅包含纯数据处理函数，不包含任何 Chainlit UI 调用（cl.Message 等）。
所有 UI 渲染保留在 chainlit_app.py 中。
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from agent.shared.logger import get_logger

logger = get_logger("file_handler")


def read_element_content(element) -> str:
    """从上传元素中读取文件内容（兼容多种 element 类型）

    Args:
        element: Chainlit 文件元素（File 或 Element 对象）

    Returns:
        str: 文件文本内容
    """
    if hasattr(element, 'path') and element.path:
        with open(element.path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    elif hasattr(element, 'content'):
        content = element.content
        if isinstance(content, bytes):
            return content.decode('utf-8', errors='ignore')
        return str(content)
    else:
        return str(element)


def decode_file_content(file_content: str) -> Dict[str, Any]:
    """解码 Base64 文件内容

    Args:
        file_content: 原始文件内容字符串

    Returns:
        dict: simple_decode 返回的解码结果
    """
    from agent.core.agent import simple_decode
    return simple_decode(file_content)


def build_simplified_data(decode_result: Dict[str, Any]) -> Dict[str, Any]:
    """从解码结果构建 simplified_data（精简上下文，供 LLM 输入构建使用）

    Args:
        decode_result: simple_decode 返回的结果字典

    Returns:
        dict: 包含 fields 和 original_log_sample 的简化数据
    """
    indexes = decode_result.get("fields", [])
    original_log = decode_result.get("original_log", [])

    # 修复：original_log 可能是 string（JSON字符串）、list 或 dict
    if isinstance(original_log, list):
        first_item = original_log[0] if original_log else ""
        if isinstance(first_item, (dict, list)):
            original_log_sample = json.dumps(first_item, ensure_ascii=False)
        else:
            original_log_sample = str(first_item) if first_item else ""
    elif isinstance(original_log, str):
        original_log_sample = original_log
    elif isinstance(original_log, dict):
        original_log_sample = json.dumps(original_log, ensure_ascii=False)
    else:
        original_log_sample = str(original_log) if original_log else ""

    return {
        "fields": indexes,
        "original_log_sample": original_log_sample
    }


def get_element_file_name(element) -> str:
    """获取上传文件的原始文件名

    Args:
        element: Chainlit 文件元素

    Returns:
        str: 文件名，无法获取时返回 'uploaded_file'
    """
    return getattr(element, 'name', '') or 'uploaded_file'


async def process_batched_mapping(
    team,
    fields_list: List[str],
    user_text: str,
    user_session,
    build_batch_fn,
    call_team_fn,
    parse_fn,
    batch_size: int = 50,
    on_batch_complete=None,
) -> Tuple[List[Dict], int]:
    """分批处理字段映射（P2 优化：字段 > batch_size 时自动分批调用）

    纯业务逻辑，不包含 cl.Message 等 UI 调用。
    进度通知由调用方通过 loading_msg 自行处理。

    Args:
        team: Agno Team 实例
        fields_list: 需要映射的字段列表
        user_text: 用户原始消息
        user_session: 当前会话状态
        build_batch_fn: 构建单批输入的回调 (user_text, user_session, batch, idx, total) -> str
        call_team_fn: 调用 Team 的异步回调 (team, input, loading_msg, intent) -> result
        parse_fn: 解析结果的回调 (content) -> list
        batch_size: 每批处理的字段数上限
        on_batch_complete: 每批完成后的异步回调 (batch_idx, total_batches, batch_count, total_count) -> None

    Returns:
        Tuple[List[Dict], int]: (所有批次的映射结果列表, 总批次数)
    """
    total_input_fields = len(fields_list)
    batches = [fields_list[i:i + batch_size] for i in range(0, len(fields_list), batch_size)]
    total_batches = len(batches)

    # 并行并发控制：根据批次数决定并发度（2-3 路并行）
    if total_batches <= 2:
        max_parallel = total_batches
    elif total_batches <= 4:
        max_parallel = 2
    else:
        max_parallel = 3

    semaphore = asyncio.Semaphore(max_parallel)

    async def _process_one_batch(batch_idx: int, batch: List[str]):
        """处理单个批次（带信号量和日志）"""
        batch_no = batch_idx + 1
        batch_input = build_batch_fn(
            user_text, user_session, batch,
            batch_no, total_batches
        )

        async with semaphore:
            logger.info(f"[BATCH] 第 {batch_no}/{total_batches} 批开始（{len(batch)} 个字段）")
            try:
                result = await call_team_fn(team, batch_input, None, intent="mapping")
                result_content = result.content if hasattr(result, 'content') else str(result)
                batch_mapping = parse_fn(result_content)

                if batch_mapping:
                    logger.info(
                        f"[BATCH] 第 {batch_no}/{total_batches} 批完成，"
                        f"本批 {len(batch_mapping)} 条"
                    )
                    if len(batch_mapping) < len(batch):
                        logger.warning(
                            f"[BATCH] 第 {batch_no}/{total_batches} 批结果不完整: "
                            f"输入 {len(batch)} 个字段, 输出 {len(batch_mapping)} 条, "
                            f"缺失 {len(batch) - len(batch_mapping)} 条（LLM 偶发性漏字段）"
                        )
                    return batch_mapping
                else:
                    logger.warning(f"[BATCH] 第 {batch_no}/{total_batches} 批未解析到映射结果")
                    return []

            except Exception as batch_e:
                logger.error(f"[BATCH] 第 {batch_no}/{total_batches} 批调用失败: {batch_e}")
                return []  # 不抛异常，继续处理其他批次

    # 并行执行所有批次
    tasks = [_process_one_batch(i, batch) for i, batch in enumerate(batches)]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    # 按顺序合并结果 + 进度回调
    all_mapping_data = []
    for i, raw in enumerate(raw_results):
        batch_no = i + 1
        batch = batches[i]
        if isinstance(raw, Exception):
            logger.error(f"[BATCH] 第 {batch_no}/{total_batches} 批异常: {raw}")
            batch_mapping = []
        elif isinstance(raw, list):
            batch_mapping = raw
        else:
            batch_mapping = []

        if batch_mapping:
            all_mapping_data.extend(batch_mapping)

        # 通知调用方当前进度
        if on_batch_complete:
            try:
                await on_batch_complete(
                    batch_no, total_batches,
                    len(batch) if batch else 0,
                    len(all_mapping_data)
                )
            except Exception as cb_e:
                logger.warning(f"[BATCH] 进度回调异常: {cb_e}")

    # 全局校验：总结果数 vs 总输入字段数
    if len(all_mapping_data) < total_input_fields:
        logger.warning(
            f"[BATCH] 全部分批完成，总结果不完整: "
            f"输入 {total_input_fields} 个字段, 输出 {len(all_mapping_data)} 条, "
            f"缺失 {total_input_fields - len(all_mapping_data)} 条（LLM 偶发性漏字段，建议重试）"
        )

    return all_mapping_data, total_batches
