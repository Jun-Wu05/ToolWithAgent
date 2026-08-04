"""
模板脚本 - 展示 CLI + import 双模式的标准结构

CLI 用法:
    python example.py '<json_data>'
    
import 用法:
    from example import process
    result = process(data)
"""

import json
import sys
from typing import Any


def process(data: Any) -> dict:
    """
    核心处理函数
    
    Args:
        data: 输入数据（通常是 JSON 对象或数组）
    
    Returns:
        {"status": "success"|"error", "data": ..., "message": "..."}
    """
    if not data:
        return {"status": "error", "message": "输入数据为空"}
    
    # TODO: 实现核心逻辑
    result = data
    
    return {"status": "success", "data": result, "message": "处理完成"}


def main():
    """CLI 入口"""
    if len(sys.argv) < 2:
        print(json.dumps({
            "status": "error",
            "message": "用法: python example.py '<json_data>'"
        }, ensure_ascii=False))
        sys.exit(1)
    
    try:
        data = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        # 从 stdin 读取
        if sys.argv[1] == "-":
            data = json.loads(sys.stdin.read())
        else:
            raise
    
    result = process(data)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
