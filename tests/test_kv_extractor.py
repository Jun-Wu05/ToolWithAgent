"""
KvExtractor 正则测试 — 竖线分隔 KV 日志的字段提取。

回归背景（2026-07-27 日志 app_20260727_100448.log + 用户提供的日志解析结果.json）：
  奇安信NGSOC 日志格式为 `key=val|key=val|...`（竖线分隔），
  KvExtractor 动态正则的键名捕获组用 (\\S+)（贪婪，匹配所有非空白含 |），
  导致键名跨越 | 错位，name 字段提取不到，最终：
    - aggregate matched=123/2000（6% 覆盖率）
    - real_samples 为日志行错位截断的尾部片段
    - 识别出的日志类型是错位的偶然命中

修复：键名捕获组排除 field_delimit 字符，使每个字段独立对齐。
"""
import importlib
import sys
import types
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent)


def _load_kv_extractor_isolated():
    """隔离加载 KvExtractor，绕开 agent.tools.__init__ 的循环导入。

    关键：注入无副作用的假 get_logger，避免真实 logger 创建 FileHandler
    打开日志文件（卸载模块后文件句柄残留，导致 Windows PermissionError: WinError 32）。
    加载后精确清理本次引入的 sys.modules 键，不污染其它测试。
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
    if existing_tools is not None and hasattr(existing_tools, "field_mapping_tool"):
        from agent.tools.pipeline.extractors.kv_extractor import KvExtractor
        return KvExtractor

    _snapshot = set(sys.modules.keys())
    # 注入假 logger，避免真实 FileHandler 打开日志文件
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
        from agent.tools.pipeline.extractors.kv_extractor import KvExtractor
        return KvExtractor
    finally:
        for key in list(sys.modules.keys()):
            if key not in _snapshot:
                del sys.modules[key]


KvExtractor = _load_kv_extractor_isolated()


# 真实日志样本（取自 KV_head_奇安信NGSOC待测试0703.xlsx，竖线分隔）
REAL_LINE = (
    "uuid=ecec2264-e5c2-46a6-aa6f-03696b12e4e3|"
    "latestTimestamp=2026-07-03 07:41:48|"
    "name=Nacos-Sync 后台未授权访问漏洞|"
    "severity=中危|"
    "srcIp=[10.209.1.101]|"
    "dstIp=[10.209.0.39]|"
    "authType=|"
    "dport=[8848]"
)


class TestKvExtractorPipeDelimited:
    """竖线 | 分隔的 KV 日志（本次 bug 的场景）。"""

    def test_extract_name_from_pipe_delimited(self):
        """竖线分隔日志能正确提取 name 字段值（核心回归点）。"""
        extractor = KvExtractor(field_delimit="|", kv_delimit="=")
        val = extractor.extract_value(REAL_LINE, "name")
        assert val == "Nacos-Sync 后台未授权访问漏洞", (
            f"应提取到 'Nacos-Sync 后台未授权访问漏洞'，实际：{val!r}"
        )

    def test_extract_uuid_not_concatenated(self):
        """uuid 字段值不应跨越 | 串入下一个字段（键名错位的典型症状）。"""
        extractor = KvExtractor(field_delimit="|", kv_delimit="=")
        val = extractor.extract_value(REAL_LINE, "uuid")
        assert val == "ecec2264-e5c2-46a6-aa6f-03696b12e4e3", (
            f"uuid 值被 | 串连错位，实际：{val!r}"
        )

    def test_extract_value_with_brackets(self):
        """带方括号的值（如 [10.209.1.101]）应完整提取。"""
        extractor = KvExtractor(field_delimit="|", kv_delimit="=")
        assert extractor.extract_value(REAL_LINE, "srcIp") == "[10.209.1.101]"
        assert extractor.extract_value(REAL_LINE, "dport") == "[8848]"

    def test_extract_value_with_spaces(self):
        """值内含空格（如时间戳、中文事件名）应完整提取，不被截断。"""
        extractor = KvExtractor(field_delimit="|", kv_delimit="=")
        assert extractor.extract_value(REAL_LINE, "latestTimestamp") == "2026-07-03 07:41:48"


class TestKvExtractorAllDelimiters:
    """修复正则必须对所有分隔符组合都适配（不能只修 |）。"""

    def test_space_equals(self):
        """经典 syslog：空格分隔 + 等号。"""
        extractor = KvExtractor(field_delimit=" ", kv_delimit="=")
        line = "src_ip=10.1.2.3 name=login_failed level=high action=block"
        assert extractor.extract_value(line, "name") == "login_failed"
        assert extractor.extract_value(line, "src_ip") == "10.1.2.3"

    def test_space_colon(self):
        """冒号分隔 + 空格字段分隔。"""
        extractor = KvExtractor(field_delimit=" ", kv_delimit=":")
        line = "src_ip:10.1.2.3 name:login_failed level:high action:block"
        assert extractor.extract_value(line, "name") == "login_failed"

    def test_double_pipe_colon(self):
        """双竖线 || + 冒号（文档里的示例格式）。"""
        extractor = KvExtractor(field_delimit="||", kv_delimit=":")
        line = "src_ip:10.1.2.3||name:waf_log||level:high||action:block"
        assert extractor.extract_value(line, "name") == "waf_log"


class TestKvExtractorChineseKeys:
    """键名含中文时也应正确提取（\\S 替换为字符类后仍需支持非 ASCII）。"""

    def test_chinese_key_extraction(self):
        """中文键名（如「事件名称=告警」）能正确提取。"""
        extractor = KvExtractor(field_delimit="|", kv_delimit="=")
        line = "事件名称=测试告警|severity=高|action=block"
        assert extractor.extract_value(line, "事件名称") == "测试告警"


class TestKvExtractorAggregateCoverage:
    """聚合覆盖率回归：竖线分隔日志的 matched 应接近 100%，而非 6%。"""

    def test_pipe_delimited_high_coverage(self):
        """多条竖线分隔日志，name 字段覆盖率应 ≥ 90%（修复前仅 6%）。"""
        extractor = KvExtractor(field_delimit="|", kv_delimit="=")
        lines = [
            "uuid=a1|name=远控木马活动事件|severity=危急|srcIp=[1.1.1.1]",
            "uuid=a2|name=银狐威胁体组织远控木马活动事件|severity=危急|srcIp=[2.2.2.2]",
            "uuid=a3|name=黑猫组织远控木马活动事件|severity=高危|srcIp=[3.3.3.3]",
            "uuid=a4|name=Nacos-Sync 后台未授权访问漏洞|severity=中危|srcIp=[4.4.4.4]",
            "uuid=a5|name=流量-特定端口扫描|severity=低危|srcIp=[5.5.5.5]",
        ]
        logs_str = "\n".join(lines)
        agg = extractor.extract_and_aggregate(logs_str, "name")
        # 修复前：只有 1 行能匹配（错位），覆盖率 20%
        # 修复后：全部 5 行匹配，覆盖率 100%
        assert agg["matched_lines"] == 5, (
            f"覆盖率应 100%，实际 matched={agg['matched_lines']}/{agg['total_lines']}"
        )
        assert agg["value_count"] == 5
