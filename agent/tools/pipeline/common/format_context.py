# -*- coding: utf-8 -*-
"""KV 分隔符的类型化单一事实源（#344）。

领域规则源（如 EDR 子规则 parser 配置）对 format_info 键的定义固定为：
``delimit``=字段分隔符（字段之间），``tab``=键值分隔符（key 与 value 之间）。
历史上 KvExtractor/log_feature_locator 曾用同名参数承载相反语义，导致
Step 2a 调用点两值交叉取值必错；收口后所有内部函数一律消费本类型，
禁止再从 format_info dict 就地解析或用二义参数名传递分隔符。
format_info 的 ``delimit``/``tab`` 键名是跨步骤 JSON 接口，保持不动；
dict → FormatContext 的唯一解析点是 :meth:`FormatContext.from_format_info`。
"""

from __future__ import annotations

from typing import Mapping, NamedTuple

DEFAULT_FIELD_DELIMIT = " "
"""字段分隔符缺省值：KV 体以空白分字段（KvExtractor 归一化为空白模式）。"""

DEFAULT_KV_DELIMIT = "="
"""键值分隔符缺省值。"""


class FormatContext(NamedTuple):
    """一条日志的 KV 分隔符上下文（不可变）。"""

    field_delimit: str = DEFAULT_FIELD_DELIMIT
    """字段分隔符（字段之间，如 ";"、空白）。"""

    kv_delimit: str = DEFAULT_KV_DELIMIT
    """键值分隔符（key 与 value 之间，如 "="、":"）。"""

    @classmethod
    def from_format_info(cls, info: Mapping | None) -> "FormatContext":
        """从 format_info dict 解析；空值与缺键回落到默认分隔符。"""
        info = info or {}
        return cls(
            field_delimit=str(info.get("delimit") or DEFAULT_FIELD_DELIMIT),
            kv_delimit=str(info.get("tab") or DEFAULT_KV_DELIMIT),
        )

    def as_format_info(self) -> dict:
        """还原为 format_info dict（delimit=字段分隔符、tab=键值分隔符）。"""
        return {"delimit": self.field_delimit, "tab": self.kv_delimit}
