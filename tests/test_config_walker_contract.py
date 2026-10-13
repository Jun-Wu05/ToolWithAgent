"""配置树单一遍历器 iter_normalize_entries 的契约测试（#313）。

锁定收口前 13 处变体各自依赖的语义：dict/list 两种根形态等价、
路径约定（贡献账本可按段导航 / 画像键可 str 化）、require_index 与
excluded_indexes 过滤、非 dict 条目跳过、迭代中原地可变、
entity 迭代名单过滤与名字收集去重保序。
"""

from agent.shared.mapping_utils import (
    collect_config_names,
    iter_config_entities,
    iter_normalize_entries,
)


def _sample_tree():
    """两层嵌套 + 混合条目形态的配置树。"""
    return {
        "rules": [
            {
                "name": "rule_a",
                "normalize": [
                    {"index": "src_ip", "field": "源地址"},
                    {"index": "original_log"},
                    {"index": "  ", "field": "x"},
                    "not-a-dict",
                ],
            },
            {"name": "rule_b", "normalize": []},
        ],
        "nested": {"deep": [{"name": "rule_c", "normalize": [{"index": "dst_ip"}]}]},
    }


def test_list根与dict子树产出一致():
    """规则列表根与包它的 dict 树遍历到相同的条目序列。"""
    tree = _sample_tree()
    from_list = [
        (path, position, entry)
        for path, position, _owner, entry in iter_normalize_entries(tree["rules"])
    ]
    from_tree = [
        (path[1:], position, entry)
        for path, position, _owner, entry in iter_normalize_entries(tree)
        if path[:1] == ("rules",)
    ]
    assert [e for _p, _i, e in from_list] == [e for _p, _i, e in from_tree]
    assert from_list[0][0] == (0,)
    assert from_list[0][2]["index"] == "src_ip"


def test默认过滤空白index_元字段与非法条目():
    entries = [
        entry
        for _p, _i, _o, entry in iter_normalize_entries(
            _sample_tree(), excluded_indexes={"original_log"}
        )
    ]
    assert [e["index"] for e in entries] == ["src_ip", "dst_ip"]


def test_require_index_false保留全部dict条目():
    entries = [
        entry
        for _p, _i, _o, entry in iter_normalize_entries(
            _sample_tree(), require_index=False
        )
    ]
    # rule_a 的 3 个 dict 条目（含 original_log 与空白 index）+ rule_c 的 1 个；
    # "not-a-dict" 跳过、空 normalize 的 rule_b 不产出。
    assert len(entries) == 4


def test路径可按段导航回条目本身():
    """(*owner_path, "normalize", position) 逐段取值必须命中产出条目。"""
    tree = _sample_tree()
    for owner_path, position, _owner, entry in iter_normalize_entries(tree):
        node = tree
        for segment in (*owner_path, "normalize", position):
            node = node[segment]
        assert node is entry


def test画像键str化且与收口前约定一致():
    """str(owner_path) + index 的键形态 = standard_enum_mapping.ProfileKey。"""
    keys = [
        (*tuple(str(s) for s in owner_path), str(entry.get("index") or "").strip())
        for owner_path, _p, _o, entry in iter_normalize_entries(_sample_tree())
    ]
    # 不传 excluded_indexes 时元字段照常产出（过滤是显式参数，#313 契约）。
    assert keys == [
        ("rules", "0", "src_ip"),
        ("rules", "0", "original_log"),
        ("nested", "deep", "0", "dst_ip"),
    ]


def test迭代中修改条目反映到原配置():
    tree = _sample_tree()
    for _p, _i, _o, entry in iter_normalize_entries(tree):
        entry["touched"] = True
    assert tree["rules"][0]["normalize"][0]["touched"] is True
    assert tree["nested"]["deep"][0]["normalize"][0]["touched"] is True


def test_tuple容器与dict根等价遍历():
    config = {"normalize": [{"index": "a"}], "children": ({"normalize": [{"index": "b"}]},)}
    indexes = [str(e.get("index")) for _p, _i, _o, e in iter_normalize_entries(config)]
    assert indexes == ["a", "b"]


def test_iter_config_entities按特征产出并支持名单过滤():
    tree = _sample_tree()
    names = [e.get("name") for e in iter_config_entities(tree)]
    assert names == ["rule_a", "rule_b", "rule_c"]
    only_b = list(iter_config_entities(tree, ["rule_b"]))
    assert [e["name"] for e in only_b] == ["rule_b"]


def test_collect_config_names去重保序():
    tree = {
        "name": "outer",
        "rules": [{"name": "rule_a"}, {"name": "rule_a"}, {"name": "rule_b"}],
    }
    assert collect_config_names(tree) == ["outer", "rule_a", "rule_b"]


def test_resolve_standard_target与填充链同源解析():
    """目标解析与填充消费同一遍历（#330）：解析出的目标恰是填充命中的条目。"""
    from agent.shared.mapping_utils import apply_fill_to_config
    from application.artifact_targets import resolve_standard_target

    config = {
        "normalize": [
            {"index": "alarm_name", "field": "event_name", "mappings": []},
            {"index": "other", "field": "别的字段", "mappings": []},
        ]
    }

    assert resolve_standard_target(config, "alarm_name") == "event_name"
    assert resolve_standard_target(config, "不存在") is None
    # 同一来源命中多个不同目标 → 不唯一，拒绝解析（调用方按无绑定处理）
    ambiguous = {
        "normalize": [
            {"index": "shared", "field": "f1"},
            {"index": "shared", "field": "f2"},
        ]
    }
    assert resolve_standard_target(ambiguous, "shared") is None

    filled = apply_fill_to_config(
        config,
        {"event_name": [{"mappingType": "EQUAL", "orgValue": "x", "mappingValue": "y"}]},
    )
    assert filled["normalize"][0]["mappings"] == [
        {"mappingType": "EQUAL", "orgValue": "x", "mappingValue": "y"}
    ]
    assert filled["normalize"][1]["mappings"] == []
