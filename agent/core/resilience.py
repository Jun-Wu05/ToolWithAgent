"""
容错与熔断机制 - Circuit Breaker / Fallback / Retry

为 LLM API 调用提供生产级容错能力：
- CircuitBreaker: 连续失败 N 次后熔断，冷却后可半开探测
- ModelFallback: 主模型失败时自动切换到备用模型
- RetryPolicy: 指数退避重试策略

用法:
    breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
    try:
        result = breaker.call(team.run, prompt)
    except CircuitBreakerOpenError:
        # 熔断中，使用缓存结果或返回错误
        pass
"""

import time
import threading
import functools
from typing import Callable, Optional, Any, TypeVar
from enum import Enum, auto
import logging

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = auto()       # 正常（闭合电路）
    OPEN = auto()         # 熔断（开路，拒绝请求）
    HALF_OPEN = auto()    # 半开（探测恢复）


class CircuitBreakerOpenError(Exception):
    """熔断器开启时拒绝请求的异常"""
    pass


class CircuitBreaker:
    """
    熔断器 - 防止级联失败

    状态机:
        CLOSED → (连续失败 >= threshold) → OPEN
        OPEN → (等待 recovery_timeout) → HALF_OPEN
        HALF_OPEN → (成功) → CLOSED
        HALF_OPEN → (失败) → OPEN

    Args:
        failure_threshold: 连续失败次数阈值，达到后熔断
        recovery_timeout: 熔断恢复等待时间（秒）
        half_open_max_calls: 半开状态下允许的最大探测请求数
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 1,
        name: str = "default",
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.name = name

        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._last_failure_time: float = 0.0
        self._half_open_calls: int = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        """当前熔断器状态"""
        with self._lock:
            # 检查是否可以从 OPEN 转换到 HALF_OPEN
            if (self._state == CircuitState.OPEN
                    and time.time() - self._last_failure_time >= self.recovery_timeout):
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info(
                    f"[CircuitBreaker:{self.name}] OPEN → HALF_OPEN "
                    f"(恢复时间 {self.recovery_timeout}s 已到，开始探测)"
                )
            return self._state

    def _on_success(self) -> None:
        """请求成功时回调"""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                logger.info(f"[CircuitBreaker:{self.name}] HALF_OPEN → CLOSED (探测成功)")
            else:
                self._failure_count = 0

    def _on_failure(self) -> None:
        """请求失败时回调"""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if (self._state == CircuitState.HALF_OPEN
                    or self._failure_count >= self.failure_threshold):
                self._state = CircuitState.OPEN
                logger.warning(
                    f"[CircuitBreaker:{self.name}] → OPEN "
                    f"(连续失败 {self._failure_count} 次，熔断 {self.recovery_timeout}s)"
                )

    def _check_allow(self) -> bool:
        """检查是否允许请求通过"""
        current_state = self.state
        if current_state == CircuitState.CLOSED:
            return True
        if current_state == CircuitState.HALF_OPEN:
            with self._lock:
                if self._half_open_calls < self.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
            return False
        # OPEN
        return False

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """
        受熔断器保护的函数调用

        Args:
            func: 需要保护的函数
            *args, **kwargs: 函数参数

        Returns:
            函数返回值

        Raises:
            CircuitBreakerOpenError: 熔断器开启时
            Exception: 原始异常透传
        """
        if not self._check_allow():
            raise CircuitBreakerOpenError(
                f"熔断器 [{self.name}] 已开启，"
                f"请等待 {self.recovery_timeout}s 后重试"
            )

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise


class ModelFallback:
    """
    模型降级策略

    主模型失败时自动切换到备用模型。
    可选：熔断器保护（主模型熔断后直接跳过）。

    Args:
        primary_model_id: 主模型 ID
        fallback_model_id: 备用模型 ID
        circuit_breaker: 熔断器实例（可选）
    """

    def __init__(
        self,
        primary_model_id: str,
        fallback_model_id: str,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ) -> None:
        self.primary_model_id = primary_model_id
        self.fallback_model_id = fallback_model_id
        self.circuit_breaker = circuit_breaker
        self.fallback_used_count: int = 0

        self._current_model: str = primary_model_id

    @property
    def current_model(self) -> str:
        """当前活跃模型"""
        return self._current_model

    def should_skip_primary(self) -> bool:
        """是否应跳过主模型（熔断开启时）"""
        if self.circuit_breaker and self.circuit_breaker.state == CircuitState.OPEN:
            return True
        return False

    def execute(
        self,
        primary_func: Callable[..., T],
        fallback_func: Callable[..., T],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """
        执行带降级的调用

        1. 如果主模型熔断中，直接使用备用模型
        2. 尝试主模型
        3. 主模型失败则使用备用模型
        4. 备用模型也失败则抛出异常

        Args:
            primary_func: 主模型调用函数
            fallback_func: 备用模型调用函数
            *args, **kwargs: 函数参数

        Returns:
            函数返回值

        Raises:
            Exception: 两个模型都失败时抛出
        """
        # 如果熔断中，直接降级
        if self.should_skip_primary():
            logger.warning(
                f"[ModelFallback] 主模型 {self.primary_model_id} 熔断中，"
                f"直接使用备用模型 {self.fallback_model_id}"
            )
            self._current_model = self.fallback_model_id
            result = fallback_func(*args, **kwargs)
            self.fallback_used_count += 1
            return result

        # 尝试主模型
        try:
            if self.circuit_breaker:
                result = self.circuit_breaker.call(primary_func, *args, **kwargs)
            else:
                result = primary_func(*args, **kwargs)
            self._current_model = self.primary_model_id
            return result
        except CircuitBreakerOpenError:
            logger.warning(
                f"[ModelFallback] 主模型 {self.primary_model_id} 熔断触发，"
                f"切换到备用模型 {self.fallback_model_id}"
            )
        except Exception as e:
            logger.warning(
                f"[ModelFallback] 主模型 {self.primary_model_id} 失败: {e}，"
                f"切换到备用模型 {self.fallback_model_id}"
            )

        # 使用备用模型
        self._current_model = self.fallback_model_id
        result = fallback_func(*args, **kwargs)
        self.fallback_used_count += 1
        return result


class RetryPolicy:
    """
    指数退避重试策略

    Args:
        max_retries: 最大重试次数
        base_delay: 基础延迟（秒）
        max_delay: 最大延迟上限（秒）
        backoff_factor: 退避因子（默认 2，指数增长）
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        backoff_factor: float = 2.0,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor

    def get_delay(self, attempt: int) -> float:
        """计算第 N 次重试的延迟"""
        delay = self.base_delay * (self.backoff_factor ** (attempt - 1))
        return min(delay, self.max_delay)

    def should_retry(self, attempt: int, exception: Exception) -> bool:
        """
        判断是否应重试

        Args:
            attempt: 当前尝试次数（从 1 开始）
            exception: 发生的异常

        Returns:
            是否应重试
        """
        if attempt >= self.max_retries:
            return False

        # 可重试的异常类型
        retriable_types = (
            TimeoutError,
            ConnectionError,
        )

        if isinstance(exception, retriable_types):
            return True

        # 熔断器异常不应重试（由其自身处理）
        if isinstance(exception, CircuitBreakerOpenError):
            return False

        # 默认：其他异常也尝试重试
        return True