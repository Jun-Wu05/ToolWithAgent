"""测试专用 SessionState 工厂：单一构造点 + 场景预设（#357）。

导入约定：本模块必须按顶层模块导入（``from factories import ...``），
不得写成 ``from tests.factories import ...``——site-packages 里存在同名
``tests`` 正规包，会遮蔽本仓 tests/ 的命名空间包解析（#357 实施时实测）。
pytest 对无 ``__init__.py`` 的 tests/ 目录按 prepend 模式自动将其加入
sys.path，顶层导入开箱即用。

契约：
- ``make_session_state(**overrides)`` 与 ``SessionState(**overrides)`` 完全等价，
  差异只在「构造经由唯一入口」——会话字段演进时测试侧只需改这里。
- 预设函数只固化多处在测场景间「值完全一致」的字段族（实施时实测，见 #357
  领取协议第 2 条），其余字段一律通过 overrides 显式表达；预设不设置成员
  用例未共同设置的任何字段，保证迁移零语义变化。
- ``test_session_state_contract.py`` 的契约自证用例仍直接构造 SessionState
  （被测对象即 SessionState 本身），不经工厂。
"""

from __future__ import annotations

from application.session_state import SessionState


def make_session_state(**overrides) -> SessionState:
    """测试侧会话构造的唯一入口；overrides 透传 SessionState 字段。"""
    return SessionState(**overrides)


def make_session_state_with_stale_derived_state(**overrides) -> SessionState:
    """「旧派生状态待清理」场景：enum 附件与贡献记录字段族。

    消费方：文件上传清理语义测试（新主数据提交后旧派生状态必须对称失效）。
    """
    return make_session_state(
        enum_excel_path="old-enum.xlsx",
        enum_preview=[{"目标字段": "old_field"}],
        enum_mapping_sheets={"old_field": [{"orgValue": "old"}]},
        enum_fill_contributions={
            "session.decoded_config": {"old_field": [{"mapping": {"orgValue": "old"}}]}
        },
        stale_enum_config_refs={"session.decoded_config"},
        enum_pending_refills={"session.decoded_config": {"old_field"}},
        **overrides,
    )


def make_session_state_with_current_dataset(**overrides) -> SessionState:
    """「当前有效会话」场景：已解码数据 + 枚举附件基线。

    消费方：无效上传保留语义测试（上传失败时当前会话状态必须原样保留）。
    """
    return make_session_state(
        decoded_data={"name": "current"},
        decoded_fields=["current_field"],
        enum_excel_path="current-enum.xlsx",
        enum_preview=[{"目标字段": "current_field"}],
        **overrides,
    )
