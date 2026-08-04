"""
分批字段映射 helper — 消除 user_message_handlers / action_callbacks 的复制粘贴

提供:
- run_batched_mapping(team, fields, user_text, session, parse_fn, batch_size) → (mapping_data, total_batches)
  封装 loading_msg 管理 + 三个回调闭包 + process_batched_mapping 调用
"""
import chainlit as cl

from web.input_builder import build_batch_llm_input
from web.llm_client import call_team
from web.file_handler import process_batched_mapping


async def run_batched_mapping(
    team,
    fields_list: list,
    user_text: str,
    user_session,
    parse_fn,
    batch_size: int = 25,
    loading_msg: cl.Message = None,
) -> tuple:
    """执行分批字段映射，封装 loading 消息管理和回调闭包。

    Args:
        team: Agno Team 实例
        fields_list: 待映射的原始字段名列表
        user_text: 用户请求文本（传给 LLM）
        user_session: 用户会话状态
        parse_fn: 映射结果解析函数（如 parse_json_mapping_result）
        batch_size: 每批字段数（默认 25）
        loading_msg: 可选的已有 loading 消息（不传则内部创建）

    Returns:
        (mapping_data, total_batches)：mapping_data 为合并后的映射列表，无结果时为 []
    """
    own_loading = loading_msg is None
    if own_loading:
        loading_msg = cl.Message(content="⏳ **正在处理字段映射...**")
    await loading_msg.send()

    def build_batch_fn(u_text, u_sess, batch, idx, total):
        return build_batch_llm_input(u_text, u_sess, batch, idx, total)

    async def call_team_fn(t, input_text, _loading, intent):
        return await call_team(t, input_text, loading_msg, intent=intent)

    async def on_batch_complete(batch_idx: int, total: int, batch_count: int, total_count: int):
        loading_msg.content = f"⏳ **正在处理字段映射（第 {batch_idx + 1}/{total} 批）...**"
        try:
            await loading_msg.update()
        except Exception:
            pass

    mapping_data, total_batches = await process_batched_mapping(
        team=team,
        fields_list=fields_list,
        user_text=user_text,
        user_session=user_session,
        build_batch_fn=build_batch_fn,
        call_team_fn=call_team_fn,
        parse_fn=parse_fn,
        batch_size=batch_size,
        on_batch_complete=on_batch_complete,
    )

    try:
        await loading_msg.remove()
    except Exception:
        pass

    return mapping_data, total_batches
