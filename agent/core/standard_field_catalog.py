"""Read-only standard-field facts, resource parsing, and deterministic lookup."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence


STANDARD_FIELD_COLUMNS = (
    "系统属性名称",
    "属性分类",
    "字段名称",
    "属性类型",
    "描述",
    "枚举值",
    "对象",
)

_ROOT = Path(__file__).parents[2]
_STANDARD_FIELDS_PATH = _ROOT / "config" / "标准字段.txt"
_SYNONYMS_PATH = _ROOT / "config" / "field_synonyms.json"
_TAG_RULES_PATH = _ROOT / "config" / "tag_rules.json"


def normalize_field_name(name: str) -> str:
    """Normalize snake, kebab, and camel-case field names to one lookup key."""
    normalized = name.replace("-", "_")
    normalized = re.sub(r"([a-z])([A-Z])", r"\1_\2", normalized)
    normalized = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", normalized)
    return normalized.lower()


def compact_field_name(name: str) -> str:
    """Return a separator-free secondary lookup key."""
    return re.sub(r"[_\-\s]", "", name).lower()


@dataclass(frozen=True, slots=True)
class StandardField:
    """One immutable row from the standard-field resource."""

    system_property_name: str
    category: str
    field_name: str
    data_type: str
    description: str
    enum_values: str
    objects: str

    def as_record(self) -> dict[str, str]:
        """Return a mutable compatibility copy using the historical column names."""
        return dict(
            zip(
                STANDARD_FIELD_COLUMNS,
                (
                    self.system_property_name,
                    self.category,
                    self.field_name,
                    self.data_type,
                    self.description,
                    self.enum_values,
                    self.objects,
                ),
            )
        )


class StandardFieldCatalog:
    """Immutable catalog of standard fields and their deterministic lookup keys."""

    def __init__(
        self,
        fields: Sequence[StandardField],
        synonyms: Mapping[str, Mapping[str, Any]],
        tag_rules: Mapping[str, Sequence[str]],
        standard_fields_text: str = "",
    ) -> None:
        self._fields = tuple(fields)
        self._synonyms = _freeze_synonyms(synonyms)
        self._tag_rules = MappingProxyType(
            {name: tuple(keywords) for name, keywords in tag_rules.items()}
        )
        self._standard_fields_text = standard_fields_text
        self._name_index = MappingProxyType(
            self.build_name_index(field.as_record() for field in self._fields)
        )

    @classmethod
    def from_default_resources(cls) -> "StandardFieldCatalog":
        """Load the repository's standard-field resources."""
        return cls.from_resources(
            _STANDARD_FIELDS_PATH,
            _SYNONYMS_PATH,
            _TAG_RULES_PATH,
        )

    @classmethod
    def from_resources(
        cls,
        standard_fields_path: Path,
        synonyms_path: Path,
        tag_rules_path: Path,
    ) -> "StandardFieldCatalog":
        """Parse resource files without performing network or retrieval work."""
        standard_fields_text = standard_fields_path.read_text(encoding="utf-8")
        fields = _parse_standard_fields(standard_fields_text)
        synonyms = _read_json_mapping(synonyms_path)
        tag_resource = _read_json_mapping(tag_rules_path)
        raw_rules = tag_resource.get("rules", tag_resource)
        tag_rules = raw_rules if isinstance(raw_rules, Mapping) else {}
        return cls(fields, synonyms, tag_rules, standard_fields_text)

    @property
    def fields(self) -> tuple[StandardField, ...]:
        return self._fields

    @property
    def synonyms(self) -> Mapping[str, Mapping[str, Any]]:
        return self._synonyms

    @property
    def tag_rules(self) -> Mapping[str, tuple[str, ...]]:
        return self._tag_rules

    @property
    def name_index(self) -> Mapping[str, int]:
        return self._name_index

    @property
    def standard_fields_text(self) -> str:
        return self._standard_fields_text

    def records(self) -> list[dict[str, str]]:
        """Return defensive mutable copies for legacy consumers."""
        return [field.as_record() for field in self._fields]

    def lookup(self, name: str) -> StandardField | None:
        """Look up by field name, normalized alias, or Chinese system name."""
        for key in _lookup_keys(name):
            index = self._name_index.get(key)
            if index is not None:
                return self._fields[index]
        return None

    def build_name_index(
        self, records: Iterable[Mapping[str, Any]]
    ) -> dict[str, int]:
        """Build the historical first-wins index for an ordered record set."""
        index: dict[str, int] = {}
        field_name_to_index: dict[str, int] = {}
        for position, record in enumerate(records):
            field_name = str(record.get("字段名称", ""))
            if not field_name:
                continue
            for key in (
                normalize_field_name(field_name),
                compact_field_name(field_name),
            ):
                index.setdefault(key, position)
            field_name_to_index.setdefault(field_name.lower(), position)
            system_name = str(record.get("系统属性名称", ""))
            if system_name:
                index.setdefault(system_name, position)

        for synonym_key, entry in self._synonyms.items():
            target = field_name_to_index.get(synonym_key.lower())
            if target is None:
                continue
            for alias in entry.get("zh", ()):
                if not alias:
                    continue
                index.setdefault(str(alias), target)
        return index


def _parse_standard_fields(raw: str) -> tuple[StandardField, ...]:
    lines = [line.strip() for line in raw.strip().splitlines() if line.strip()]
    if not lines:
        return ()
    header = tuple(column.strip() for column in lines[0].split("\t"))
    if header:
        header = (header[0].lstrip("\ufeff"), *header[1:])
    if header != STANDARD_FIELD_COLUMNS:
        raise ValueError(f"Unexpected standard-field schema: {header!r}")

    fields: list[StandardField] = []
    for line in lines[1:]:
        columns = [column.strip() for column in line.split("\t")]
        columns.extend([""] * (len(STANDARD_FIELD_COLUMNS) - len(columns)))
        fields.append(StandardField(*columns[: len(STANDARD_FIELD_COLUMNS)]))
    return tuple(fields)


def _lookup_keys(name: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys((name, normalize_field_name(name), compact_field_name(name))))


def _read_json_mapping(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, Mapping) else {}


def _freeze_synonyms(
    synonyms: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Mapping[str, Any]]:
    frozen: dict[str, Mapping[str, Any]] = {}
    for name, entry in synonyms.items():
        if not isinstance(entry, Mapping):
            continue
        frozen[name] = MappingProxyType(
            {
                "en": str(entry.get("en", "")),
                "zh": tuple(str(alias) for alias in entry.get("zh", ())),
            }
        )
    return MappingProxyType(frozen)


# ---------------------------------------------------------------------------
# 标准枚举自动映射策略（#189）
# ---------------------------------------------------------------------------

ENUM_AUTO_MAPPING_TARGETS: Mapping[str, str] = MappingProxyType({
    "HTTP请求方法": "其他",
    "操作系统平台": "others",
    "事件状态": "未知",
    "事件结果": "未知",
    "威胁等级": "提醒",
    "攻击结果": "未知",
    "登录系统": "未知",
    "事件动作": "未知",
})
"""参与标准枚举自动映射的标准字段 → 外层 value 默认值。

白名单唯一来源仍是标准字段表的「枚举值」列；本表不复制枚举集合。
"""

ENUM_AUTO_MAPPING_EXCLUSIONS: tuple[str, ...] = ("操作类型", "威胁类型")
"""显式排除的标准字段：操作类型由事件绑定链持有（#395），威胁类型走 #173 独立链路。"""

ENUM_UNIQUE_VALUE_LIMIT = 10
"""单个值画像允许的唯一值上限：第 11 个出现即整体拒绝，不截断。"""


@dataclass(frozen=True, slots=True)
class EnumMappingPolicy:
    """一个标准枚举字段的自动映射策略。"""

    system_property_name: str
    field_name: str
    default_value: str
    whitelist: tuple[str, ...]


def enum_auto_mapping_policies() -> dict[str, EnumMappingPolicy]:
    """从目录事实解析 8 个目标字段的枚举策略，配置漂移时立即失败。

    校验：目标行存在、属性类型为「枚举」、白名单非空、默认值属于白名单、
    排除字段不得出现在目标集合中（启动/测试期验证默认值合法性的唯一入口）。
    """
    catalog = get_standard_field_catalog()
    overlap = ENUM_AUTO_MAPPING_EXCLUSIONS and set(ENUM_AUTO_MAPPING_EXCLUSIONS) & set(
        ENUM_AUTO_MAPPING_TARGETS
    )
    if overlap:
        raise ValueError(f"枚举自动映射排除字段与目标重叠: {sorted(overlap)}")
    policies: dict[str, EnumMappingPolicy] = {}
    for system_name, default_value in ENUM_AUTO_MAPPING_TARGETS.items():
        field = next(
            (item for item in catalog.fields if item.system_property_name == system_name),
            None,
        )
        if field is None:
            raise ValueError(f"枚举自动映射目标字段不存在: {system_name}")
        if field.data_type != "枚举":
            raise ValueError(
                f"枚举自动映射目标 {system_name} 属性类型为 {field.data_type!r}，应为「枚举」"
            )
        whitelist = tuple(
            value.strip() for value in field.enum_values.split(",") if value.strip()
        )
        if not whitelist:
            raise ValueError(f"枚举自动映射目标 {system_name} 白名单为空")
        if default_value not in whitelist:
            raise ValueError(
                f"枚举自动映射目标 {system_name} 默认值 {default_value!r} 不在白名单内"
            )
        policies[system_name] = EnumMappingPolicy(
            system_property_name=system_name,
            field_name=field.field_name,
            default_value=default_value,
            whitelist=whitelist,
        )
    return policies


def resolve_enum_field(raw_field_name: str) -> tuple[str, str] | None:
    """确定性解析原始字段名是否命中 8 个枚举自动映射目标之一。

    返回 ``(系统属性名称, 来源)``，来源为 ``exact``（规范化名/紧凑名等于目标
    英文字段名）或 ``synonym``（目录中文别名或 field_synonyms 的 en 同义词指向
    目标英文名）；未命中目标（含命中其他标准字段）返回 None，字段继续走
    既有候选检索 + LLM 主路径。
    """
    policies = enum_auto_mapping_policies()
    catalog = get_standard_field_catalog()
    record = catalog.lookup(raw_field_name)
    if record is not None and record.system_property_name in policies:
        if (
            normalize_field_name(raw_field_name) == normalize_field_name(record.field_name)
            or compact_field_name(raw_field_name) == compact_field_name(record.field_name)
        ):
            return record.system_property_name, "exact"
        return record.system_property_name, "synonym"

    normalized = normalize_field_name(raw_field_name)
    compact = compact_field_name(raw_field_name)
    for synonym_key, entry in catalog.synonyms.items():
        target = next(
            (
                policy
                for policy in policies.values()
                if policy.field_name == str(entry.get("en", ""))
            ),
            None,
        )
        if target is None:
            continue
        key_normalized = normalize_field_name(str(synonym_key))
        if normalized == key_normalized or compact == compact_field_name(str(synonym_key)):
            return target.system_property_name, "synonym"
    return None


@lru_cache(maxsize=1)
def get_standard_field_catalog() -> StandardFieldCatalog:
    """Return the process-wide immutable default catalog."""
    return StandardFieldCatalog.from_default_resources()
