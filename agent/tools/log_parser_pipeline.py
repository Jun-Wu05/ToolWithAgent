# -*- coding: utf-8 -*-
"""
日志格式识别与特征提取 Pipeline — 兼容入口。

⚠️  此文件已重构为薄包装层，实际实现已迁移至 agent/tools/pipeline/ 各子模块。
    子模块独立可测：每个 Step 可单独 import + 单独单测。
    此文件仅保留对外兼容的函数别名，不改动调用方代码。
"""

from agent.tools.pipeline.log_format_identifier import _do_identify_log_format, identify_log_format
from agent.tools.pipeline.log_classifier import _do_classify_log_features, classify_log_features
from agent.tools.pipeline.log_sample_filler import fill_sample_logs

# _do_* = 未装饰纯函数（chainlit_app 直接调用）
# identify_log_format / classify_log_features = @tool 装饰版（agent/tools/__init__.py 用）

__all__ = [
    "identify_log_format",
    "_do_identify_log_format",
    "classify_log_features",
    "_do_classify_log_features",
    "fill_sample_logs",
]