"""
应用会话状态管理 - 结构化 SessionState dataclass

将散落在代码各处的 20+ 个裸字符串 session key 封装为类型安全的 dataclass。
通过单一 key "user_session" 存储整个对象，所有字段通过 property 访问。
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Optional, List, Dict, Set

from contracts.session_artifacts import EnumArtifactSlot, ThreatArtifactSlot
from contracts.planner_models import StepSpec
from contracts.rule_source import RuleSourceFields


_MAPPED_SUB_RULE_CONFIG_REF = "session.mapped_sub_rules"
_MAPPING_DERIVED_STATE_KEYS = (
    "mapped_sub_rules",
    "sub_rule_mapping_results",
    "last_mapping_data",
    "excel_data",
    "excel_filename",
)


def _read_state_value(session: Any, key: str, default: Any = None) -> Any:
    """读取 SessionState 或测试字典，不把兼容细节泄漏给生命周期操作。"""
    if isinstance(session, Mapping):
        return session.get(key, default)
    return getattr(session, key, default)


def _write_state_value(session: Any, key: str, value: Any) -> None:
    """写入 SessionState 或测试字典。"""
    if isinstance(session, dict):
        session[key] = value
        return
    setattr(session, key, value)


def commit_log_classification(session: Any, classification: Dict[str, Any]) -> bool:
    """提交新日志分类并失效所有依赖旧分类的映射后子规则状态。

    返回是否实际清除了非空派生状态，供调用方决定是否向用户显示覆盖警告。
    与上传配置绑定的枚举贡献必须保留；这里只移除已失效的映射后子规则引用。
    """
    had_mapping_derivatives = any(
        bool(_read_state_value(session, key)) for key in _MAPPING_DERIVED_STATE_KEYS
    )
    for key in _MAPPING_DERIVED_STATE_KEYS:
        _write_state_value(session, key, None)

    contributions = dict(
        _read_state_value(session, "enum_fill_contributions", {}) or {}
    )
    if contributions.pop(_MAPPED_SUB_RULE_CONFIG_REF, None) is not None:
        had_mapping_derivatives = True
    _write_state_value(session, "enum_fill_contributions", contributions)

    stale_refs = set(
        _read_state_value(session, "stale_enum_config_refs", set()) or set()
    )
    if _MAPPED_SUB_RULE_CONFIG_REF in stale_refs:
        had_mapping_derivatives = True
        stale_refs.discard(_MAPPED_SUB_RULE_CONFIG_REF)
    _write_state_value(session, "stale_enum_config_refs", stale_refs)

    pending_refills = dict(
        _read_state_value(session, "enum_pending_refills", {}) or {}
    )
    if pending_refills.pop(_MAPPED_SUB_RULE_CONFIG_REF, None) is not None:
        had_mapping_derivatives = True
    _write_state_value(session, "enum_pending_refills", pending_refills)

    _write_state_value(session, "rule_source_fields", None)
    _write_state_value(session, "pending_rule_source_step", None)
    _write_state_value(session, "log_classification", classification)
    return had_mapping_derivatives


@dataclass(frozen=True)
class PrimaryDatasetSnapshot:
    """已完整解析并校验、可原子提交到会话的主数据快照。"""

    decoded_data: Any
    decoded_fields: List[str]
    original_log: Any
    simplified_data: Dict[str, Any]
    decoded_text: str
    uploaded_file_name: str
    uploaded_file_time: str
    raw_log_lines: Optional[List[str]] = None
    raw_base64: Optional[str] = None


@dataclass
class SessionState:
    """Chainlit 用户会话状态，完全替代零散的 dict session key 读写。

    约定：
    - 所有字段都有默认值，确保初始化时不会遗漏
    - 使用 Optional 标记可能为空的字段
    - 字段注释说明用途和生命周期
    """

    # ---- 核心 Agent ----
    team: Any = None
    """Agno Team 实例（单例缓存），on_chat_start 时初始化，整个会话期间复用"""

    # ---- 解码后的数据 ----
    decoded_data: Optional[dict] = None
    """B64/TXT 解码后的 JSON 数据，文件上传后设置"""

    decoded_fields: Optional[List[str]] = None
    """解码数据中的字段列表"""

    original_log: Optional[List[str]] = None
    """原始日志行列表"""

    simplified_data: Optional[Dict[str, Any]] = None
    """简化数据（fields + original_log_sample），用于 LLM 输入构建"""

    decoded_text: Optional[str] = None
    """解码后的原始文本，供 input_builder 后备使用（解码时保存，映射时作为上下文）"""

    raw_log_lines: Optional[List[str]] = None
    """从数据表格的"原始日志"列预提取的行列表，供 LogParserAgent 精简输入使用"""

    # ---- 文件上传元信息（Agent 自决清空所需）----
    uploaded_file_name: Optional[str] = None
    """最近上传的文件名，供 Agent 感知当前会话处理的是哪个文件"""

    uploaded_file_time: Optional[str] = None
    """最近上传文件的时间戳（HH:MM:SS 格式）"""

    # ---- 字段映射结果 ----
    last_mapping_data: Optional[List[Dict[str, Any]]] = None
    """最后一次字段映射的结果列表，供确认填充使用"""

    excel_data: Optional[bytes] = None
    """Excel 导出二进制数据"""

    excel_filename: Optional[str] = None
    """Excel 导出文件名"""

    # ---- 威胁类型 ----
    last_threat_data: Optional[List[Dict[str, Any]]] = None
    """最后一次威胁类型映射的结果列表"""

    latest_threat_artifact: Optional[ThreatArtifactSlot] = None
    """最近一次成功、可由后续类型化计划显式引用的威胁映射产物"""

    # ---- 枚举映射输入 ----
    raw_base64: Optional[str] = None
    """原始 Base64 内容缓存，供确定性文件事件和类型化执行步骤使用"""

    enum_excel_path: Optional[str] = None
    """枚举映射表 Excel 文件路径"""

    enum_preview: Optional[List[Dict[str, Any]]] = None
    """枚举映射预览数据"""

    enum_mapping_sheets: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    """当前主数据下按 Sheet 名管理的枚举映射集合"""

    enum_fill_contributions: Dict[str, Dict[str, List[Dict[str, Any]]]] = field(
        default_factory=dict
    )
    """按配置来源和 Sheet 记录实际写入的枚举贡献"""

    stale_enum_config_refs: Set[str] = field(default_factory=set)
    """枚举附件已变化、必须重新填充后才能继续使用的配置来源"""

    enum_pending_refills: Dict[str, Set[str]] = field(default_factory=dict)
    """每个配置来源尚未应用的 Sheet 集合；全部成功后才恢复有效"""

    # ---- 枚举提取结果 ----
    last_enum_extract_result: Optional[Dict[str, Any]] = None
    """最后一次枚举提取的结果"""

    latest_enum_artifact: Optional[EnumArtifactSlot] = None
    """最近一次成功、可由后续类型化计划显式引用的枚举值产物"""

    # ---- 日志解析结果 ----
    log_classification: Optional[Dict[str, Any]] = None
    """日志解析 Pipeline 的分类结果，供规则导出使用"""

    rule_source_fields: Optional[RuleSourceFields] = None
    """用户显式填写、绑定当前主数据和日志分类的规则来源字段"""

    pending_rule_source_step: Optional[StepSpec] = None
    """因缺少规则来源字段而等待表单提交的类型化步骤"""

    # ---- 标准字段映射结果 ----
    mapped_sub_rules: Optional[List[Dict[str, Any]]] = None
    """映射后的子规则列表，供导出使用"""

    sub_rule_mapping_results: Optional[List[Dict[str, Any]]] = None
    """标准字段映射结果（每条子规则的映射对照表）"""

    # ---- 模型配置 ----
    current_provider: Optional[str] = None
    """当前供应商（"deepseek" | "siliconflow"）"""

    api_key: Optional[str] = None
    """API Key（界面输入，覆盖环境变量）"""

    model_name: Optional[str] = None
    """模型名称（界面选择，覆盖环境变量）"""

    # ---- 对话历史（自定义记忆，不依赖 Agno session）----
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    """多轮对话历史，每项 {role: 'user'|'assistant', content: str}。
    由 web/history_store.py 管理，统一 Planner 消费最近 N 轮。
    clear_decoded_data 时同步清空。"""

    # ---- 工厂方法 ----

    @classmethod
    def create_default(cls) -> "SessionState":
        """创建默认状态的 SessionState 实例"""
        return cls()

    # ---- 便捷方法 ----

    def has_decoded_data(self) -> bool:
        """是否已有解码后的数据"""
        return self.decoded_data is not None or self.decoded_fields is not None

    def clear_decoded_data(self) -> None:
        """清除当前主数据及其全部附件和派生结果。"""
        self.decoded_data = None
        self.decoded_fields = None
        self.decoded_text = None
        self.original_log = None
        self.raw_log_lines = None
        self.simplified_data = None
        self.uploaded_file_name = None
        self.uploaded_file_time = None
        self.raw_base64 = None
        self.enum_excel_path = None
        self.enum_preview = None
        self.enum_mapping_sheets = {}
        self.enum_fill_contributions = {}
        self.stale_enum_config_refs = set()
        self.enum_pending_refills = {}
        self.last_mapping_data = None
        self.excel_data = None
        self.excel_filename = None
        self.last_threat_data = None
        self.latest_threat_artifact = None
        self.last_enum_extract_result = None
        self.latest_enum_artifact = None
        self.log_classification = None
        self.rule_source_fields = None
        self.pending_rule_source_step = None
        self.mapped_sub_rules = None
        self.sub_rule_mapping_results = None
        # 主数据失效时 Planner 历史也必须失效，避免旧文件语义污染新请求。
        self.conversation_history = []

    def replace_primary_dataset(self, snapshot: PrimaryDatasetSnapshot) -> None:
        """原子替换当前主数据；调用前必须完成全部解析和校验。"""
        decoded_fields = list(snapshot.decoded_fields)
        self.clear_decoded_data()
        self.decoded_data = snapshot.decoded_data
        self.decoded_fields = decoded_fields
        self.original_log = snapshot.original_log
        self.simplified_data = snapshot.simplified_data
        self.decoded_text = snapshot.decoded_text
        self.raw_log_lines = snapshot.raw_log_lines
        self.raw_base64 = snapshot.raw_base64
        self.uploaded_file_name = snapshot.uploaded_file_name
        self.uploaded_file_time = snapshot.uploaded_file_time

    def get_session_summary(self) -> str:
        """
        构建当前会话的人类可读摘要，仅供界面展示和历史兼容。

        返回示例：
            - 已上传文件：syslog_config.txt
            - 字段数量：51 个
            - 字段映射：已完成（批量映射）
            - 子规则：已生成 3 条，已映射字段
            - 枚举映射表：已加载（event_type）
            - 威胁映射：已完成 12 条

        无任何数据时返回空字符串。
        """
        parts = []

        # 文件信息
        if self.has_decoded_data():
            field_count = len(self.decoded_fields) if self.decoded_fields else 0
            if self.uploaded_file_name:
                parts.append(f"- 已上传文件：{self.uploaded_file_name}")
            parts.append(f"- 字段数量：{field_count} 个")
            if self.uploaded_file_time:
                parts.append(f"- 上传时间：{self.uploaded_file_time}")
        elif self.last_mapping_data or self.mapped_sub_rules:
            # 数据可能已清空但映射结果还在
            parts.append("- 当前无文件数据，但有历史映射结果")

        # 字段映射状态
        if self.last_mapping_data:
            parts.append(f"- 字段映射：已完成（{len(self.last_mapping_data)} 条）")

        # 子规则状态
        if self.mapped_sub_rules:
            parts.append(f"- 子规则：已生成 {len(self.mapped_sub_rules)} 条，已映射字段")
        elif self.sub_rule_mapping_results:
            parts.append(f"- 子规则：已生成 {len(self.sub_rule_mapping_results)} 条")

        # 枚举状态
        if self.enum_excel_path:
            parts.append(f"- 枚举映射表：已加载（{self.enum_excel_path}）")
        if self.last_enum_extract_result:
            parts.append("- 枚举提取：已有结果")

        # 威胁状态
        if self.last_threat_data:
            parts.append(f"- 威胁映射：已完成 {len(self.last_threat_data)} 条")

        # 日志解析状态
        if self.log_classification:
            parts.append("- 日志解析：已完成")

        return "\n".join(parts) if parts else ""

    def clear_mapping_results(self) -> None:
        """清除映射结果"""
        self.last_mapping_data = None
        self.last_threat_data = None
        self.excel_data = None
        self.excel_filename = None

    # ---- Dict 兼容层（过渡期，后续可移除）----

    def get(self, key: str, default: Any = None) -> Any:
        """dict.get() 兼容方法，迁移完成后可移除"""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """dict[key] 兼容方法"""
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        """dict[key] = value 兼容方法"""
        if hasattr(self, key):
            setattr(self, key, value)
        else:
            raise KeyError(f"SessionState 没有字段: {key}")

    def __contains__(self, key: str) -> bool:
        """key in dict 兼容方法"""
        return hasattr(self, key)

    def pop(self, key: str, default: Any = None) -> Any:
        """dict.pop() 兼容方法 — 取值后重置为默认值"""
        if hasattr(self, key):
            value = getattr(self, key)
            setattr(self, key, default)
            return value
        return default
