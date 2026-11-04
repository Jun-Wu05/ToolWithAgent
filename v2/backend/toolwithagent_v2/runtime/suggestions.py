"""#435 对话式引导建议目录：按业务节点给出 ≤4 个可执行下一步。

建议是按状态过滤的「过滤器」，不是功能目录（设计定稿见 #435 评论）：
动作芯片由前端接既有 API；prompt 芯片只填入输入框，由用户确认后发送。
字段值为 None 表示占位——由 store 在产物发布后回填真实 ID。
"""

MAX_SUGGESTIONS = 4


def upload_validated(file_id):
    """主数据校验通过：意图气泡。枚举可直提；映射需先提取（分叉②定稿）。"""
    return [
        {"type": "prompt", "id": "enum_extract", "label": "提取字段枚举值",
         "text": "提取【字段名】的枚举值"},
        {"type": "action", "id": "log_parse", "label": "日志类型提取", "file_id": file_id},
    ]


def classification_done():
    """日志类型提取完成：映射走分类产物入口（#432 后两入口同源）。"""
    return [
        {"type": "action", "id": "field_mapping", "label": "标准字段映射",
         "classification_artifact_id": None},
        {"type": "action", "id": "open_results", "label": "查看解析规则", "artifact_id": None},
        {"type": "prompt", "id": "enum_extract", "label": "提取字段枚举值",
         "text": "提取【字段名】的枚举值"},
    ]


def mapping_done():
    """字段映射完成：看结果、下载、一句话改映射。"""
    return [
        {"type": "action", "id": "open_results", "label": "查看映射结果", "artifact_id": None},
        {"type": "action", "id": "download", "label": "下载产物", "artifact_id": None},
        {"type": "prompt", "id": "mapping_edit", "label": "修改映射（多步可一句话）",
         "text": "给当前映射增加【字段a】，删除【字段b】"},
    ]


def business_done():
    """业务操作完成（枚举/威胁/导出）：单步结果看产物即可。"""
    return [
        {"type": "action", "id": "open_results", "label": "查看结果"},
        {"type": "prompt", "id": "continue_mapping", "label": "继续标准字段映射",
         "text": "对当前结果进行标准字段映射"},
    ]


def failed():
    """失败引导：重试 + 查看轨迹（run_id 取自消息自身，不重复携带）。"""
    return [
        {"type": "action", "id": "retry", "label": "重试"},
        {"type": "action", "id": "open_trace", "label": "查看轨迹"},
    ]
