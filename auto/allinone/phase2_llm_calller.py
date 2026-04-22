"""
Phase2 LLM 调用模块：生成字段映射和威胁类型映射的提示词，可选自动调用 LLM。
"""

import os
from pathlib import Path


def _read_file(path: str) -> str:
    """读取文本文件内容。"""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _write_file(path: str, content: str) -> None:
    """写入文本文件，自动创建父目录。"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _load_templates(config: dict) -> dict:
    """
    从配置中加载三个提示词模板文件。
    返回 {"field_strong": str, "field_weak": str, "threat": str}
    """
    templates = {}
    for key in ("field_strong", "field_weak", "threat"):
        tpl_path = config.get("prompt_templates", {}).get(key)
        if not tpl_path:
            raise ValueError(f"配置中缺少模板路径: prompt_templates.{key}")
        templates[key] = _read_file(tpl_path)
    return templates


def _build_prompts(normalize_content: str, templates: dict) -> dict:
    """
    将 phase1 输出内容替换到模板占位符 {{NORMALIZE_INDEXES}} 中。
    返回三个填充后的提示词字符串。
    """
    placeholder = "{{NORMALIZE_INDEXES}}"
    return {
        key: tpl.replace(placeholder, normalize_content)
        for key, tpl in templates.items()
    }


def _call_llm(prompt: str, llm_config: dict) -> str:
    """
    调用 OpenAI API，返回模型回复文本。
    """
    try:
        import openai
    except ImportError:
        raise ImportError("请先安装 openai 包：pip install openai")

    openai.api_key = llm_config.get("api_key") or os.environ.get("OPENAI_API_KEY", "")
    model = llm_config.get("model", "gpt-4")
    max_tokens = llm_config.get("max_tokens", 4096)
    temperature = llm_config.get("temperature", 0.0)

    response = openai.ChatCompletion.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return response.choices[0].message.content


def process_phase2(
    normalize_indexes_file: str,
    output_dir: str,
    phase2_config: dict = None,
    auto_call: bool = False,
) -> dict:
    """
    Phase2 主入口：生成提示词文件，可选自动调用 LLM 生成映射文件。

    参数：
        normalize_indexes_file: phase1 输出的 normalize_indexes.txt 路径
        output_dir: 输出目录（如 data/output/phase2）
        phase2_config: phase2 配置字典，包含 prompt_templates / llm 等
        auto_call: True 时自动调用 LLM；False 时仅生成提示词文件

    返回：
        {
            "field_mapping_file": str,       # 字段映射结果路径（auto_call=True 时有效）
            "threat_mapping_file": str,      # 威胁类型映射结果路径（auto_call=True 时有效）
            "prompt_files": {
                "field_strong": str,
                "field_weak": str,
                "threat": str,
            }
        }
    """
    if phase2_config is None:
        phase2_config = {}
    llm_config = phase2_config.get("llm", {})

    # 读取 phase1 输出
    normalize_content = _read_file(normalize_indexes_file)

    # 加载模板并填充
    templates = _load_templates(phase2_config)
    prompts = _build_prompts(normalize_content, templates)

    # 写出提示词文件
    prompts_dir = os.path.join(output_dir, "prompts")
    prompt_file_map = {
        "field_strong": os.path.join(prompts_dir, "field_strong_prompt.md"),
        "field_weak":   os.path.join(prompts_dir, "field_weak_prompt.md"),
        "threat":       os.path.join(prompts_dir, "threat_prompt.md"),
    }
    for key, path in prompt_file_map.items():
        _write_file(path, prompts[key])
        print(f"[Phase2] 提示词已写出: {path}")

    field_mapping_file = ""
    threat_mapping_file = ""

    if auto_call:
        # 自动调用 LLM
        print("[Phase2] 正在调用 LLM 生成字段映射...")
        field_result = _call_llm(prompts["field_strong"], llm_config)
        field_mapping_file = os.path.join(output_dir, "field_mapping.md")
        _write_file(field_mapping_file, field_result)
        print(f"[Phase2] 字段映射已写出: {field_mapping_file}")

        print("[Phase2] 正在调用 LLM 生成威胁类型映射...")
        threat_result = _call_llm(prompts["threat"], llm_config)
        threat_mapping_file = os.path.join(output_dir, "threat_type_mapping.md")
        _write_file(threat_mapping_file, threat_result)
        print(f"[Phase2] 威胁类型映射已写出: {threat_mapping_file}")
    else:
        print("[Phase2] auto_call=False，跳过 LLM 调用。请手动使用提示词文件。")

    return {
        "field_mapping_file": field_mapping_file,
        "threat_mapping_file": threat_mapping_file,
        "prompt_files": prompt_file_map,
    }
