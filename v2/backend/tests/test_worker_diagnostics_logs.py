"""#433：Worker 失败路径日志保留 run 关联与稳定类别，敏感内容不可见。"""
import logging
from io import StringIO

from application.log_privacy import private_business_logging
from test_log_parse_slice import setup, upload


class _Capture:
    """挂 handler 捕获输出并暂停 propagate；用作上下文管理器，退出时恢复。"""

    def __init__(self, name):
        self.logger = logging.getLogger(name)
        self.output = StringIO()
        self.handler = logging.StreamHandler(self.output)
        self.handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        self._propagate = self.logger.propagate
        self.logger.propagate = False
        self.logger.addHandler(self.handler)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        if self.handler in self.logger.handlers:
            self.logger.removeHandler(self.handler)
        self.logger.propagate = self._propagate
        return False

    def text(self):
        return self.output.getvalue()


class LoggingFailingParse:
    """业务替身：在隐私作用域内打一条带类别与敏感内容的日志后失败。"""

    async def parse(self, path, snapshot):
        logging.getLogger("log_parser_pipeline").error(
            "SECRET-PIPELINE-DETAIL %s", "SECRET-ARG", extra={"error_category": "model_rate_limited"}
        )
        return {"error": "log_parse_failed"}


def test_worker_masks_content_but_keeps_run_context_and_category(tmp_path):
    client, store, conversation, worker = setup(tmp_path)
    worker.business_application = LoggingFailingParse()
    file_id = upload(client, conversation, worker)
    with _Capture("log_parser_pipeline") as capture:
        queued = client.post(
            f"/api/v2/conversations/{conversation}/log-parse", json={"file_id": file_id}
        )
        run_id = queued.json()["run"]["id"]
        assert worker.once()
        text = capture.text()
        assert f"run_id={run_id}" in text and "step=log_parse" in text
        assert "error_category=model_rate_limited" in text
        assert "SECRET" not in text
    assert client.get(f"/api/v2/runs/{run_id}").json()["status"] == "failed"


def test_model_call_failure_uses_exempt_diagnostics_channel(tmp_path):
    client, store, conversation, worker = setup(tmp_path)
    claim = {"id": "run-model-call", "task_type": "field_mapping"}
    event = {
        "status": "failed",
        "error_code": "model_rate_limited",
        "http_status": 429,
        "operation": "field_mapping",
        "attempt": 2,
        "duration_ms": 1523,
        "provider": "deepseek",
        "model": "deepseek-chat",
    }
    with _Capture("v2.diagnostics") as capture:
        with private_business_logging(run_id="run-model-call", step="field_mapping"):
            worker._log_model_call_failure(claim, event)
            worker._log_model_call_failure(claim, {**event, "status": "succeeded"})
        text = capture.text()
        assert "model_call_failed run_id=run-model-call task=field_mapping" in text
        assert "error_code=model_rate_limited http_status=429" in text
        assert "operation=field_mapping attempt=2" in text
        assert text.count("model_call_failed") == 1
