"""V2 只保存允许的进度字段，不透传任意专业工具或模型细节。"""
import hashlib

OPERATIONS = frozenset({"log_parse", "field_mapping", "enum_extract", "threat_mapping", "fill", "remove_mapping", "export", "add_fields", "delete_fields", "merge_fields", "decode_fields", "regex_extract"})


class RunProgressSink:
    """绑定 Run/lease/fence，迟到事件与迟到结果同样失去发布资格。"""
    def __init__(self, store, worker_id, claim):
        self.store, self.worker_id, self.claim = store, worker_id, claim

    def scope(self, plan_id, step_id):
        """原始计划或步骤标识可能含用户值，只保存单运行稳定哈希。"""
        return "step-" + hashlib.sha256((self.claim["id"] + "\0" + plan_id + "\0" + step_id).encode()).hexdigest()[:24]

    async def publish(self, event):
        """只保留安全枚举与匿名依赖，不存 message_code、问题或未审查 detail。"""
        operation = next((item for item in OPERATIONS if event.message_code.startswith(item + "_")), None)
        summary = {"phase": event.phase.value, "progress_status": event.status.value, "operation": operation,
                   "dependency_scope_ids": [self.scope(event.plan_id, dependency) for dependency in event.dependency_step_ids]}
        self.store.record_progress(self.worker_id, self.claim, self.scope(event.plan_id, event.step_id), summary)
