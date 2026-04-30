"""
标准字段语义检索器 — 基于 SiliconFlow Embedding API

组件：
- FieldRetriever: 管理 embedding 缓存（磁盘持久化）
- batch_retrieve_candidates(): 运行时批量语义检索

语义检索链路：
  标准字段表 (654行) → 复合文本 → SiliconFlow Embedding API → numpy (.npy) + records (.json) 缓存
  用户字段列表 → 批量 Embedding API → 矩阵乘法余弦相似度 → top-K 紧凑候选

依赖项：numpy（版本 >= 1.21），SiliconFlow API Key（环境变量）
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

import numpy as np

from agent.shared.logger import get_logger

logger = get_logger("field_retriever")

# Embedding 模型配置
EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_DIM = 1024
EMBEDDING_API_URL = "https://api.siliconflow.cn/v1/embeddings"
EMBEDDING_BATCH_SIZE = 100  # 每次 API 调用最多嵌入 100 个文本
EMBEDDING_TIMEOUT = 10.0  # 单次 API 调用超时（秒）
EMBEDDING_MAX_RETRIES = 2  # 最多重试次数

# 相似度阈值：低于此值的候选不返回
SIMILARITY_THRESHOLD = 0.25

# 缓存文件路径
_STANDARD_FIELDS_PATH = Path(__file__).parent.parent / "data" / "标准字段.txt"
_CACHE_EMBEDDINGS_PATH = Path(__file__).parent.parent / "data" / "标准字段_embeddings.npy"
_CACHE_RECORDS_PATH = Path(__file__).parent.parent / "data" / "标准字段_records.json"


def _load_standard_fields() -> list[dict]:
    """
    加载标准字段表，返回结构化的条目列表。

    标准字段表格式（TSV, 头行有）：
      系统属性名称\t属性分类\t字段名称\t属性类型\t描述\t枚举值\t对象

    返回 list[dict]，每个 dict 包含所有列及复合文本字段 _composite_text。
    """
    header: Optional[list[str]] = None
    records: list[dict] = []

    raw = _STANDARD_FIELDS_PATH.read_text(encoding="utf-8")
    lines = raw.strip().split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue
        cols = [c.strip() for c in line.split("\t")]
        if header is None:
            # 去除首列 BOM 字符
            if cols:
                cols[0] = cols[0].lstrip("\ufeff")
            header = cols
            continue
        # 补齐列数（某些行末尾可能缺列）
        if len(cols) < len(header):
            cols.extend([""] * (len(header) - len(cols)))
        entry = dict(zip(header, cols[:len(header)]))
        # 构造复合文本：包含所有维度用于 semantic matching
        system_name = entry.get("系统属性名称", "")
        field_name = entry.get("字段名称", "")
        description = entry.get("描述", "")
        obj = entry.get("对象", "")
        data_type = entry.get("属性类型", "")
        entry["_composite_text"] = f"{system_name} ({field_name})：{description}，对象：{obj}，数据类型：{data_type}"
        records.append(entry)

    return records


def _get_api_key() -> Optional[str]:
    """获取 SiliconFlow API Key，先从环境变量，优先生效的 Key"""
    primary = os.getenv("SILICONFLOW_API_KEY", "")
    if primary:
        return primary
    return os.getenv("FALLBACK_API_KEY", "") or None


def _call_embedding_api(texts: list[str], retries: int = EMBEDDING_MAX_RETRIES) -> Optional[np.ndarray]:
    """
    调用 SiliconFlow Embedding API，返回 (N, 1024) 的 numpy 数组。

    Args:
        texts: 待嵌入的文本列表
        retries: 剩余重试次数

    Returns:
        numpy 数组 or None（API 调用失败）
    """
    import requests

    api_key = _get_api_key()
    if not api_key:
        logger.warning("[EMBEDDING] 未设置 SILICONFLOW_API_KEY，跳过 embedding")
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": EMBEDDING_MODEL,
        "input": texts,
        "encoding_format": "float",
    }

    for attempt in range(retries + 1):
        try:
            response = requests.post(
                EMBEDDING_API_URL,
                headers=headers,
                json=payload,
                timeout=EMBEDDING_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            # API 返回格式：{"data": [{"index": 0, "embedding": [...]}, ...]}
            embeddings = sorted(data["data"], key=lambda x: x["index"])
            vectors = np.array([item["embedding"] for item in embeddings], dtype=np.float32)
            logger.info(f"[EMBEDDING] API 成功：{len(texts)} 个文本 → ({vectors.shape[0]}, {vectors.shape[1]})")
            return vectors
        except requests.exceptions.Timeout:
            logger.warning(f"[EMBEDDING] 超时 (第 {attempt + 1}/{retries + 1} 次)")
        except requests.exceptions.RequestException as e:
            logger.warning(f"[EMBEDDING] 请求失败 (第 {attempt + 1}/{retries + 1} 次): {e}")
        except (KeyError, IndexError, ValueError) as e:
            logger.warning(f"[EMBEDDING] 响应解析失败 (第 {attempt + 1}/{retries + 1} 次): {e}")

        if attempt < retries:
            backoff = 2 ** attempt  # 1s, 2s
            time.sleep(backoff)

    logger.error(f"[EMBEDDING] API 调用全部失败，已重试 {retries} 次")
    return None


def _cosine_similarity(query_vec: np.ndarray, corpus_mat: np.ndarray) -> np.ndarray:
    """
    计算余弦相似度（矩阵乘法优化）。

    Args:
        query_vec: (D,) 查询向量
        corpus_mat: (N, D) 语料矩阵，行已是 L2 归一化的

    Returns:
        (N,) 相似度数组
    """
    # corpus_mat 每行已经是单位向量，直接点积即为余弦相似度
    return np.dot(corpus_mat, query_vec)


def _build_cache(texts: list[str], records: list[dict]) -> None:
    """
    构建并持久化 embedding 缓存。

    Args:
        texts: 标准字段的复合文本列表
        records: 标准字段原始记录列表
    """
    vectors = _call_embedding_api(texts)
    if vectors is None:
        return

    # 对语料矩阵作 L2 归一化（方便后续快速余弦相似度计算）
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-10)  # 防除零
    normalized = vectors / norms

    np.save(str(_CACHE_EMBEDDINGS_PATH), normalized)
    _CACHE_RECORDS_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"[CACHE] Embedding 缓存已保存：{len(records)} 条记录，维度 {normalized.shape[1]}")


def init_field_cache(force_refresh: bool = False) -> bool:
    """
    初始化标准字段 embedding 缓存。

    如果缓存已存在且 force_refresh=False，直接返回，不做额外工作。
    调用时机：Web 应用启动时（约 50ms，有缓存时）

    Args:
        force_refresh: 强制重新生成缓存（标准字段表更新后调用）

    Returns:
        bool: 缓存是否就绪（可用）
    """
    if not force_refresh and _CACHE_EMBEDDINGS_PATH.exists() and _CACHE_RECORDS_PATH.exists():
        logger.info("[CACHE] Embedding 缓存已存在，跳过初始化")
        return True

    # 检查 API Key
    if not _get_api_key():
        logger.warning("[CACHE] 无 API Key，无法生成 embedding 缓存")
        return False

    records = _load_standard_fields()
    if not records:
        logger.warning("[CACHE] 标准字段表为空")
        return False

    texts = [r["_composite_text"] for r in records]
    _build_cache(texts, records)

    # 验证缓存已写入
    cache_ready = _CACHE_EMBEDDINGS_PATH.exists() and _CACHE_RECORDS_PATH.exists()
    if cache_ready:
        logger.info(f"[CACHE] Embedding 缓存初始化成功：{len(records)} 条")
    else:
        logger.warning("[CACHE] Embedding 缓存写入失败")
    return cache_ready


def _load_cache() -> tuple[Optional[np.ndarray], Optional[list[dict]]]:
    """
    加载磁盘缓存。

    Returns:
        (embeddings_matrix, records_list) 或 (None, None) 如果缓存损坏
    """
    try:
        if not _CACHE_EMBEDDINGS_PATH.exists() or not _CACHE_RECORDS_PATH.exists():
            return None, None
        embeddings = np.load(str(_CACHE_EMBEDDINGS_PATH))
        records = json.loads(_CACHE_RECORDS_PATH.read_text(encoding="utf-8"))
        return embeddings, records
    except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError) as e:
        logger.warning(f"[CACHE] 缓存加载失败: {e}")
        return None, None


def batch_retrieve_candidates(raw_field_names: list[str], top_k: int = 3) -> str:
    """
    对一批原始字段名执行语义检索，返回紧凑格式的候选列表。

    整体链路：
    1. 加载磁盘缓存（若不存在则自动初始化）
    2. 对 raw_field_names 批量调用 Embedding API
    3. 矩阵乘法计算余弦相似度：[N_fields, N_records]
    4. 每个字段取 top_k，返回紧凑文本

    Args:
        raw_field_names: 原始字段名列表
        top_k: 每个字段返回的候选数（默认 3）

    Returns:
        紧凑格式字符串，无候选时返回空字符串
    """
    if not raw_field_names:
        return ""

    # 加载缓存，不存在则自动初始化
    embeddings, records = _load_cache()
    if embeddings is None or records is None:
        logger.info("[RETRIEVE] 缓存不存在，尝试自动初始化")
        if not init_field_cache():
            logger.warning("[RETRIEVE] 缓存初始化失败，返回空候选")
            return ""
        embeddings, records = _load_cache()
        if embeddings is None or records is None:
            return ""

    # 批量嵌入用户字段名
    query_vecs = _call_embedding_api(raw_field_names)
    if query_vecs is None:
        return ""

    # L2 归一化查询向量
    norms = np.linalg.norm(query_vecs, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-10)
    query_vecs = query_vecs / norms

    # 矩阵乘法：一次计算所有字段的相似度
    # query_vecs: (N_fields, D), embeddings: (N_records, D)
    # 结果: (N_fields, N_records)
    similarity_matrix = np.dot(query_vecs, embeddings.T)

    lines: list[str] = []
    for i, field_name in enumerate(raw_field_names):
        sims = similarity_matrix[i]

        # 取 top_k（用 argpartition 比 argsort 更快）
        if len(sims) <= top_k:
            top_indices = np.argsort(sims)[::-1]
        else:
            # 分区后取 top_k
            partitioned = np.argpartition(sims, -top_k)[-top_k:]
            top_indices = partitioned[np.argsort(sims[partitioned])[::-1]]

        # 收集候选（相似度 >= 阈值）
        candidates: list[str] = []
        for idx in top_indices:
            sim = float(sims[idx])
            if sim < SIMILARITY_THRESHOLD:
                continue
            rec = records[idx]
            candidates.append(
                f"{rec.get('系统属性名称', '')}({sim:.2f}, {rec.get('字段名称', '')})"
            )

        if candidates:
            lines.append(f"{field_name} → {' | '.join(candidates)}")

    if not lines:
        return ""

    header = f"## 标准字段候选（语义检索 top-{top_k}，按相似度降序）："
    return header + "\n" + "\n".join(lines)