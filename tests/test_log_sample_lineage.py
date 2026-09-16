"""Issue #191：下游样本补齐不得改写确定性类型血缘。"""

from agent.tools import fill_log_samples


def test_existing_deterministic_sample_is_not_replaced_by_prefix_match() -> None:
    """已有 sample 是上游权威结果；real_samples 必须从同一行补齐。"""
    auth_fail_line = "type=AUTH_FAIL message=failed"
    auth_line = "type=AUTH message=ok"
    classification = {
        "feature_identifier": "",
        "classification_details": [
            {"logtype": "AUTH", "sample": auth_line},
        ],
    }

    result = fill_log_samples(
        classification,
        "\n".join([auth_fail_line, auth_line]),
    )

    detail = result["classification_details"][0]
    assert detail["sample"] == auth_line
    assert detail["real_samples"] == auth_line


def test_existing_deterministic_real_sample_is_preserved() -> None:
    """上游已补齐的 real_samples 与 sample 一样是权威结果。"""
    classification = {
        "feature_identifier": "",
        "classification_details": [
            {
                "logtype": "AUTH",
                "sample": "header type=AUTH message=ok",
                "real_samples": "type=AUTH message=ok",
            },
        ],
    }

    result = fill_log_samples(
        classification,
        "type=AUTH_FAIL message=failed",
    )

    detail = result["classification_details"][0]
    assert detail["sample"] == "header type=AUTH message=ok"
    assert detail["real_samples"] == "type=AUTH message=ok"


def test_missing_sample_does_not_borrow_line_from_prefixed_type() -> None:
    """AUTH 不得通过子串包含关系借用 AUTH_FAIL 的日志。"""
    classification = {
        "feature_identifier": "",
        "classification_details": [
            {"logtype": "AUTH", "matched_regex": "AUTH"},
        ],
    }

    result = fill_log_samples(
        classification,
        "type=AUTH_FAIL message=failed",
    )

    detail = result["classification_details"][0]
    assert detail.get("sample", "[匹配失败]") == "[匹配失败]"
    assert detail["real_samples"] == "[匹配失败]"


def test_missing_sample_is_filled_only_by_exact_feature_capture() -> None:
    """结构化捕获值与 logtype 严格相等时，才可从同一行补齐样本。"""
    auth_fail_line = "type=AUTH_FAIL message=failed"
    auth_line = "type=AUTH message=ok"
    classification = {
        "feature_identifier": r"^(.*?type=(AUTH(?:_FAIL)?)\s.*)$",
        "feature_body_group": 1,
        "feature_value_group": 2,
        "classification_details": [{"logtype": "AUTH"}],
    }

    result = fill_log_samples(
        classification,
        "\n".join([auth_fail_line, auth_line]),
    )

    detail = result["classification_details"][0]
    assert detail["sample"] == auth_line
    assert detail["real_samples"] == auth_line
