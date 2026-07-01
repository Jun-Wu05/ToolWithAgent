# -*- coding: utf-8 -*-
"""
日志模式向量知识库 (B6)

存储已解析日志的指纹 + embedding，实现跨文件自动匹配。
- 指纹脱敏: IP→{ip}, 时间→{time}, 数字→{n}
- 存储: SQLite 存元数据 + .npy 存 embedding
- 检索: 余弦相似度
- 自动匹配阈值: ≥ 0.85

复用 agent/core/field_retriever.py 的 embedding API 和 cosine 工具函数。
"""

from __future__ import annotations

import json
import re as _re
import sqlite3
import time as _time
from pathlib import Path
from typing import Optional

import numpy as np

from agent.core.field_retriever import _call_embedding_api, _cosine_similarity
from agent.shared.logger import get_logger

logger = get_logger("log_pattern_store")

# ============================================================================
# 路径配置
# ============================================================================

_DB_PATH = Path(__file__).parent.parent.parent / "config" / "log_patterns.db"
_EMBEDDING_PATH = Path(__file__).parent.parent.parent / "config" / "log_patterns_embeddings.npy"
_META_PATH = Path(__file__).parent.parent.parent / "config" / "log_patterns_meta.json"

# 阈值
MATCH_THRESHOLD = 0.85


# ============================================================================
# 指纹脱敏
# ============================================================================

# IP 地址 (IPv4 简单匹配)
_IP_RE = _re.compile(
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
)
# 时间戳多种格式
_TIME_RE = _re.compile(
    r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}[T ]\d{1,2}:\d{2}:\d{2}(?:\.\d+)?"
    r"|"
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\b"  # May 12 16:48:10
    r"|"
    r"\b\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\b"  # 16:48:10
)
# 纯数字序列 (至少 3 位, 防止误杀短数字如 port, status)
_NUMBER_RE = _re.compile(r"\b\d{4,}\b")

def generate_log_fingerprint(log_line: str) -> str:
    """
    对单行日志进行指纹脱敏，保留结构骨架。

    Args:
        log_line: 一行原始日志

    Returns:
        脱敏后的指纹字符串
    """
    # 1. 替换时间戳
    line = _TIME_RE.sub("{time}", log_line)
    # 2. 替换 IP
    line = _IP_RE.sub("{ip}", line)
    # 3. 替换长数字序列
    line = _NUMBER_RE.sub("{n}", line)

    # 4. 保留非字母数字字符 (分隔符结构)，字母转小写
    line = line.lower()

    return line


def generate_fingerprint_from_fields(pattern_info: dict) -> str:
    """
    从字段特征信息生成指纹（不依赖原始日志行）。

    Args:
        pattern_info: classify_log_features 输出，包含 fields 列表

    Returns:
        指纹字符串（字段名序列 + 类型序列）
    """
    fields = pattern_info.get("fields", [])
    if not fields:
        return ""

    field_names = [f.get("field_name", "?") for f in fields]
    field_types = [f.get("field_type", "string") for f in fields]
    fmt = pattern_info.get("format", "unknown")

    # 指纹: format|field1:type1,field2:type2,...
    finger = f"{fmt}|" + ",".join(
        f"{n}:{t}" for n, t in zip(field_names, field_types)
    )
    return finger


def generate_structured_fingerprint(
    classify_result: dict,
    format_detail: str = "",
    feature_field: str = "",
) -> str:
    """
    基于 classify_log_features 输出的语义骨架生成结构化指纹。
    
    指纹 = format_detail | feature_field | feature_identifier_clean
    
    对日志增删字段不敏感——只要核心正则骨架不变，指纹就不变。
    
    feature_identifier_clean 处理：
    - 将 Group 2（值捕获）改为通用匹配，使同类日志指纹一致
    - 归一化转义字符统一用小写 (\\s, \\w, \\d ...)
    
    Args:
        classify_result: classify_log_features 的输出 dict
        format_detail: 格式详情（"日志头+JSON" / "JSON" / "KV" ...）
        feature_field: 业务分类字段名
        
    Returns:
        结构化指纹字符串
    """
    fd = format_detail or classify_result.get("format_detail", "") or classify_result.get("log_format", "")
    ff = feature_field or classify_result.get("feature_field", "")
    fi = classify_result.get("feature_identifier", "")
    
    # 归一化 feature_identifier：去掉尾部精确值捕获组，保留结构骨架
    # 策略：提取 Group 1 部分（去掉日志头后的主体），保留其正则结构
    fi_clean = _normalize_feature_identifier(fi)
    
    return f"{fd}|{ff}|{fi_clean}"


def _normalize_feature_identifier(feature_identifier: str) -> str:
    """
    归一化 feature_identifier，去除值相关的精确匹配，保留结构骨架。
    
    处理步骤：
    1. 将 Group 2（字段值捕获组）内容泛化
    2. 统一转义字符为小写
    3. 统一空格
    
    Args:
        feature_identifier: 双捕获组正则表达式
        
    Returns:
        归一化后的正则骨架
    """
    if not feature_identifier:
        return ""
    
    fi = feature_identifier.strip()
    
    # 将大写的转义符统一为小写
    fi = _re.sub(r'\\([SWDNswdn])', lambda m: f'\\{m.group(1).lower()}', fi)
    
    # 将捕获组中的精确字符串值泛化（如 "dac_dga_log" → "[^\"]*"）
    # 匹配捕获组内的字面量字符串
    fi = _re.sub(r'"([^"\\]*(?:\\.[^"\\]*)*)"', r'"[^"]*"', fi)
    
    # 标准化空白（去掉多余空格）
    fi = _re.sub(r'\s+', '', fi)
    
    return fi


# ============================================================================
# SQLite 存储
# ============================================================================


def _get_connection() -> sqlite3.Connection:
    """获取数据库连接，自动建表"""
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS log_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint TEXT NOT NULL,
            format TEXT NOT NULL,
            meta_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            use_count INTEGER NOT NULL DEFAULT 0,
            last_used_at TEXT
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_fingerprint 
        ON log_patterns(fingerprint)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pattern_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_id INTEGER NOT NULL,
            sample_log TEXT NOT NULL,
            FOREIGN KEY (pattern_id) REFERENCES log_patterns(id)
        )
    """)
    conn.commit()
    return conn


def store_log_knowledge(
    fingerprint: str,
    format_type: str,
    meta: dict,
    sample_logs: list[str] | None = None,
    embedding: np.ndarray | None = None,
) -> int | None:
    """
    存储日志模式到知识库。

    Args:
        fingerprint: 脱敏指纹
        format_type: 格式类型 (json/kv/space/semicolon/comma)
        meta: 分类元数据 (classify_log_features 结果)
        sample_logs: 样例日志行
        embedding: 指纹的 embedding 向量 (1,D)

    Returns:
        插入的 pattern_id，失败返回 None
    """
    try:
        conn = _get_connection()
        meta_json = json.dumps(meta, ensure_ascii=False)

        # 使用 INSERT OR REPLACE 处理重复指纹
        conn.execute(
            """
            INSERT INTO log_patterns (fingerprint, format, meta_json, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(fingerprint) DO UPDATE SET
                meta_json = excluded.meta_json,
                updated_at = excluded.updated_at,
                use_count = use_count
            """,
            (fingerprint, format_type, meta_json),
        )
        conn.commit()

        # 获取 pattern_id
        row = conn.execute(
            "SELECT id FROM log_patterns WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if not row:
            logger.warning("[STORE] 插入后查询失败")
            return None

        pattern_id = row[0]

        # 更新样例日志
        if sample_logs:
            conn.execute(
                "DELETE FROM pattern_samples WHERE pattern_id = ?",
                (pattern_id,),
            )
            for sample in sample_logs[:10]:
                conn.execute(
                    "INSERT INTO pattern_samples (pattern_id, sample_log) VALUES (?, ?)",
                    (pattern_id, sample),
                )
            conn.commit()

        # 更新 embedding
        if embedding is not None:
            _update_embeddings_file(pattern_id, fingerprint, embedding)

        logger.info(f"[STORE] 存储模式 id={pattern_id}, fingerprint={fingerprint[:80]}...")
        return pattern_id

    except Exception as e:
        logger.error(f"[STORE] 存储失败: {type(e).__name__}: {e}")
        return None


def _update_embeddings_file(
    pattern_id: int, fingerprint: str, embedding: np.ndarray
) -> None:
    """更新 embedding 文件，按 pattern_id 索引"""
    # 简单策略：保存 id→fingerprint 映射的 JSON + all embeddings numpy
    meta: dict[int, str] = {}
    if _META_PATH.exists():
        try:
            meta = json.loads(_META_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            meta = {}

    all_embeddings: np.ndarray | None = None
    if _EMBEDDING_PATH.exists():
        try:
            all_embeddings = np.load(str(_EMBEDDING_PATH))
        except (ValueError, OSError):
            all_embeddings = None

    # 确保 embedding 是 2D
    emb = embedding.reshape(1, -1)

    if all_embeddings is None:
        all_embeddings = emb
    else:
        # 检查是否已有此 pattern_id 的条目
        str_id = str(pattern_id)
        if str_id in meta:
            # 替换对应行
            old_index = int(str_id)
            if old_index < all_embeddings.shape[0]:
                all_embeddings[old_index] = emb[0]
        else:
            all_embeddings = np.vstack([all_embeddings, emb])

    # 更新 meta 映射
    meta[str(pattern_id)] = fingerprint

    np.save(str(_EMBEDDING_PATH), all_embeddings)
    _META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================================
# 检索与自动匹配
# ============================================================================


def retrieve_log_knowledge(
    query_text: str,
    top_k: int = 5,
    threshold: float = MATCH_THRESHOLD,
) -> list[dict]:
    """
    根据查询文本检索最相似的日志模式。

    Args:
        query_text: 查询文本 (日志行或指纹)
        top_k: 返回最大结果数
        threshold: 相似度阈值

    Returns:
        [{"pattern_id": 1, "fingerprint": "...", "similarity": 0.95, "meta": {...}}, ...]
    """
    if not _EMBEDDING_PATH.exists():
        logger.info("[RETRIEVE] embedding 文件不存在，返回空")
        return []

    try:
        embeddings = np.load(str(_EMBEDDING_PATH))
        meta = json.loads(_META_PATH.read_text(encoding="utf-8"))

        if embeddings.shape[0] == 0:
            return []

        # 生成查询 embedding
        query_vec = _call_embedding_api([query_text])
        if query_vec is None:
            logger.warning("[RETRIEVE] embedding API 调用失败")
            return []

        # 计算相似度
        similarities = _cosine_similarity(query_vec, embeddings).flatten()

        # 取 top_k
        top_indices = np.argsort(-similarities)[:top_k]

        results: list[dict] = []
        conn = _get_connection()

        for idx in top_indices:
            sim = float(similarities[idx])
            if sim < threshold:
                break

            pattern_id = int(list(meta.keys())[idx]) if idx < len(meta) else None
            if pattern_id is None:
                continue

            # 从 DB 读取元数据
            row = conn.execute(
                "SELECT fingerprint, format, meta_json FROM log_patterns WHERE id = ?",
                (pattern_id,),
            ).fetchone()

            if row:
                results.append({
                    "pattern_id": pattern_id,
                    "fingerprint": row[0],
                    "similarity": round(sim, 4),
                    "format": row[1],
                    "meta": json.loads(row[2]) if row[2] else {},
                })

                # 更新使用计数
                conn.execute(
                    """
                    UPDATE log_patterns 
                    SET use_count = use_count + 1, last_used_at = datetime('now')
                    WHERE id = ?
                    """,
                    (pattern_id,),
                )
                conn.commit()

        return results

    except Exception as e:
        logger.error(f"[RETRIEVE] 检索异常: {type(e).__name__}: {e}")
        return []


def auto_match_log(logs_str: str, sample_size: int = 3) -> dict | None:
    """
    自动匹配日志模式：采样 → 指纹 → 检索 → 返回最佳匹配。

    Args:
        logs_str: 原始日志字符串
        sample_size: 采样行数

    Returns:
        匹配的模式 dict 或 None (无匹配)
    """
    if not logs_str or not logs_str.strip():
        return None

    lines = [l for l in logs_str.strip().split("\n") if l.strip()]
    if not lines:
        return None

    # 采样并生成指纹
    sampled = lines[:sample_size]
    fingerprints = [generate_log_fingerprint(line) for line in sampled]

    # 合并指纹用于检索
    query = " | ".join(fingerprints)

    results = retrieve_log_knowledge(query, top_k=1, threshold=MATCH_THRESHOLD)
    if results:
        logger.info(f"[AUTO_MATCH] 匹配成功, similarity={results[0]['similarity']}")
        return results[0]
    else:
        logger.info("[AUTO_MATCH] 无匹配")
        return None


# ============================================================================
# 增量更新
# ============================================================================


def update_log_pattern(
    pattern_id: int,
    meta: dict | None = None,
    sample_logs: list[str] | None = None,
) -> bool:
    """
    增量更新已有日志模式的元数据和样例。

    Args:
        pattern_id: 模式 ID
        meta: 更新的元数据部分 (合并)
        sample_logs: 更新的样例日志 (替换)

    Returns:
        是否成功
    """
    try:
        conn = _get_connection()

        if meta is not None:
            conn.execute(
                """
                UPDATE log_patterns 
                SET meta_json = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (json.dumps(meta, ensure_ascii=False), pattern_id),
            )

        if sample_logs is not None:
            conn.execute(
                "DELETE FROM pattern_samples WHERE pattern_id = ?",
                (pattern_id,),
            )
            for sample in sample_logs[:10]:
                conn.execute(
                    "INSERT INTO pattern_samples (pattern_id, sample_log) VALUES (?, ?)",
                    (pattern_id, sample),
                )

        conn.commit()
        return True

    except Exception as e:
        logger.error(f"[UPDATE] 更新失败: {type(e).__name__}: {e}")
        return False


def list_all_patterns() -> list[dict]:
    """列出所有已存储的日志模式（概要）"""
    try:
        conn = _get_connection()
        rows = conn.execute(
            """
            SELECT id, fingerprint, format, use_count, created_at, last_used_at
            FROM log_patterns
            ORDER BY use_count DESC, updated_at DESC
            """
        ).fetchall()

        return [
            {
                "pattern_id": row[0],
                "fingerprint": row[1],
                "format": row[2],
                "use_count": row[3],
                "created_at": row[4],
                "last_used_at": row[5],
            }
            for row in rows
        ]
    except Exception as e:
        logger.error(f"[LIST] 列表查询失败: {type(e).__name__}: {e}")
        return []


def delete_pattern(pattern_id: int) -> bool:
    """删除指定日志模式"""
    try:
        conn = _get_connection()
        conn.execute("DELETE FROM log_patterns WHERE id = ?", (pattern_id,))
        conn.execute("DELETE FROM pattern_samples WHERE pattern_id = ?", (pattern_id,))
        conn.commit()
        logger.info(f"[DELETE] 删除模式 id={pattern_id}")
        return True
    except Exception as e:
        logger.error(f"[DELETE] 删除失败: {type(e).__name__}: {e}")
        return False