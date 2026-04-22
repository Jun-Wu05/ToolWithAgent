# -*- coding: utf-8 -*-
"""从日志文件中按字段键和正则逐行提取匹配的非重复值，并输出到文件。"""

from __future__ import annotations

import json
import re
import time
from collections import OrderedDict
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"


def read_log_lines(path: Path) -> list[str]:
    """读取日志文件的所有行（保留原始行号相关信息）。"""
    for encoding in ("utf-8-sig", "utf-16", "gbk", "cp936", "utf-8"):
        try:
            with path.open("r", encoding=encoding) as f:
                return [line.rstrip("\n") for line in f]
        except UnicodeDecodeError:
            continue
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        return [line.rstrip("\n") for line in f]


def process_log_once(log_lines: list[str], field_key: str, pattern: str):
    """【性能优化版】一次遍历完成所有逻辑，保持原输出不变"""
    # 预编译正则表达式
    regex = re.compile(pattern)
    unique_values = OrderedDict()
    value_lines = OrderedDict()  # value -> list of lines (保持原样，包括重复)
    matched_indexes = set()
    
    # 优化点1：预分配常用变量，减少属性查找
    append_to_lines = None  # 将在循环中动态设置

    for idx, raw_line in enumerate(log_lines):
        # 快速过滤：字段key不在行中则跳过
        if field_key not in raw_line:
            continue
            
        line = raw_line.strip()
        if not line:
            continue

        # 优化点2：直接在当前行查找所有匹配
        matches = regex.findall(line)
        if not matches:
            continue
            
        # 标记当前行已匹配
        matched_indexes.add(idx)
        
        # 优化点3：使用集合去重当前行的匹配值
        current_values = set()
        for match in matches:
            if isinstance(match, tuple):
                # 取元组中第一个非空值
                match_value = next((item for item in match if item), "")
            else:
                match_value = match
            
            if match_value:
                current_values.add(match_value)
        
        # 优化点4：批量处理当前行的所有唯一值
        for val in current_values:
            if val not in unique_values:
                unique_values[val] = None
                value_lines[val] = []
            value_lines[val].append(raw_line)

    # 优化点5：使用列表推导式快速获取未匹配行
    unmatched_lines = [
        log_lines[i] for i in range(len(log_lines))
        if i not in matched_indexes
    ]

    return list(unique_values.keys()), value_lines, unmatched_lines


def reorder_log_lines(value_lines: OrderedDict[str, list[str]], unmatched_lines: list[str]) -> list[str]:
    """按字段值分组输出日志块。"""
    reordered: list[str] = []
    for value, lines in value_lines.items():
        if lines:
            reordered.append(value)
            reordered.extend(lines)
            reordered.append("==========")
    if unmatched_lines:
        reordered.append("未匹配")
        reordered.extend(unmatched_lines)
        reordered.append("==========")
    return reordered


def save_result(field_key: str, pattern: str, log_lines: list[str],
                unique_values: list[str], value_lines: OrderedDict[str, list[str]],
                unmatched_lines: list[str], source_name: str) -> tuple[Path, Path, Path]:

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff-]+", "_", field_key).strip("_") or "field"
    safe_source = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff-]+", "_", source_name).strip("_") or "source"
    output_file = OUTPUT_DIR / f"{safe_source}_{safe_name}.txt"
    mapping_file = OUTPUT_DIR / f"{safe_source}_{safe_name}_mapping.txt"
    reordered_file = OUTPUT_DIR / f"{safe_source}_{safe_name}_reordered.txt"

    # 保持原输出：每个值只取第一个匹配行
    original_logs: list[str] = []
    for value in unique_values:
        matched_lines = value_lines.get(value, [])
        original_logs.append(matched_lines[0] if matched_lines else None)

    with output_file.open("w", encoding="utf-8") as file:
        payload = {
            "field": field_key,
            "regex": pattern,
            "original_log": original_logs,
            "value": unique_values,
        }
        json.dump(payload, file, ensure_ascii=False, indent=4)

    with mapping_file.open("w", encoding="utf-8") as file:
        file.write("mappingType\torgValue\tmappingValue\n")
        for value in unique_values:
            file.write(f"REGULAR\t{value}\t\n")

    reordered_lines = reorder_log_lines(value_lines, unmatched_lines)
    with reordered_file.open("w", encoding="utf-8") as file:
        for line in reordered_lines:
            file.write(f"{line}\n")

    return output_file, mapping_file, reordered_file


def main() -> None:
    """程序入口。【完全保留原来的界面提示】"""
    field_key = input("请输入字段key: ").strip()
    default_pattern = fr'["\']{field_key}["\']\s*:\s*["\']([^"\']*?)["\']'
    pattern = input(f"请输入正则（直接回车使用默认：{default_pattern}）: ").strip() or default_pattern

    if not field_key:
        raise ValueError("字段key不能为空")
    if not pattern:
        raise ValueError("正则不能为空")

    if not DATA_DIR.exists():
        raise FileNotFoundError(f"未找到 data 目录: {DATA_DIR}")

    data_files = [p for p in DATA_DIR.iterdir() if p.is_file()]
    if not data_files:
        raise FileNotFoundError(f"data 目录下没有可处理的文件: {DATA_DIR}")

    for data_file in sorted(data_files):
        print(f"\n正在处理文件: {data_file.name}")
        
        # 添加性能监控
        start_time = time.time()
        
        log_lines = read_log_lines(data_file)
        read_time = time.time() - start_time
        print(f"  读取到 {len(log_lines)} 行日志 (耗时: {read_time:.2f}s)")

        # ================ 核心优化：一次遍历，保持原输出 ================
        process_start = time.time()
        unique_values, value_lines, unmatched_lines = process_log_once(log_lines, field_key, pattern)
        process_time = time.time() - process_start
        
        print(f"  找到 {len(unique_values)} 个非重复字段值 (耗时: {process_time:.2f}s)")
        
        # 可选：显示前几个值（如果太多可以限制显示数量）
        max_display = 10
        for i, v in enumerate(unique_values):
            if i >= max_display:
                print(f"    ... 还有 {len(unique_values) - max_display} 个值")
                break
            print(f"    - {v}")

        save_start = time.time()
        output_file, mapping_file, reordered_file = save_result(
            field_key, pattern, log_lines, unique_values, value_lines, unmatched_lines, data_file.stem
        )
        save_time = time.time() - save_start
        
        print(f"  已输出到: {output_file}")
        print(f"  mapping表已输出到: {mapping_file}")
        print(f"  重排原始行已输出到: {reordered_file}")
        print(f"  总耗时: {time.time() - start_time:.2f}s")


if __name__ == "__main__":
    main()