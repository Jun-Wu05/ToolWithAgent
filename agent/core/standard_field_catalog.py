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


@lru_cache(maxsize=1)
def get_standard_field_catalog() -> StandardFieldCatalog:
    """Return the process-wide immutable default catalog."""
    return StandardFieldCatalog.from_default_resources()
