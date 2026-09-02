"""规则数据源字段的跨层值对象。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuleSourceFields:
    """用户显式提供、在同一主数据生命周期内复用的规则来源信息。"""

    product: str
    log_vendor: str
    data_source: str = ""

    def __post_init__(self) -> None:
        """保证直接构造与表单工厂拥有相同的不变量。"""
        normalized_product = str(self.product or "").strip()
        normalized_vendor = str(self.log_vendor or "").strip()
        normalized_source = str(self.data_source or "").strip()
        missing: list[str] = []
        if not normalized_product:
            missing.append("数据源产品")
        if not normalized_vendor:
            missing.append("数据源厂商")
        if missing:
            raise ValueError(f"请填写{'、'.join(missing)}")
        object.__setattr__(self, "product", normalized_product)
        object.__setattr__(self, "log_vendor", normalized_vendor)
        object.__setattr__(
            self,
            "data_source",
            normalized_source or f"{normalized_product}({normalized_vendor})",
        )

    @classmethod
    def create(
        cls,
        *,
        product: Any,
        log_vendor: Any,
        data_source: Any = "",
    ) -> "RuleSourceFields":
        """清理表单值、校验必填项，并补全默认数据源。"""
        return cls(
            product=product,
            log_vendor=log_vendor,
            data_source=data_source,
        )

    @classmethod
    def from_value(cls, value: Any) -> "RuleSourceFields | None":
        """把会话中的值对象或字典规范化为同一契约。"""
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            try:
                return cls.create(
                    product=value.get("product"),
                    log_vendor=value.get("log_vendor"),
                    data_source=value.get("data_source"),
                )
            except ValueError:
                return None
        return None


__all__ = ["RuleSourceFields"]
