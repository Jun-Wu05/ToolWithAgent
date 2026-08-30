"""Chainlit DataFrame display helpers."""


def create_dataframe_elements(mapping_data: list) -> list:
    """把映射结果转换为 Chainlit 内联 Dataframe 元素。"""
    import chainlit as cl
    import pandas as pd

    if not mapping_data:
        return []
    return [
        cl.Dataframe(
            data=pd.DataFrame(mapping_data),
            display="inline",
            title="📊 映射结果",
            pagination=0,
        )
    ]


__all__ = [
    "create_dataframe_elements",
]
