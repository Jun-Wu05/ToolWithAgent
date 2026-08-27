"""适配器共享接缝：会话读写、结果构造、进度发布与重试判定。

本模块只放跨操作复用的纯函数；操作语义分别位于
field_mapping.py / agent_ops.py / config_ops.py（Issue #88）。
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agent.shared.logger import get_logger

from web.plan_executor import ExecutionContext
from contracts.progress import ProgressEvent, ProgressPhase, ProgressStatus
from contracts.planner_models import (
    ConfigDownloadKind,
    ConfigExportArtifact,
    StepArtifact,
    StepResult,
    StepSpec,
    StepStatus,
)


logger = get_logger("execution_adapters")

# 仓库根目录：适配器据此定位 config/ 与 agent/prompts/ 资产（层级敏感，勿随文件移动改变）。
REPO_ROOT = Path(__file__).resolve().parents[2]


def _model_error_status_code(error: Exception) -> int | None:
    """从常见 SDK 异常中读取 HTTP 状态码，不依赖具体供应商类型。"""
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
    try:
        return int(status_code) if status_code is not None else None
    except (TypeError, ValueError):
        return None


def _is_retriable_model_error(error: Exception) -> bool:
    """仅允许瞬时网络、限流、服务端和超时错误重试一次。"""
    if isinstance(error, (TimeoutError, ConnectionError)):
        return True
    error_type = type(error).__name__
    if error_type in {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ReadTimeout",
        "WriteTimeout",
        "RateLimitError",
    }:
        return True
    status_code = _model_error_status_code(error)
    return status_code == 429 or (status_code is not None and status_code >= 500)


def _retry_delay_seconds(error: Exception, default_seconds: float) -> float:
    """优先采用 Retry-After，且将服务端等待建议限制在十秒内。"""
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    retry_after = headers.get("Retry-After") if hasattr(headers, "get") else None
    try:
        return min(max(float(retry_after), 0.0), 10.0)
    except (TypeError, ValueError):
        return default_seconds


async def _publish_progress(
    context: ExecutionContext,
    step: StepSpec,
    phase: ProgressPhase,
    status: ProgressStatus,
    message_code: str,
    *,
    current_batch: int | None = None,
    total_batches: int | None = None,
    elapsed_seconds: float = 0.0,
) -> None:
    """向执行上下文发布不含原始输入值的安全进度事件。"""
    await context.progress_sink.publish(
        ProgressEvent(
            plan_id=context.plan_id,
            step_id=step.step_id,
            phase=phase,
            status=status,
            message_code=message_code,
            current_batch=current_batch,
            total_batches=total_batches,
            elapsed_seconds=elapsed_seconds,
        )
    )


def _session_get(session: Any, key: str, default: Any = None) -> Any:
    """在迁移期集中兼容 SessionState 与字典，适配器外不传播裸 key 判断。"""
    if isinstance(session, Mapping):
        return session.get(key, default)
    return getattr(session, key, default)


def _session_set(session: Any, key: str, value: Any) -> None:
    """集中写入会话字段，并在未知字段时立即失败。"""
    if isinstance(session, dict):
        session[key] = value
        return
    setattr(session, key, value)


def _is_enum_config_stale(session: Any, config_ref: str) -> bool:
    """判断配置是否因枚举附件变化而需要重新填充。"""
    stale_refs = _session_get(session, "stale_enum_config_refs", set()) or set()
    return config_ref in stale_refs


_CONFIG_SESSION_KEYS = {
    "session.decoded_config": "decoded_data",
    "session.mapped_sub_rules": "mapped_sub_rules",
}


def _read_config(session: Any, config_ref: str) -> Any:
    """按显式配置引用读取 session，未知引用立即失败且不尝试其他来源。"""
    session_key = _CONFIG_SESSION_KEYS.get(config_ref)
    if session_key is None:
        raise ValueError(f"不支持的配置来源: {config_ref}")
    return _session_get(session, session_key)


def _write_config(session: Any, config_ref: str, config: Any) -> None:
    """把更新结果写回原配置来源，禁止在两个 session 字段之间隐式迁移。"""
    session_key = _CONFIG_SESSION_KEYS.get(config_ref)
    if session_key is None:
        raise ValueError(f"不支持的配置来源: {config_ref}")
    _session_set(session, session_key, config)


def _enum_mapping_table(
    enum_preview: list[dict[str, Any]],
    target_fields: tuple[str, ...],
) -> dict[str, list[dict[str, str]]]:
    """从已解析预览构建映射表，避免执行阶段重新依赖真实 Excel 路径。"""
    targets = set(target_fields)
    table: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for row in enum_preview:
        target_field = str(row.get("目标字段", "")).strip()
        if target_field not in targets:
            continue
        original_value = row.get("orgValue", row.get("原始值", ""))
        mapped_value = row.get("mappingValue", row.get("映射值", original_value))
        table[target_field].append(
            {
                "mappingType": str(row.get("mappingType", "EQUAL")),
                "orgValue": str(original_value),
                "mappingValue": str(mapped_value),
            }
        )
    return dict(table)


def _build_config_artifact(
    updated_config: Any,
    item_count: int,
    download_kind: ConfigDownloadKind = "current_config",
) -> ConfigExportArtifact:
    """把完整配置编码为统一下载产物，不改变根对象类型。"""
    encoded_config = base64.b64encode(
        json.dumps(updated_config, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    return ConfigExportArtifact(
        content=encoded_config,
        item_count=item_count,
        download_kind=download_kind,
    )


def _count_tagged_normalize(config: Any) -> int:
    """递归统计已设置标准字段（field 非空）的 normalize 条目数。

    用于字段映射前后差分，得出本次「实际更新的 normalize 项数」，
    与「唯一字段映射数」区分（#23）：同一字段在 N 条子规则会被更新 N 次。
    """
    count = 0

    def _walk(node: Any) -> None:
        """递归遍历 dict/list，累计 field 非空的 normalize 条目。"""
        nonlocal count
        if isinstance(node, dict):
            normalize = node.get("normalize")
            if isinstance(normalize, list):
                for entry in normalize:
                    if isinstance(entry, dict) and entry.get("field"):
                        count += 1
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(config)
    return count


async def run_member_stream(
    team: Any,
    member_name: str,
    model_input: str,
    *,
    plan_id: str = "pending",
    step_id: str = "pending",
    batch_number: int | None = None,
) -> Any:
    """消费专业 Agent 事件流，只接收完成事件内容并记录安全 token 计数。"""
    members = getattr(team, "members", ())
    member = next(
        (candidate for candidate in members if getattr(candidate, "name", "") == member_name),
        None,
    )
    if member is None:
        raise RuntimeError(f"未配置专业 Agent: {member_name}")

    async_runner = getattr(member, "arun", None)
    if callable(async_runner):
        response_stream = async_runner(model_input, stream=True, stream_events=True)
        if inspect.isawaitable(response_stream):
            response_stream = await response_stream
        if hasattr(response_stream, "__aiter__"):
            completed_content = None
            completed_metrics = None
            async for event in response_stream:
                event_name = str(getattr(event, "event", ""))
                if event_name.endswith("RunError"):
                    raise RuntimeError("专业 Agent 返回运行错误事件")
                if event_name.endswith("RunCompleted"):
                    completed_content = getattr(event, "content", None)
                    completed_metrics = getattr(event, "metrics", None)
            if completed_content is None:
                raise RuntimeError("专业 Agent 未返回完成内容")
            if completed_metrics is not None:
                logger.info(
                    "[MODEL_USAGE] 专业模型 token 统计: plan_id=%s step_id=%s "
                    "batch=%s member=%s input_tokens=%s output_tokens=%s total_tokens=%s",
                    plan_id,
                    step_id,
                    batch_number if batch_number is not None else "none",
                    member_name,
                    getattr(completed_metrics, "input_tokens", 0),
                    getattr(completed_metrics, "output_tokens", 0),
                    getattr(completed_metrics, "total_tokens", 0),
                )
            return completed_content
        return getattr(response_stream, "content", response_stream)

    # 仅为尚未迁移的测试替身保留同步兼容；生产 Agent 必须提供 arun。
    sync_runner = getattr(member, "run", None)
    if not callable(sync_runner):
        raise RuntimeError(f"专业 Agent 不支持异步执行: {member_name}")
    response = await asyncio.to_thread(sync_runner, model_input)
    return getattr(response, "content", response)


def _success(step: StepSpec, artifact: StepArtifact, message: str | None = None) -> StepResult:
    """把已验证的类型化领域产物转换为统一成功结果。"""
    return StepResult(
        step_id=step.step_id,
        operation_type=step.type,
        status=StepStatus.SUCCESS,
        artifact=artifact,
        message=message or "步骤执行成功",
    )


def _failed(step: StepSpec, error_code: str, message: str) -> StepResult:
    """把领域失败转换为稳定错误码，不携带敏感原值。"""
    return StepResult(
        step_id=step.step_id,
        operation_type=step.type,
        status=StepStatus.FAILED,
        error_code=error_code,
        message=message,
    )


def _needs_input(step: StepSpec, error_code: str, message: str) -> StepResult:
    """把缺失输入转换为待输入结果，阻止执行器继续后续步骤。"""
    return StepResult(
        step_id=step.step_id,
        operation_type=step.type,
        status=StepStatus.NEEDS_INPUT,
        error_code=error_code,
        message=message,
    )


# ===== 字段词汇解析（issue #146）：用户可用标准字段名指称字段，解析在执行层完成 =====


def iter_config_entities(config: Any, targets: list[str] | None = None):
    """递归产出 entity dict（含 parser 或 normalize 的 dict）。

    targets 为 None 时产出全部 entity；否则只产出 name 命中名单的 entity。
    """
    target_set = set(targets) if targets else None

    def _walk(node: Any):
        """递归遍历配置，按 entity 特征与目标名单产出。"""
        if isinstance(node, dict):
            name = node.get("name")
            looks_like_entity = isinstance(node.get("parser"), dict) or isinstance(
                node.get("normalize"), list
            )
            if looks_like_entity:
                if target_set is None:
                    yield node
                elif isinstance(name, str) and name in target_set:
                    yield node
            for value in node.values():
                yield from _walk(value)
        elif isinstance(node, list):
            for item in node:
                yield from _walk(item)

    yield from _walk(config)


def field_vocabulary(config: Any, targets: list[str] | None = None) -> list[tuple[str, str]]:
    """目标 entity 的（原始 index, 标准名）对照表，去重保序。"""
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for entity in iter_config_entities(config, targets):
        for entry in entity.get("normalize") or []:
            if not isinstance(entry, dict):
                continue
            index = entry.get("index")
            if not index:
                continue
            pair = (str(index), str(entry.get("field") or ""))
            if pair not in seen:
                seen.add(pair)
                pairs.append(pair)
    return pairs


def format_field_vocabulary(config: Any, targets: list[str] | None = None, limit: int = 30) -> str:
    """把词汇对照表格式化为用户可读字符串（原始名(标准名)、…，超限截断）。"""
    pairs = field_vocabulary(config, targets)
    parts = [
        index if not standard else f"{index}({standard})"
        for index, standard in pairs[:limit]
    ]
    text = "、".join(parts)
    if len(pairs) > limit:
        text += f" 等 {len(pairs)} 项"
    return text


def resolve_field_names(
    config: Any,
    names: list[str],
    targets: list[str] | None = None,
) -> tuple[dict[str, str], list[dict]]:
    """把字段名解析为配置的原始 index（确定性，不经 LLM）。

    逐名规则：
    - 精确命中任一目标 entity 的 normalize index → 原样通过；
    - 否则按 normalize[].field（标准字段名）在目标 entity 内找**唯一**对应
      index → 解析为该 index（用户以映射表展示名指称字段的场景）；
    - 多个不同 index 对应同一标准名 → ambiguous 问题（列候选，不猜）；
    - 零命中 → not_found 问题。

    Returns:
        (resolved: {原名: index}, problems: [{"name", "kind", "candidates"}])
    """
    resolved: dict[str, str] = {}
    problems: list[dict] = []
    for name in names:
        exact = any(
            any(
                isinstance(entry, dict) and entry.get("index") == name
                for entry in entity.get("normalize") or []
            )
            for entity in iter_config_entities(config, targets)
        )
        if exact:
            resolved[name] = name
            continue
        candidates: list[str] = []
        for index, standard in field_vocabulary(config, targets):
            if standard == name and index not in candidates:
                candidates.append(index)
        if len(candidates) == 1:
            resolved[name] = candidates[0]
        elif len(candidates) > 1:
            problems.append(
                {"name": name, "kind": "ambiguous", "candidates": candidates}
            )
        else:
            problems.append({"name": name, "kind": "not_found", "candidates": []})
    return resolved, problems
