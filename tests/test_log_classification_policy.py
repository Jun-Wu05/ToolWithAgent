"""Issue #159：日志体特征键覆盖率路由策略。"""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("feature_field", "coverage", "expected", "reason"),
    [
        ("Type", 0.0, False, "insufficient_coverage"),
        ("Type", 0.799, False, "insufficient_coverage"),
        ("Type", 0.8, True, "body_key_coverage"),
        ("Type", 1.0, True, "body_key_coverage"),
        ("", 1.0, False, "missing_feature_field"),
        ("   ", 1.0, False, "missing_feature_field"),
        ("__header__", 1.0, False, "header_feature"),
    ],
)
def test_body_key_route_policy_has_stable_boundary(
    feature_field, coverage, expected, reason
) -> None:
    from agent.tools.pipeline.classification_policy import decide_body_key_route

    decision = decide_body_key_route(feature_field, coverage)

    assert decision.use_body_path is expected
    assert decision.coverage == coverage
    assert decision.reason == reason


def test_body_key_route_policy_rejects_invalid_coverage() -> None:
    from agent.tools.pipeline.classification_policy import decide_body_key_route

    with pytest.raises(ValueError, match="coverage"):
        decide_body_key_route("Type", -0.01)
    with pytest.raises(ValueError, match="coverage"):
        decide_body_key_route("Type", 1.01)
