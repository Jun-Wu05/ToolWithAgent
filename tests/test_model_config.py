"""共享 Agent 模型配置的结构化输出稳定性测试。"""

from agent.core.model_config import ModelConfig


def testDeepSeekV4Agent禁用思考以避免结构化content为空():
    """Planner 与专业 Agent 应复用 Pipeline 已验证的 V4 非思考配置。"""
    model = ModelConfig._build_model(
        "deepseek-v4-flash",
        api_key="test-key",
        provider="deepseek",
    )

    assert model.extra_body == {"thinking": {"type": "disabled"}}


def test普通DeepSeek模型不注入特定思考参数():
    """只约束已知 V4 模型，避免改变其他 Provider 模型语义。"""
    model = ModelConfig._build_model(
        "deepseek-chat",
        api_key="test-key",
        provider="deepseek",
    )

    assert model.extra_body is None
