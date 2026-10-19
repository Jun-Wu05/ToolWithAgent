"""正则提取模式生成（skills 扩展：regex-extract-field）。

LLM 只负责一件事：给定被提取字段的样本值与提取目标描述，生成一个
**必须全匹配整条样本**的正则（第一个捕获组为提取值）。生成结果经
确定性校验（re.compile + fullmatch），非法或不匹配带反馈重试一次，
仍失败抛 RegexGenerationError——正则的正确性不依赖 LLM 自觉。

正则提取的运行时约束（来自技能设计文档）：非全匹配整条日志的正则
在解析器中不生效，因此校验是硬性的。
"""

from __future__ import annotations

import json
import re
from typing import Any

from agent.shared.llm_response import strip_code_fences
from agent.shared.logger import get_logger

logger = get_logger("regex_extract")

_SAMPLE_MAX_CHARS = 4000
_MAX_ATTEMPTS = 2

_PROMPT_TEMPLATE = """# 正则提取任务

给定一个字段的样本值和提取目标，生成一个 Java 风格正则表达式，满足：

1. **必须全匹配（fullmatch）整条样本值**——从第一个字符到最后一个字符，
   首尾用 `[\\S\\s]*` 包容前后缀是常用手法；
2. **第一个捕获组 `(.*?)` 恰好捕获要提取的值**；
3. 只提取第一个匹配项；正则需兼容样本中的 `\\r\\n`（写作 `\\\\r\\\\n`）等转义；
4. 只输出 JSON，格式：{{"pattern": "<正则字符串>"}}

## 被提取字段
{source_field}

## 提取目标
{description}

## 样本值（必须整条全匹配）
```
{sample}
```
"""


class RegexGenerationError(RuntimeError):
    """正则生成失败（重试后仍非法或无法全匹配样本）。"""


def _extract_pattern(raw_text: str) -> str:
    """从 LLM 响应提取 pattern 字段；容忍 markdown 代码块包装。

    json.loads 的异常上抛语义保持不变（调用方依赖异常触发重试），
    围栏剥离统一走共享原语。
    """
    text = strip_code_fences(raw_text)
    data = json.loads(text)
    if isinstance(data, dict) and data.get("pattern"):
        return str(data["pattern"])
    raise ValueError("输出缺少 pattern 字段")


async def generate_extraction_pattern(
    sample_text: str,
    source_field: str,
    description: str,
    *,
    llm_client: Any = None,
) -> str:
    """生成并校验正则提取模式。

    Args:
        sample_text: 被提取字段的样本值（必须非空，否则无生成依据）。
        source_field: 被提取字段名（进提示词供语义理解）。
        description: 提取目标描述（如 "client"、"请求头里的 Referer"）。
        llm_client: 依赖注入接缝；缺省走工具门面 ``call_llm_direct``。

    Returns:
        通过 re.compile 与 fullmatch 校验的正则字符串。

    Raises:
        RegexGenerationError: 重试一次后仍非法或无法全匹配。
    """
    import asyncio
    import functools

    sample = str(sample_text)[:_SAMPLE_MAX_CHARS]
    if not sample.strip():
        raise RegexGenerationError("被提取字段没有可用样本，无法生成正则")

    async def _call(prompt: str) -> str:
        if llm_client is not None:
            response = llm_client(prompt)
            if hasattr(response, "__await__"):
                response = await response
            return str(response)
        from agent.tools import call_llm_direct

        return await asyncio.get_running_loop().run_in_executor(
            None, functools.partial(call_llm_direct, prompt)
        )

    base_prompt = _PROMPT_TEMPLATE.format(
        source_field=source_field, description=description, sample=sample
    )
    prompt = base_prompt
    last_error = ""
    for _attempt in range(_MAX_ATTEMPTS):
        raw = await _call(prompt)
        try:
            pattern = _extract_pattern(raw)
            compiled = re.compile(pattern)
        except (json.JSONDecodeError, ValueError, re.error) as error:
            last_error = f"输出不合法: {error}"
        else:
            if compiled.fullmatch(sample) is not None:
                logger.info(
                    "[REGEX_EXTRACT] 正则生成成功: source=%s description=%s pattern=%s",
                    source_field,
                    description,
                    pattern,
                )
                return pattern
            last_error = "正则无法全匹配样本"
        prompt = f"{base_prompt}\n上一次输出的问题：{last_error}。请修正后重新输出 JSON。"

    logger.warning(
        "[REGEX_EXTRACT] 正则生成失败: source=%s description=%s error=%s",
        source_field,
        description,
        last_error,
    )
    raise RegexGenerationError(f"正则生成失败（{last_error}）")
