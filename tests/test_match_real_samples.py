"""
match_real_samples 测试 — real_samples 不应被 {…} fallback 截断。

回归背景（2026-07-28 用户反馈，日志解析结果.json）：
  纯 KV 日志（header_end_marker=""、feature_identifier=""）的日志行内含
  JSON 子串（如 dipGeo={"10.163.2.52":{…}}），match_real_samples 的分支C
  fallback `find("{")…rfind("}")` 误将这些子串当作 body 提取，导致：
    - sample 是完整行（uuid=… 开头）✅
    - real_samples 被截断成 {"10.163.2.52":…} 的尾部片段 ❌

修复：纯 KV（无 header_end_marker、无 feature_identifier）应原样返回完整行。
"""
import importlib
import sys
import types
from pathlib import Path

import pytest

# 隔离加载，绕开 agent.tools.__init__ 循环导入
_ROOT = str(Path(__file__).resolve().parent.parent)


def _load_postprocessor_isolated():
    """隔离加载 llm_postprocessor，绕开 agent.tools.__init__ 循环导入。

    注入无副作用的假 get_logger，避免真实 logger 的 FileHandler 打开日志文件
    （卸载后文件句柄残留导致 Windows PermissionError: WinError 32）。
    """
    import logging

    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    if "agent" not in sys.modules:
        try:
            importlib.import_module("agent")
        except Exception:
            m = types.ModuleType("agent")
            m.__path__ = [str(Path(_ROOT) / "agent")]
            sys.modules["agent"] = m

    existing_tools = sys.modules.get("agent.tools")
    if existing_tools is not None and hasattr(existing_tools, "read_enum_mappings_from_excel"):
        from agent.tools.pipeline.common.llm_postprocessor import match_real_samples
        return match_real_samples

    _snapshot = set(sys.modules.keys())
    fake_shared = types.ModuleType("agent.shared")
    fake_logger_mod = types.ModuleType("agent.shared.logger")
    fake_logger_mod.get_logger = lambda name="agent": logging.getLogger(name)
    sys.modules["agent.shared"] = fake_shared
    sys.modules["agent.shared.logger"] = fake_logger_mod

    tools_mod = types.ModuleType("agent.tools")
    tools_mod.__path__ = [str(Path(_ROOT) / "agent" / "tools")]
    tools_mod.__package__ = "agent.tools"
    sys.modules["agent.tools"] = tools_mod
    try:
        from agent.tools.pipeline.common.llm_postprocessor import match_real_samples
        return match_real_samples
    finally:
        for key in list(sys.modules.keys()):
            if key not in _snapshot:
                del sys.modules[key]


match_real_samples = _load_postprocessor_isolated()


# 真实 KV 日志行（含 {…} 子串，如 dipGeo/sipGeo）
KV_LINE = (
    "uuid=3cc90c2c|latestTimestamp=2026-07-03 07:27:29|name=远控木马活动事件"
    "|severity=危急|srcIp=[10.16.2.12]"
    '|dipGeo={"10.163.2.52":{"continent_name":"保留IP","latitude":"0.0"}}'
    "|dport=[53]|authType=|eventType="
    '|sipGeo={"10.16.2.12":{"continent_name":"保留IP","latitude":"0.0"}}'
)

# 纯 JSON 日志行（无 syslog 头，应走 {...} 提取）
JSON_LINE = (
    '{"log_type":"nginx","src_ip":"10.1.2.3","action":"block","level":"high"}'
)

# syslog 头 + JSON body（header_end_marker 场景）
SYSLOG_JSON_LINE = (
    "Jul 28 10:00:00 host nginx: "
    '{"log_type":"nginx","src_ip":"10.1.2.3","action":"block"}'
)


def _dummy_extractor(line, field):
    """简单 KV 提取器，用于 match_real_samples 的 extractor_func 参数。"""
    if "name=远控木马活动事件" in line:
        return "远控木马活动事件"
    if '"log_type":"nginx"' in line:
        return "nginx"
    return None


class TestRealSamplesPureKV:
    """纯 KV 日志的 real_samples 应是完整行，不被 {…} 子串截断。"""

    def test_pure_kv_real_samples_is_full_line(self):
        """纯 KV（无 header/feature_identifier）real_samples = 完整行，以 uuid= 开头。"""
        parsed = {
            "feature_field": "name",
            "feature_identifier": "",   # 纯 KV 无此字段
            "feature_body_group": 0,
            "classification_details": [
                {"logtype": "远控木马活动事件"}
            ],
        }
        result = match_real_samples(
            parsed, KV_LINE, _dummy_extractor,
            feature_field="name",
            header_end_marker="",  # 纯 KV 无 header
        )
        detail = result["classification_details"][0]
        assert detail["real_samples"].startswith("uuid="), (
            f"纯 KV 的 real_samples 应以 uuid= 开头（完整行），"
            f"实际开头: {detail['real_samples'][:50]!r}"
        )
        assert detail["real_samples"] == KV_LINE, (
            "纯 KV 的 real_samples 应等于完整日志行"
        )

    def test_pure_kv_real_samples_not_truncated_at_brace(self):
        """regression: 确认不是从 dipGeo={ 处截断。"""
        parsed = {
            "feature_field": "name",
            "feature_identifier": "",
            "feature_body_group": 0,
            "classification_details": [{"logtype": "远控木马活动事件"}],
        }
        result = match_real_samples(parsed, KV_LINE, _dummy_extractor,
                                    feature_field="name", header_end_marker="")
        rs = result["classification_details"][0]["real_samples"]
        assert not rs.startswith("{"), (
            f"BUG 复现：real_samples 被 {{...}} 截断，开头: {rs[:40]!r}"
        )


class TestScanCollectsOnlyWantedLogtypes:
    """#281：扫描只收集本批 logtype 的命中行，不因干扰值凑数提前退出。

    分批分类（#190）后 details 仅含本批值；旧逻辑按"任意不同值"计数提前
    退出，扫描收集满 len(details) 个干扰值即 break，首次出现较晚的本批
    类型永远扫不到（线上 36/55 类型 sample 为空）。
    """

    def test_late_first_occurrence_types_still_match(self):
        """目标类型首次出现排在干扰值之后时，仍能扫到并取得真实样例。"""
        wanted_lines = [
            "seq=1|name=高频晚现类型|sev=high",
            "seq=2|name=低频晚现类型|sev=low",
        ]
        logs = "\n".join(
            [
                "seq=9|name=干扰甲|sev=info",
                "seq=8|name=干扰乙|sev=info",
                "seq=7|name=干扰丙|sev=info",
                *wanted_lines,
            ]
        )

        def extractor(line, field):
            for part in line.split("|"):
                if part.startswith("name="):
                    return part[len("name="):]
            return None

        parsed = {
            "feature_field": "name",
            "feature_identifier": "",
            "feature_body_group": 0,
            "classification_details": [
                {"logtype": "高频晚现类型"},
                {"logtype": "低频晚现类型"},
            ],
        }
        result = match_real_samples(
            parsed, logs, extractor, feature_field="name", header_end_marker=""
        )
        details = result["classification_details"]
        assert details[0]["sample"] == wanted_lines[0], (
            "首现晚于干扰值的类型应扫到首个命中行（旧逻辑在收集满 "
            "len(details) 个干扰值后提前退出）"
        )
        assert details[1]["sample"] == wanted_lines[1]


class TestRealSamplesKVHeaderFailure:
    """已声明 KV body 正则时，意外失配必须失败关闭。"""

    def test_feature_identifier_miss_preserves_sample_but_rejects_headed_body(self):
        line = "<6> Sep 04 17:00:08 host TYPE/6/EVENT:body=ok type=TYPE"
        parsed = {
            "status": "SUCCESS",
            "feature_field": "__header__",
            "feature_identifier": r"TYPE/6/EVENT:\s+(.*)",
            "feature_body_group": 1,
            "classification_details": [{"logtype": "TYPE"}],
        }

        result = match_real_samples(
            parsed,
            line,
            lambda value, _: "TYPE" if "type=TYPE" in value else None,
            feature_field="__header__",
            header_end_marker=": ",
            sample_format="kv",
        )

        detail = result["classification_details"][0]
        assert detail["sample"] == line
        assert detail["real_samples"] == "[匹配失败]"
        assert result["status"] == "PARTIAL"
        assert "body" in result["fail_reason"]


class TestRealSamplesJSON:
    """JSON 日志的 real_samples 应正确提取 {...} body（保留原有行为）。"""

    def test_pure_json_line_keeps_body(self):
        """纯 JSON 行（整体就是 {...}）real_samples 保持完整。"""
        parsed = {
            "feature_field": "log_type",
            "feature_identifier": "",
            "feature_body_group": 0,
            "classification_details": [{"logtype": "nginx"}],
        }
        result = match_real_samples(parsed, JSON_LINE, _dummy_extractor,
                                    feature_field="log_type", header_end_marker="")
        rs = result["classification_details"][0]["real_samples"]
        # 纯 JSON 行，{...} 就是完整行，不应丢失内容
        assert rs.startswith("{"), "JSON body 应以 { 开头"
        assert '"log_type":"nginx"' in rs

    def test_syslog_json_strips_header(self):
        """syslog 头 + JSON：header_end_marker 场景应剥离头部，保留 JSON body。"""
        parsed = {
            "feature_field": "log_type",
            "feature_identifier": "",
            "feature_body_group": 0,
            "classification_details": [{"logtype": "nginx"}],
        }
        result = match_real_samples(parsed, SYSLOG_JSON_LINE, _dummy_extractor,
                                    feature_field="log_type",
                                    header_end_marker="nginx: ")
        rs = result["classification_details"][0]["real_samples"]
        assert '"log_type":"nginx"' in rs, "JSON body 应被保留"
        assert "Jul 28" not in rs, "syslog 头应被剥离"

    def test_syslog_json_without_marker_uses_explicit_json_format(self):
        """body-key 快路清空 marker 后，显式 JSON 语义仍应提取 JSON body。"""
        parsed = {
            "feature_field": "log_type",
            "feature_identifier": "",
            "feature_body_group": 0,
            "classification_details": [{"logtype": "nginx"}],
        }

        result = match_real_samples(
            parsed,
            SYSLOG_JSON_LINE,
            _dummy_extractor,
            feature_field="log_type",
            header_end_marker="",
            sample_format="json",
        )

        detail = result["classification_details"][0]
        assert detail["sample"] == SYSLOG_JSON_LINE
        assert detail["real_samples"] == (
            '{"log_type":"nginx","src_ip":"10.1.2.3","action":"block"}'
        )
