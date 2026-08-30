"""迁移期兼容入口及历史确定性编码函数。

上传解码实现归属于 Application；旧模块继续重导出相同对象。
`simple_encode` 暂无生产调用，但其历史返回契约不在本次迁移范围内。
"""

import base64
import json



def simple_encode(data: dict) -> dict:
    """按历史 JSON 与 Base64 格式编码字典。"""
    try:
        json_text = json.dumps(data, ensure_ascii=False)
        encoded = base64.b64encode(json_text.encode("utf-8")).decode("utf-8")

        return {"status": "success", "encoded": encoded}
    except Exception as error:
        return {"status": "error", "error_message": str(error)}


__all__ = ["simple_encode"]
