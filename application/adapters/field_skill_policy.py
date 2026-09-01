"""Pure shared policies used by FieldSkillAdapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping


ReferenceKind = Literal["merger", "placeholder"]


@dataclass(frozen=True, slots=True)
class DanglingFieldReference:
    """A field reference that would become invalid after deletion."""

    entity_name: str
    kind: ReferenceKind
    fields: tuple[str, ...]


def find_dangling_references(
    entities: Iterable[Mapping[str, Any]],
    deleted_names: Iterable[str],
) -> tuple[DanglingFieldReference, ...]:
    """Find merger sources and ``%{field}`` placeholders targeting deleted fields."""
    deleted = set(deleted_names)
    conflicts: list[DanglingFieldReference] = []
    for entity in entities:
        name = entity.get("name") or "<未命名>"
        parser = entity.get("parser") or {}
        for filter_item in parser.get("filter") or []:
            if not isinstance(filter_item, dict):
                continue
            if filter_item.get("name") == "merger":
                overlap = tuple(sorted(deleted & set(filter_item.get("fields") or [])))
                if overlap:
                    conflicts.append(DanglingFieldReference(str(name), "merger", overlap))
            fields = filter_item.get("fields")
            if isinstance(fields, dict):
                for value in fields.values():
                    if not isinstance(value, str):
                        continue
                    references = tuple(
                        sorted(field for field in deleted if f"%{{{field}}}" in value)
                    )
                    if references:
                        conflicts.append(
                            DanglingFieldReference(
                                str(name), "placeholder", (references[0],)
                            )
                        )
    return tuple(conflicts)
