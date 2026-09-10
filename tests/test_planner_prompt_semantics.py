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
    """未点名威胁类型的提取+映射保持两步，不加 fill/add_fields（#173 修订后语义）。"""
    assert "提取 alarm_name 的枚举值并进行威胁类型映射" in PROMPT
    assert "enum_extract → threat_mapping" in PROMPT
    assert "不得生成 `fill` 或 `add_fields`" in PROMPT
    assert "未点名威胁类型为目标字段" in PROMPT


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


def test提示词约束威胁填充固定目标与无绑定澄清():
    """威胁填充目标固定为威胁类型；点名其他字段或无绑定必须澄清（#173）。"""
    assert "目标固定为「威胁类型」" in PROMPT
    assert '`target_bindings` 中出现「威胁类型」绑定' in PROMPT
    assert '"reason_code":"threat_fill_target_fixed"' in PROMPT
    assert "不得把目标静默改成威胁类型" in PROMPT


def test提示词声明威胁链路四步指令与换来源话术():
    """显式链路指令生成四步且 X 逐字；换来源/删字段话术消歧（#173）。"""
    assert "威胁类型决策表" in PROMPT
    assert "enum_extract(<字段>) → threat_mapping → add_fields(威胁类型=%{<字段>}, reference, rule_group=threat)" in PROMPT
    assert "逐字取自当前指令" in PROMPT
    assert "请先执行标准字段映射以判定威胁子规则" in PROMPT
    assert "换链路来源" in PROMPT
    assert "重新执行字段映射会自动重建该字段" in PROMPT
    assert "未点名威胁类型为目标字段）保持两步" in PROMPT
    # 显式来源不存在时必须定向拒绝，不能倾倒完整字段池。
    assert "`reason_code=threat_source_not_found`" in PROMPT
    assert "不列出全部字段" in PROMPT


def test提示词按语义槽位识别威胁类型完整链路():
    """完整链路由来源、目标和值映射意图决定，不以固定措辞为门槛（#211）。"""
    for semantic_slot in ("`目标字段=威胁类型`", "`来源字段=X`", "`值映射意图`"):
        assert semantic_slot in PROMPT
    assert "reason_code=threat_source_required" in PROMPT
    assert "不在 `available_fields`" in PROMPT
    for synonym in ("映射为", "作为来源", "根据", "转成", "改用"):
        assert synonym in PROMPT
    assert "不依赖固定短语" in PROMPT
    assert "明确只做普通字段名映射并排除值映射" in PROMPT
    assert "首次链路只检查 `available_fields`" in PROMPT
    assert "不得臆造“威胁子规则字段池”门槛" in PROMPT


def test提示词定义类型化提案确认协议():
    """Agent 判断确认或取消，但不得复制或重建待确认步骤。"""
    assert "`pending_plan` 存在" in PROMPT
    assert "返回 `confirm`" in PROMPT
    assert "取消时返回 `cancel`" in PROMPT
    assert "只携带 `pending_plan_id`" in PROMPT
    assert "不得从对话历史重建步骤" in PROMPT


def test提示词消除固定字段冲突且没有超出长度预算():
    assert "【事件名称】【事件级别】【日志类型】是系统固定字段" in PROMPT
    assert "威胁类型不适用本条" in PROMPT
    assert len(PROMPT) <= 15_031


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


def test提示词要求信息型问题直接从会话事实作答():
    """事实已含答案的信息型问题必须 guidance+answer 直接作答，不 Clarification（回归 #149）。"""
    assert "信息型问题直接作答" in PROMPT
    assert "`answer` 字段用事实直接作答" in PROMPT
    assert "不得生成修改计划，也不得 Clarification" in PROMPT
    assert "事实中无答案（如 `event_annotations` 为空且尚未字段映射）时仍 Clarification" in PROMPT
    assert '"decision":"guidance","plan_id":"plan-qa","answer"' in PROMPT
    assert "`guidance_code`、`answer`、`parameters`" in PROMPT


def test提示词区分planner点名词典与字段映射候选池():
    """映射可执行性只看 mappable_fields，available_fields 仍服务用户点名。"""
    assert "`mappable_fields` 非空时执行" in PROMPT
    assert "`available_fields` 是用户显式点名字段的词典" in PROMPT
    assert "不得把它当作映射批次输入" in PROMPT
