"""Issue #165：字段映射目标一对一冲突的确定性裁决。"""

from __future__ import annotations


def _row(original: str, standard: str = "源IP") -> dict[str, str]:
    return {
        "原始字段名": original,
        "系统属性名称": standard,
        "匹配状态": "匹配成功",
    }


def _candidates(**rows: tuple):
    """构造结构化候选检索假件（#180 候选表：字段 → [(标准名, 得分, 英文名, 变体)]）。"""
    calls: list[tuple[str, ...]] = []

    def retrieve(fields):
        calls.append(tuple(fields))
        return {field: list(items) for field, items in rows.items()}

    retrieve.calls = calls
    return retrieve


def test精确命中优先于普通相似度() -> None:
    from application.field_mapping_conflicts import resolve_field_mapping_conflicts

    retriever = _candidates(
        src=[("源IP", 0.96, "source_ip", "")],
        client=[("源IP", 1.00, "client", "")],
    )

    outcome = resolve_field_mapping_conflicts(
        [_row("src"), _row("client")], candidate_retriever=retriever
    )

    assert outcome.rows[0]["匹配状态"] == "未匹配"
    assert outcome.rows[1]["匹配状态"] == "匹配成功"
    assert outcome.details[0].winner == "client"
    assert outcome.details[0].reason == "精确命中（1.00）"


def test目标候选相似度高者优先() -> None:
    from application.field_mapping_conflicts import resolve_field_mapping_conflicts

    retriever = _candidates(
        src=[("源IP", 0.72, "source_ip", "")],
        client=[("源IP", 0.88, "client_address", "")],
    )

    outcome = resolve_field_mapping_conflicts(
        [_row("src"), _row("client")], candidate_retriever=retriever
    )

    assert outcome.details[0].winner == "client"
    assert outcome.details[0].losers == ("src",)
    assert outcome.details[0].reason == "候选相似度 0.88"


def test同分时按原行序且三行只保留一个() -> None:
    from application.field_mapping_conflicts import resolve_field_mapping_conflicts

    retriever = _candidates(
        first=[("源IP", 0.80, "first_ip", "")],
        second=[("源IP", 0.80, "second_ip", "")],
        third=[("源IP", 0.80, "third_ip", "")],
    )

    outcome = resolve_field_mapping_conflicts(
        [_row("first"), _row("second"), _row("third")],
        candidate_retriever=retriever,
    )

    assert [row["匹配状态"] for row in outcome.rows] == [
        "匹配成功",
        "未匹配",
        "未匹配",
    ]
    assert outcome.details[0].winner == "first"
    assert outcome.details[0].losers == ("second", "third")
    assert outcome.details[0].reason == "原行序优先"


def test候选检索失败降级行序且不抛错() -> None:
    from application.field_mapping_conflicts import resolve_field_mapping_conflicts

    def unavailable(_fields):
        raise RuntimeError("embedding unavailable")

    outcome = resolve_field_mapping_conflicts(
        [_row("first"), _row("second")], candidate_retriever=unavailable
    )

    assert outcome.details[0].winner == "first"
    assert outcome.details[0].reason == "候选检索不可用，按原行序"
    assert outcome.rows[1] == {
        "原始字段名": "second",
        "系统属性名称": "未匹配",
        "匹配状态": "未匹配",
    }


def test无冲突直通且不调用候选检索() -> None:
    from application.field_mapping_conflicts import resolve_field_mapping_conflicts

    retriever = _candidates()
    rows = [_row("src", "源IP"), _row("dst", "目的IP")]

    outcome = resolve_field_mapping_conflicts(rows, candidate_retriever=retriever)

    assert list(outcome.rows) == rows
    assert outcome.details == ()
    assert retriever.calls == []


def test上传配置既有映射占用时新行落选() -> None:
    from application.field_mapping_conflicts import resolve_field_mapping_conflicts

    decoded_data = {
        "normalize": [
            {"index": "external_src", "field": "源IP"},
            {"index": "external_src", "field": "源IP"},
            {"index": "client_ip", "field": ""},
        ]
    }

    outcome = resolve_field_mapping_conflicts(
        [_row("client_ip")],
        decoded_data=decoded_data,
        candidate_retriever=lambda fields: {
            "client_ip": [("源IP", 1.00, "client_ip", "")]
        },
    )

    assert outcome.rows[0]["匹配状态"] == "未匹配"
    assert outcome.details[0].winner == "external_src"
    assert outcome.details[0].losers == ("client_ip",)
    assert outcome.details[0].reason == "既有上传映射占用"
