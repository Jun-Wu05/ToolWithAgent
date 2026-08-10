"""
KV 日志头剥离回归测试 — header_end_marker == 字段分隔符场景。

回归背景（issue #14，app_20260807_091056.log）：
  skyeye_ioc 日志格式 `<30>skyeye_ioc\tkey=val\tkey=val\t...`，
  LLM 返回 header_end_marker='\t'，但 \t 也是 KV 字段分隔符。
  _classify_kv_features 原用 rpartition('\t') 从右切，body 只剩每行
  最后一个字段（attck_tech="T1041"），type= 等字段丢失，matched=0。

  修复：改用 strip_header_to_body（从左 split(marker, 1)），与全仓
  8 处剥头一致。第一个 marker 之后全算 body。
"""
# conftest 已注入根路径。直接 import 依赖全量环境（agent.tools 链已由
# 其它测试初始化），与 test_threat_context / test_user_message_routing 同模式。
from agent.tools.pipeline.common.json_utils import strip_header_to_body

# 真实 skyeye_ioc 日志行（取自 SearchResult xlsx，tab 分隔 KV）
SKYEYE_LINE = (
    "<30>skyeye_ioc\taccess_time=\"1785294505279\"\ttid=\"2\"\ttype=\"远控木马\""
    "\trule_desc=\"AsyncRAT\"\toffence_type=\"sip\"\tattck_tech=\"T1041\""
)
TAB = "\t"


class TestKVHeaderStripMarkerEqualsDelimiter:
    """header_end_marker == 字段分隔符时，body 须保留完整 KV 行。"""

    def test_skyeye_body_retains_type_field(self):
        """skyeye_ioc 日志剥离头后，body 须含 type= 字段（修复前只剩 attck_tech）。"""
        body = strip_header_to_body(SKYEYE_LINE, TAB, is_json=False)
        assert "type=" in body, f"body 丢失 type 字段（rpartition bug），实际：{body!r}"
        assert "远控木马" in body, f"body 丢失 type 值，实际：{body!r}"

    def test_skyeye_body_retains_all_fields_not_just_last(self):
        """body 须保留多个字段，而非只剩最后一个（attck_tech）。"""
        body = strip_header_to_body(SKYEYE_LINE, TAB, is_json=False)
        # 修复前 rpartition：body='attck_tech="T1041"'（1 个字段）
        # 修复后 split(1)：body 含 access_time/type/rule_desc/.../attck_tech
        field_count = body.count(TAB) + 1
        assert field_count > 3, (
            f"body 字段数过少（{field_count}），疑似只保留尾部字段，实际：{body!r}"
        )

    def test_skyeye_header_stripped(self):
        """日志头 <30>skyeye_ioc 须被剥离，不出现在 body 中。"""
        body = strip_header_to_body(SKYEYE_LINE, TAB, is_json=False)
        assert not body.startswith("<30>"), f"body 仍含日志头，实际：{body!r}"
        assert not body.startswith("skyeye_ioc"), f"body 仍含日志头标识，实际：{body!r}"


class TestKVHeaderStripUniqueMarker:
    """marker 唯一出现的常规场景行为不变（零回归验证）。"""

    def test_unique_marker_strips_header_correctly(self):
        """marker（如 ': '）在行内唯一出现时，剥头后保留完整 body。"""
        line = "Jan 01 12:00:00 host nginx: key=val key2=val2"
        body = strip_header_to_body(line, "nginx: ", is_json=False)
        assert body == "key=val key2=val2", f"唯一 marker 剥头异常，实际：{body!r}"

    def test_empty_marker_returns_original_line(self):
        """marker 为空时返回原始行（不剥头）。"""
        line = "key=val key2=val2"
        body = strip_header_to_body(line, "", is_json=False)
        assert body == line, f"空 marker 应返回原行，实际：{body!r}"

    def test_marker_not_found_returns_original_line(self):
        """marker 未找到时返回原始行（兼容性）。"""
        line = "key=val key2=val2"
        body = strip_header_to_body(line, "|", is_json=False)
        assert body == line, f"未找到 marker 应返回原行，实际：{body!r}"
