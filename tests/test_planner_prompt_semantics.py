"""Planner 提示词的离线语义目录与消歧契约测试。"""

from pathlib import Path


PROMPT = (
    Path(__file__).resolve().parent.parent / "agent" / "prompts" / "planner.md"
).read_text(encoding="utf-8")


def test提示词定义七类操作及各自必需参数():
    """防止统一路由再次只依靠模型从操作名猜任务边界。"""
    for operation in (
        "log_parse",
        "field_mapping",
        "enum_extract",
        "threat_mapping",
        "fill",
        "remove_mapping",
        "export",
    ):
        assert f"`{operation}`" in PROMPT
    # log_parse 默认自动探测分类特征字段，仅显式点名时携带可选 feature_field（PRD #110）。
    assert "默认不选字段、由系统自动探测分类特征字段" in PROMPT
    assert "必须有 `target_field`" in PROMPT


def test提示词包含日志类型与枚举提取的正反例():
    """“日志类型提取”必须稳定落到无目标字段的 LogParseStep。"""
    assert "“日志类型提取”“日志分类”“日志解析”是 `log_parse`" in PROMPT
    assert "是 `enum_extract`，两者不可互换" in PROMPT
    assert '{"step_id":"log-1","type":"log_parse"}' in PROMPT
    assert '"type":"enum_extract","target_field":"事件级别"' in PROMPT
    assert "不得生成 `enum_extract` 或询问字段" in PROMPT


def test提示词定义显式分类特征字段语义():
    """「把X字段作为日志类型」必须映射为携带 feature_field 的 log_parse（PRD #110）。"""
    assert "作为/当作/设为/当日志类型" in PROMPT
    assert "默认不选字段、由系统自动探测分类特征字段" in PROMPT
    assert "可选 `feature_field=X`" in PROMPT
    assert "允许点分路径" in PROMPT


def test提示词消歧枚举字样与作为日志类型短语():
    """带「枚举」字样但含「作为日志类型」短语的表达仍属 log_parse，不误入枚举提取。"""
    assert "“把A的枚举值作为日志类型”即使句中出现“枚举”" in PROMPT
    assert "也是携带 feature_field=A 的 `log_parse`" in PROMPT
    assert "用 X 区分日志类型" in PROMPT


def test提示词含显式字段单例与复合句拆两步示例():
    """显式分类特征字段示例固定步骤形态；复合句分解为枚举提取 + 日志类型提取两步。"""
    assert "把 category 字段作为日志类型" in PROMPT
    assert '{"step_id":"log-1","type":"log_parse","feature_field":"category"}' in PROMPT
    assert "提取 category 的枚举值，然后按 category 做日志类型分类" in PROMPT
    assert '"type":"log_parse","feature_field":"category"' in PROMPT


def test提示词包含三步复合计划与冲突澄清():
    """代表性 few-shot 同时固定依赖链与失败关闭行为。"""
    assert '"type":"enum_extract"' in PROMPT
    assert '"type":"threat_mapping","source_ref":"step:enum-1"' in PROMPT
    assert '"type":"fill","fill_kind":"threat"' in PROMPT
    assert '"reason_code":"conflicting_intent"' in PROMPT
    assert "## 静默自检" in PROMPT


def test提示词允许decoded_config直接执行枚举填充():
    """上传 Base64 配置时，枚举填充不得错误要求先生成子规则。"""
    assert "`session.decoded_config` 或 `session.mapped_sub_rules` 均可" in PROMPT
    assert "无需先做字段映射" in PROMPT
    assert "可用配置（`session.decoded_config` 或 `session.mapped_sub_rules`）" in PROMPT


def test提示词明确区分枚举提取威胁映射与枚举填充():
    """提取并映射只产生两步，只有明确回写配置才允许追加 fill。"""
    assert "提取 alarm_name 的枚举值并进行威胁类型映射" in PROMPT
    assert "enum_extract → threat_mapping" in PROMPT
    assert "不得生成 `fill`" in PROMPT
    assert "明确要求“填充回配置”或“写入解析规则”" in PROMPT


def test提示词声明威胁映射不依赖枚举映射表():
    """无枚举映射表时威胁映射必须照常规划，不得据此追问（回归 #76）。"""
    assert "**不需要枚举映射表**" in PROMPT
    assert "`enum_mapping_row_count=0` 不是追问理由" in PROMPT


def test提示词声明枚举填充免追问并默认全字段填充():
    """映射表与配置齐备时不得追问目标字段；未点名即填全部目标字段（回归 #91）。"""
    assert "直接生成填充步骤，不必追问目标字段" in PROMPT
    assert "未点名就填充 `enum_mapping_target_fields` 的**全部**字段" in PROMPT
    assert "多 sheet 映射表每个 sheet 的目标字段都填" in PROMPT


def test提示词只允许白名单会话产物并声明选择优先级():
    """跨轮来源必须显式、类型化，且不能压过本轮用户值或步骤结果。"""
    assert "`session.artifacts.enum_values`" in PROMPT
    assert "`session.artifacts.threat_mapping`" in PROMPT
    assert "优先使用当前文本的显式值" in PROMPT
    assert "其次使用本计划可依赖的 Enum Extract 步骤" in PROMPT
    assert "自然续接" in PROMPT
    assert "旧 `last_*` 不是合法来源" in PROMPT


def test提示词约束威胁产物字段绑定与无字段产物澄清():
    """有字段产物不得改投其他字段，无字段产物必须由用户明确目标。"""
    assert "只能使用同一目录项 `target_bindings`" in PROMPT
    assert "没有 `source_field`" in PROMPT
    assert "只有用户在当前文本明确指定目标字段" in PROMPT
    assert '"reason_code":"artifact_target_mismatch"' in PROMPT
    assert "不得把目标静默改成" in PROMPT


def test提示词包含合并与提取的单操作化规则():
    """「添加X+合并/提取」不得拆成 add+操作 两步（#146 线上报错回归）。"""
    assert "单操作化" in PROMPT
    assert "禁止再生成 `add_fields`" in PROMPT
    assert "merge 自身创建目标字段" in PROMPT
    assert "只有当添加的字段与合并/提取的目标是**不同**字段时才拆成多步" in PROMPT


def test提示词要求字段名逐字取自当前原文():
    """目标与来源字段名不得沿用历史轮次（#146「响应内容1」丢字回归）。"""
    assert "逐字取自**当前用户原文**" in PROMPT
    assert "历史轮次出现过的字段名不得默认沿用" in PROMPT
    assert "由执行器解析为原始字段名" in PROMPT
