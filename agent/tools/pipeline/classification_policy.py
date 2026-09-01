"""Pure routing policies for log classification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


BODY_KEY_COVERAGE_THRESHOLD = 0.8
BodyKeyRouteReason = Literal[
    "body_key_coverage",
    "insufficient_coverage",
    "missing_feature_field",
    "header_feature",
]


@dataclass(frozen=True, slots=True)
class BodyKeyRouteDecision:
    """Decision to use deterministic body-key classification."""

    use_body_path: bool
    coverage: float
    reason: BodyKeyRouteReason


def decide_body_key_route(
    feature_field: str,
    coverage: float,
) -> BodyKeyRouteDecision:
    """Choose the body path when a real feature key covers at least 80% of lines."""
    if not 0.0 <= coverage <= 1.0:
        raise ValueError("coverage must be between 0.0 and 1.0")
    if not feature_field or not feature_field.strip():
        return BodyKeyRouteDecision(False, coverage, "missing_feature_field")
    if feature_field == "__header__":
        return BodyKeyRouteDecision(False, coverage, "header_feature")
    if coverage < BODY_KEY_COVERAGE_THRESHOLD:
        return BodyKeyRouteDecision(False, coverage, "insufficient_coverage")
    return BodyKeyRouteDecision(True, coverage, "body_key_coverage")
