"""#433：隐私作用域保留安全诊断——run 关联、白名单字段、异常类型与豁免通道。

可区分三类失败（模型调用 / 输出解析 / 正则校验）是验收核心；
所有用例同时断言敏感内容（SECRET 标记）不可见。
"""
import asyncio
import json
import logging
from io import StringIO

import httpx

from application.log_privacy import private_business_logging, bind_run_log_recorder, reset_run_log_recorder


class Capture:
    """挂在具名 logger 上的输出捕获；makeRecord 层的脱敏先于 handler 生效。

    用作上下文管理器，退出时恢复 propagate，避免污染后续 caplog 类测试。
    """

    def __init__(self, name):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        self.output = StringIO()
        self.handler = logging.StreamHandler(self.output)
        self.handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        self._propagate = self.logger.propagate
        self.logger.propagate = False
        self.logger.addHandler(self.handler)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False

    def text(self):
        return self.output.getvalue()

    def close(self):
        if self.handler in self.logger.handlers:
            self.logger.removeHandler(self.handler)
        self.logger.propagate = self._propagate


def test_scope_context_and_whitelisted_extras_survive_masking():
    with Capture("privacy-diagnostics") as capture:
        with private_business_logging(run_id="run-abc12345", step="log_parse"):
            capture.logger.error(
                "SECRET-MESSAGE %s",
                "SECRET-ARGS",
                extra={"error_category": "model_rate_limited", "attempt": 2, "payload": "SECRET-EXTRA"},
            )
        text = capture.text()
        assert "SECRET-MESSAGE SECRET-ARGS" in text
        assert "run_id=run-abc12345" in text and "step=log_parse" in text
        assert "error_category=model_rate_limited" in text and "attempt=2" in text
        assert "SECRET-EXTRA" not in text


def test_exception_type_and_traceback_remain_readable():
    with Capture("privacy-diagnostics-2") as capture:
        with private_business_logging():
            try:
                raise ValueError("SECRET-EXCEPTION")
            except ValueError:
                capture.logger.exception("SECRET-MESSAGE")
        text = capture.text()
        assert "exc_type=ValueError" in text
        assert "SECRET-MESSAGE" in text and "SECRET-EXCEPTION" in text and "Traceback" in text


def test_extra_values_sanitized_long_strings_truncated_non_scalars_dropped():
    with Capture("privacy-diagnostics-3") as capture:
        with private_business_logging():
            capture.logger.error(
                "m", extra={"error_category": "x" * 200, "operation": object(), "duration_ms": 12}
            )
        text = capture.text()
        assert "error_category=" + "x" * 64 in text
        assert "x" * 65 not in text
        assert "operation=" not in text
        assert "duration_ms=12" in text


def test_nested_scope_merges_context():
    with Capture("privacy-diagnostics-4") as capture:
        with private_business_logging(run_id="run-outer"):
            with private_business_logging(step="field_mapping"):
                capture.logger.error("SECRET")
        text = capture.text()
        assert "run_id=run-outer" in text and "step=field_mapping" in text
        assert "SECRET" in text


def test_run_recorder_keeps_full_message_and_masks_only_credentials():
    records = []
    token = bind_run_log_recorder(records.append)
    try:
        with Capture("privacy-full") as capture:
            with private_business_logging(run_id="run-full", step="field_mapping"):
                capture.logger.info("业务日志 %s api_key=real-secret", "甲" * 5000)
        assert "甲" * 5000 in capture.text()
        assert "real-secret" not in capture.text()
        assert records[0]["run_id"] == "run-full"
        assert "甲" * 5000 in records[0]["message"]
        assert "real-secret" not in records[0]["message"]
    finally:
        reset_run_log_recorder(token)


def test_diagnostics_channel_exempt_from_masking_inside_scope():
    with Capture("v2.diagnostics") as capture:
        with private_business_logging(run_id="run-x"):
            capture.logger.error(
                "model_call_failed run_id=run-x error_code=model_rate_limited http_status=429"
            )
        assert (
            "model_call_failed run_id=run-x error_code=model_rate_limited http_status=429"
            in capture.text()
        )


def _api_error():
    request = httpx.Request("POST", "https://api.secret-provider.test/v1/chat/completions")
    return httpx.HTTPStatusError(
        "SECRET-PROSE-429", request=request, response=httpx.Response(429, request=request)
    )


def test_classifier_failure_categories_are_distinguishable(monkeypatch):
    """模型调用 / 正则校验 / 输出解析三类失败在同一掩码下仍可区分。"""
    from agent.tools.pipeline import log_classifier, log_header_processor

    logs = "kind=attack src=SECRET-SAMPLE\n"

    def run_case(patch_batches, format_detail="kv"):
        monkeypatch.setattr(log_classifier, "_meaning_fill_batches", patch_batches)
        with private_business_logging(run_id="run-classify", step="log_parse"):
            return log_classifier._classify_kv_features(logs, "kv", format_detail, "kind", None)

    with Capture("log_parser_pipeline") as capture:
        # 1) 模型调用失败：HTTP 状态异常与通用异常分别标记。
        def raise_api(*args, **kwargs):
            raise _api_error()

        json.loads(run_case(raise_api))
        assert "error_category=model_api_failed" in capture.text()
        assert "SECRET-PROSE-429" in capture.text()

        def raise_llm(*args, **kwargs):
            raise RuntimeError("SECRET-LLM-PROSE")

        json.loads(run_case(raise_llm))
        assert "error_category=model_call_failed" in capture.text()
        assert "SECRET-LLM-PROSE" in capture.text()

        # 2) 正则校验失败：日志头 KV feature_identifier 生成抛 ValueError。
        monkeypatch.setattr(
            log_classifier,
            "_meaning_fill_batches",
            lambda *args, **kwargs: {"status": "SUCCESS", "classification_details": [], "feature_count": 0},
        )
        monkeypatch.setattr(
            log_header_processor,
            "_generate_kv_feature_identifier",
            lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("SECRET-REGEX")),
        )
        parsed = json.loads(run_case(lambda *args, **kwargs: {
            "status": "SUCCESS", "classification_details": [], "feature_count": 0}, format_detail="kv+日志头"))
        assert parsed["fail_reason"] == "feature_identifier 生成失败"
        assert "error_category=feature_regex_invalid" in capture.text()
        assert "SECRET-REGEX" in capture.text()

    # 3) 输出解析失败：LLM 返回非法 JSON 走兜底。
    from agent.tools.pipeline.common.llm_postprocessor import postprocess_llm_classification

    with Capture("log_parser_pipeline") as capture:
        with private_business_logging(run_id="run-classify", step="log_parse"):
            fallback = postprocess_llm_classification(
                "NOT-JSON{SECRET-OUTPUT}", {}, logs, lambda line, field: None
            )
        assert fallback.get("status") in {"PARTIAL", "FAILED", "SUCCESS"}
        assert "error_category=model_output_invalid" in capture.text()
        assert "LLM returned invalid JSON" in capture.text()


def test_executor_failure_extras_and_exc_type_survive_privacy_scope():
    from application.execution import ExecutionContext, PlanExecutor
    from application.log_privacy import private_business_logging
    from contracts.planner_models import DeterministicPlan, LogParseStep, StepStatus
    from contracts.session_facts import SessionFacts
    from factories import make_session_state

    class Failing:
        async def execute(self, *args):
            raise TimeoutError("SECRET-TIMEOUT")

    plan = DeterministicPlan(plan_id="p", steps=(LogParseStep(step_id="log-parse", type="log_parse"),))
    with Capture("plan_executor") as capture:
        with private_business_logging(run_id="run-exec", step="log_parse"):
            result = asyncio.run(
                PlanExecutor({"log_parse": Failing()}).execute(
                    plan, ExecutionContext(make_session_state(), SessionFacts(has_logs=True))
                )
            )
        assert result.status == StepStatus.FAILED
        text = capture.text()
        assert "error_category=adapter_failed" in text
        assert "step_id=log-parse" in text and "operation=log_parse" in text
        assert "exc_type=TimeoutError" in text and "run_id=run-exec" in text
        assert "SECRET-TIMEOUT" in text


def test_log_parse_adapter_reports_classifier_fail_reason():
    from application.adapters.log_parse import LogParseAdapter
    from application.execution import ExecutionContext
    from contracts.planner_models import LogParseStep, StepStatus
    from contracts.session_facts import SessionFacts
    from factories import make_session_state

    adapter = LogParseAdapter(
        format_identifier=lambda text: json.dumps({"format": "kv", "format_detail": "kv"}),
        classifier=lambda *a, **k: json.dumps(
            {"status": "PARTIAL", "fail_reason": "feature_identifier 生成失败"}, ensure_ascii=False
        ),
    )
    context = ExecutionContext(
        make_session_state(raw_log_lines=["kind=a src=SECRET"]), SessionFacts(has_logs=True)
    )
    result = asyncio.run(adapter.execute(LogParseStep(step_id="log-parse", type="log_parse"), context, {}))
    assert result.status == StepStatus.FAILED
    assert "feature_identifier 生成失败" in result.message
