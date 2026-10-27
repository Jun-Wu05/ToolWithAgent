"""Successful classification counts come from deterministic aggregation (#412)."""
import json
import re

import pytest

from agent.tools.pipeline.common.aggregator import aggregate_by_field
from agent.tools.pipeline.common.llm_postprocessor import postprocess_llm_classification
from agent.tools.pipeline.extractors.json_extractor import JsonExtractor
from agent.tools.pipeline.extractors.kv_extractor import KvExtractor


@pytest.mark.parametrize("sample_format", ["json", "kv", "header"])
def test_success_details_use_aggregate_counts_for_llm_and_backfilled_types(sample_format):
    values = ["AUDIT", "IPS", "AUDIT", "RUN_INFO", "AUDIT", "IPS"]
    if sample_format == "json":
        logs = "\n".join(json.dumps({"kind": value}) for value in values)
        extractor = JsonExtractor().extract_value
    elif sample_format == "kv":
        logs = "\n".join(f"kind={value};id=1" for value in values)
        extractor = KvExtractor(field_delimit=";", kv_delimit="=").extract_value
    else:
        logs = "\n".join(f"<{value}> body" for value in values)
        extractor = lambda line, field: re.match(r"<([^>]+)>", line).group(1)
    aggregation = aggregate_by_field(logs, "kind", extractor)
    response = json.dumps({"status": "SUCCESS", "classification_details": [
        {"logtype": "AUDIT", "count": 999, "meaning": "audit"},
        {"logtype": "IPS", "meaning": "alert"},
        {"logtype": "INVENTED", "count": 20},
        {"meaning": "missing type"},
    ]})

    result = postprocess_llm_classification(
        response, aggregation, logs, extractor, feature_field="kind",
        sample_format=sample_format,
    )

    assert result["status"] == "SUCCESS"
    assert result["feature_count"] == 3
    assert {item["logtype"]: item.get("count") for item in result["classification_details"]} == {
        "AUDIT": 3, "IPS": 2, "RUN_INFO": 1,
    }
    assert sum(item["count"] for item in result["classification_details"]) == aggregation["matched_lines"]
    assert result["classification_details"][0]["meaning"] == "audit"


def test_incomplete_llm_detail_does_not_break_count_backfill():
    result = postprocess_llm_classification(
        '{"classification_details": [{"meaning": "missing type"}]}',
        {"values": {"AUDIT": {"count": 1, "samples": ["audit"]}}},
        "audit", lambda line, field: "AUDIT", feature_field="kind",
    )
    assert result["status"] == "SUCCESS"
    assert [(item["logtype"], item["count"]) for item in result["classification_details"]] == [("AUDIT", 1)]
