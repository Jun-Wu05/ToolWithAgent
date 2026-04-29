"""
Agent 层测试

覆盖：
- CancellationToken：基本行为 + 线程安全
- TeamManager：单例、统计、重置、线程安全计数
- Agent 创建：工具挂载验证、instructions 验证、Team 结构
- ModelConfig：主模型、fallback、API Key

只测试纯逻辑/结构，不调用外部 API。
通过 Agent 工厂函数创建 Agent，验证 tools 挂载、name、instructions、Team 单例等。

运行方式：
    cd d:\Agent\agent_design\toolswithagent
    python -m pytest tests/test_agent_layer.py -v
"""

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ====================================================================
# CancellationToken 测试
# ====================================================================

class TestCancellationToken:
    """取消令牌基本行为"""

    def test_initial_state_not_cancelled(self):
        from agent.core.team_web import CancellationToken
        token = CancellationToken()
        assert token.cancelled is False

    def test_cancel_sets_flag(self):
        from agent.core.team_web import CancellationToken
        token = CancellationToken()
        token.cancel()
        assert token.cancelled is True

    def test_double_cancel_idempotent(self):
        from agent.core.team_web import CancellationToken
        token = CancellationToken()
        token.cancel()
        token.cancel()
        assert token.cancelled is True

    def test_thread_safe_cancel(self):
        from agent.core.team_web import CancellationToken
        token = CancellationToken()
        results = []

        def worker():
            token.cancel()
            results.append(token.cancelled)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2)

        assert all(r is True for r in results)


# ====================================================================
# TeamManager 测试
# ====================================================================

class TestTeamManager:
    """TeamManager 线程安全和基本行为"""

    def test_singleton_same_instance(self):
        from agent.core.team_web import TeamManager
        m1 = TeamManager()
        m2 = TeamManager()
        assert m1 is m2

    def test_get_team_manager_returns_same_instance(self):
        from agent.core.team_web import get_team_manager
        m1 = get_team_manager()
        m2 = get_team_manager()
        assert m1 is m2

    def test_initial_stats(self):
        from agent.core.team_web import get_team_manager
        manager = get_team_manager()
        stats = manager.get_stats()
        assert stats["initialized"] is True
        assert stats["request_count"] == 0
        assert stats["active_threads"] >= 0

    def test_reset_clears_team(self):
        from agent.core.team_web import TeamManager
        manager = TeamManager.__new__(TeamManager)
        manager._initialized = True
        manager._team = "dummy"
        manager._request_count = 5
        manager._active_threads = set()
        manager._threads_lock = threading.Lock()
        manager._count_lock = threading.Lock()

        manager.reset()
        assert manager._team is None
        assert manager._request_count == 0

    def test_increment_count_thread_safety(self):
        from agent.core.team_web import TeamManager
        manager = TeamManager.__new__(TeamManager)
        manager._initialized = True
        manager._request_count = 0
        manager._count_lock = threading.Lock()
        manager._last_request_time = None
        manager._active_threads = set()
        manager._threads_lock = threading.Lock()

        counts = []

        def worker():
            c = manager._increment_count()
            counts.append(c)

        threads = [threading.Thread(target=worker) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2)

        assert sorted(counts) == list(range(1, 51))
        assert manager._request_count == 50


# ====================================================================
# Agent 创建测试 (不调用 API)
# ====================================================================

class TestAgentCreation:
    """Agent 工厂函数 - 验证结构而非推理结果"""

    def test_field_mapping_agent_has_tools(self):
        from agent.core.team import create_field_mapping_agent
        agent = create_field_mapping_agent()
        assert agent.name == "FieldMappingAgent"
        assert agent.tools is not None
        assert len(agent.tools) >= 3, f"Expected >=3 tools, got {len(agent.tools)}"

    def test_threat_agent_has_tools(self):
        from agent.core.team import create_threat_agent
        agent = create_threat_agent()
        assert agent.name == "ThreatAgent"
        assert agent.tools is not None
        assert len(agent.tools) >= 2, f"Expected >=2 tools, got {len(agent.tools)}"

    def test_enum_agent_has_tools(self):
        from agent.core.team import create_enum_agent
        agent = create_enum_agent()
        assert agent.name == "EnumAgent"
        assert agent.tools is not None
        assert len(agent.tools) >= 6, f"Expected >=6 tools, got {len(agent.tools)}"

    def test_field_mapping_agent_has_instructions(self):
        from agent.core.team import create_field_mapping_agent
        agent = create_field_mapping_agent()
        assert agent.instructions is not None
        assert len(str(agent.instructions)) > 0

    def test_threat_agent_has_instructions(self):
        from agent.core.team import create_threat_agent
        agent = create_threat_agent()
        assert agent.instructions is not None
        assert len(str(agent.instructions)) > 0

    def test_enum_agent_has_instructions(self):
        from agent.core.team import create_enum_agent
        agent = create_enum_agent()
        assert agent.instructions is not None
        assert len(str(agent.instructions)) > 0

    def test_team_creation_has_members(self):
        from agent.core.team import create_data_mapping_team
        team = create_data_mapping_team()
        assert team.members is not None
        assert len(team.members) == 3, f"Expected 3 members, got {len(team.members)}"

    def test_team_mode_is_route(self):
        from agent.core.team import create_data_mapping_team
        from agno.team.mode import TeamMode
        team = create_data_mapping_team()
        assert team.mode == TeamMode.route

    def test_get_team_instance_returns_same_object(self):
        from agent.core.team import get_team_instance, reset_team_instance
        reset_team_instance()
        t1 = get_team_instance()
        t2 = get_team_instance()
        assert t1 is t2

    def test_reset_team_instance_clears_cache(self):
        from agent.core.team import get_team_instance, reset_team_instance
        reset_team_instance()
        t1 = get_team_instance()
        reset_team_instance()
        t2 = get_team_instance()
        assert t1 is not t2

    def test_team_debug_mode_respects_env(self):
        from agent.core.team import create_data_mapping_team
        team = create_data_mapping_team()
        assert team.debug_mode is False
        assert team.show_members_responses is False


# ====================================================================
# 模型配置测试
# ====================================================================

class TestModelConfig:
    """模型配置"""

    def test_main_model_defined(self):
        from agent.core.model_config import ModelConfig
        assert ModelConfig.MAIN_MODEL is not None
        assert "deepseek" in ModelConfig.MAIN_MODEL.lower()

    def test_fallback_model_defined(self):
        from agent.core.model_config import ModelConfig
        assert ModelConfig.FALLBACK_MODEL is not None
        assert isinstance(ModelConfig.FALLBACK_MODEL, str)

    def test_fallback_enabled_default(self):
        from agent.core.model_config import ModelConfig
        assert isinstance(ModelConfig.FALLBACK_ENABLED, bool)

    def test_get_api_key_returns_string(self):
        from agent.core.model_config import ModelConfig
        key = ModelConfig.get_api_key()
        assert isinstance(key, str)