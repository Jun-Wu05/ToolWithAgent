import copy
import pytest
from agent.tools.rule_generator import apply_manual_field_mappings


def test_manual_mapping_is_atomic_positional_and_clears_obsolete_values():
    config=[{"name":"duplicate","normalize":[{"index":"a","field":"源地址","entity":"event","result":["raw"],"mappings":[{"orgValue":"raw","mappingValue":"old"}],"value":"old"}]},
            {"name":"duplicate","normalize":[{"index":"a","field":"目的地址","result":["other"]}]}]
    before=copy.deepcopy(config)
    result=apply_manual_field_mappings(config,[{"sub_rule_id":"0","source_path":"a","standard_field":"源端口"}])
    assert config==before and result[1]==config[1]
    entry=result[0]["normalize"][0]
    assert entry["field"]=="源端口" and entry["result"]==["raw"] and "mappings" not in entry and "value" not in entry
    result=apply_manual_field_mappings(config,[{"sub_rule_id":"0","source_path":"a","standard_field":None}])
    assert result[0]["normalize"][0]["index"]=="a" and result[0]["normalize"][0]["field"] is None
    with pytest.raises(ValueError):
        apply_manual_field_mappings(config,[{"sub_rule_id":"0","source_path":"a","standard_field":"源端口"},{"sub_rule_id":"1","source_path":"a","standard_field":"src_ip"}])
    assert config==before


@pytest.mark.parametrize("change",[
    {"sub_rule_id":"00","source_path":"a","standard_field":"源地址"},
    {"sub_rule_id":"1","source_path":"a","standard_field":"源地址"},
    {"sub_rule_id":"0","source_path":"original_log","standard_field":None},
    {"sub_rule_id":"0","source_path":"a","standard_field":"威胁类型"},
])
def test_illegal_manual_choice_does_not_mutate_config(change):
    config=[{"normalize":[{"index":"a","field":None},{"index":"original_log","field":None}]}]
    before=copy.deepcopy(config)
    with pytest.raises(ValueError):
        apply_manual_field_mappings(config,[change])
    assert config==before


def test_manual_complete_batch_allows_swap_but_rejects_duplicate_target():
    config=[{"normalize":[{"index":"a","field":"源地址"},{"index":"b","field":"目的地址"}]}]
    result=apply_manual_field_mappings(config,[{"sub_rule_id":"0","source_path":"a","standard_field":"目的地址"},{"sub_rule_id":"0","source_path":"b","standard_field":"源地址"}])
    assert [item["field"] for item in result[0]["normalize"]]==["目的地址","源地址"]
    with pytest.raises(ValueError,match="mapping_target_conflict"):
        apply_manual_field_mappings(config,[{"sub_rule_id":"0","source_path":"a","standard_field":"目的地址"}])
