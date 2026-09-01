"""Issue #160：Field Skill 删除前悬空引用共享策略。"""

from __future__ import annotations


def test_reference_policy_detects_merger_and_placeholder_conflicts() -> None:
    from application.adapters.field_skill_policy import find_dangling_references

    entities = [
        {
            "name": "rule-a",
            "parser": {
                "filter": [
                    {"name": "merger", "fields": ["src", "dst", "keep"]},
                    {"name": "addFields", "fields": {"copy": "%{src}-x"}},
                ]
            },
        },
        {
            "name": "rule-b",
            "parser": {
                "filter": [{"name": "addFields", "fields": {"copy": "%{keep}"}}]
            },
        },
    ]

    conflicts = find_dangling_references(entities, ["dst", "src"])

    assert [(item.entity_name, item.kind, item.fields) for item in conflicts] == [
        ("rule-a", "merger", ("dst", "src")),
        ("rule-a", "placeholder", ("src",)),
    ]


def test_reference_policy_ignores_unrelated_or_malformed_filters() -> None:
    from application.adapters.field_skill_policy import find_dangling_references

    entities = [
        {
            "parser": {
                "filter": [
                    None,
                    "bad",
                    {"name": "merger", "fields": ["keep"]},
                    {"name": "addFields", "fields": {"copy": 123}},
                ]
            }
        }
    ]

    assert find_dangling_references(entities, ["deleted"]) == ()
