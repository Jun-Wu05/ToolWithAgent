"""Issue #169：冻结历史 resilience 模块的确定性公开行为。"""

from __future__ import annotations

import pytest

import agent.core.resilience as resilience

CircuitBreaker = resilience.CircuitBreaker
CircuitBreakerOpenError = resilience.CircuitBreakerOpenError
CircuitState = resilience.CircuitState
ModelFallback = resilience.ModelFallback
RetryPolicy = resilience.RetryPolicy


def test_circuit_breaker达到阈值后打开并拒绝调用() -> None:
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=30, name="primary")
    calls = []

    def fail() -> None:
        calls.append("called")
        raise RuntimeError("model failed")

    with pytest.raises(RuntimeError, match="model failed"):
        breaker.call(fail)
    assert breaker.state == CircuitState.CLOSED

    with pytest.raises(RuntimeError, match="model failed"):
        breaker.call(fail)
    assert breaker.state == CircuitState.OPEN

    with pytest.raises(CircuitBreakerOpenError, match=r"熔断器 \[primary\] 已开启"):
        breaker.call(fail)
    assert calls == ["called", "called"]


def test_circuit_breaker用可控时钟半开并按探测结果转换(monkeypatch) -> None:
    now = [100.0]
    monkeypatch.setattr(resilience.time, "time", lambda: now[0])
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=5)

    with pytest.raises(ValueError):
        breaker.call(lambda: (_ for _ in ()).throw(ValueError("failed")))
    now[0] = 104.9
    assert breaker.state == CircuitState.OPEN
    now[0] = 105.0
    assert breaker.state == CircuitState.HALF_OPEN
    assert breaker.call(lambda: "recovered") == "recovered"
    assert breaker.state == CircuitState.CLOSED

    with pytest.raises(ValueError):
        breaker.call(lambda: (_ for _ in ()).throw(ValueError("failed again")))
    now[0] = 110.0
    assert breaker.state == CircuitState.HALF_OPEN
    with pytest.raises(ValueError):
        breaker.call(lambda: (_ for _ in ()).throw(ValueError("probe failed")))
    assert breaker.state == CircuitState.OPEN


def test_model_fallback保持主备选择计数与双失败透传() -> None:
    fallback = ModelFallback("primary", "backup")

    assert fallback.execute(lambda value: value + 1, lambda value: -1, 2) == 3
    assert fallback.current_model == "primary"
    assert fallback.fallback_used_count == 0

    def primary_failed() -> None:
        raise RuntimeError("primary failed")

    assert fallback.execute(primary_failed, lambda: "backup result") == "backup result"
    assert fallback.current_model == "backup"
    assert fallback.fallback_used_count == 1

    def backup_failed() -> None:
        raise LookupError("backup failed")

    with pytest.raises(LookupError, match="backup failed"):
        fallback.execute(primary_failed, backup_failed)
    assert fallback.current_model == "backup"
    assert fallback.fallback_used_count == 1


def test_model_fallback在熔断开启时跳过主模型() -> None:
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=30)
    with pytest.raises(RuntimeError):
        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("failed")))

    primary_calls = []
    fallback = ModelFallback("primary", "backup", circuit_breaker=breaker)
    result = fallback.execute(
        lambda: primary_calls.append("called"),
        lambda: "backup result",
    )

    assert result == "backup result"
    assert primary_calls == []
    assert fallback.fallback_used_count == 1


def test_retry_policy保持退避上限与异常分类() -> None:
    policy = RetryPolicy(max_retries=3, base_delay=0.5, max_delay=2, backoff_factor=3)

    assert [policy.get_delay(attempt) for attempt in range(1, 6)] == [0.5, 1.5, 2, 2, 2]
    assert policy.should_retry(1, TimeoutError()) is True
    assert policy.should_retry(1, ConnectionError()) is True
    assert policy.should_retry(1, ValueError()) is True
    assert policy.should_retry(1, CircuitBreakerOpenError()) is False
    assert policy.should_retry(3, TimeoutError()) is False
