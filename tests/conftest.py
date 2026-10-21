"""pytest 全局配置（保持最小化，不引入全局副作用）。"""
import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


@pytest.fixture(autouse=True)
def _clear_query_embedding_cache():
    """隔离 field_retriever 的进程内查询向量缓存（#245），避免用例间串味。"""
    from agent.core import field_retriever

    field_retriever._QUERY_EMBEDDING_CACHE.clear()
    yield
    field_retriever._QUERY_EMBEDDING_CACHE.clear()


@pytest.fixture(autouse=True)
def _fake_event_name_classifier(monkeypatch):
    """默认把事件名称判定替换为空判定，避免测试意外发起真实 LLM 调用。

    空判定 = 不写入事件字段、不追加消息（适配器对空判定短路），
    存量测试行为与标注功能引入前完全一致。显式注入 ``llm_client``
    时透传给真实判定函数——单测据此用假 LLM 验证判定与校验逻辑；
    需要完全自定义判定行为的测试可再次 monkeypatch
    ``agent.shared.event_classify.classify_sub_rule_events`` 覆盖本守卫。
    """
    from agent.shared import event_classify

    real_classify = event_classify.classify_sub_rule_events

    async def _guarded_classify(sub_rules, *, llm_client=None):
        if llm_client is not None:
            return await real_classify(sub_rules, llm_client=llm_client)
        return {}, {}, []

    monkeypatch.setattr(event_classify, "classify_sub_rule_events", _guarded_classify)
