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

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Optional

import numpy as np

from agent.shared.logger import get_logger

logger = get_logger("field_retriever")

# 缓存 schema 版本：标准字段表格式变更时递增，触发自动刷新
CACHE_SCHEMA_VERSION = "1"

# Embedding 模型配置
EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_DIM = 1024
EMBEDDING_API_URL = "https://api.siliconflow.cn/v1/embeddings"
EMBEDDING_BATCH_SIZE = 30  # 每次 API 调用最多嵌入 30 个文本（防 413 Request Entity Too Large）
EMBEDDING_BATCH_SLEEP = 0.3  # 每批请求间隔（秒），防止 API 429 限流
EMBEDDING_TIMEOUT = 10.0  # 单次 API 调用超时（秒）
EMBEDDING_MAX_RETRIES = 2  # 最多重试次数

# 相似度阈值：低于此值的候选不返回
SIMILARITY_THRESHOLD = 0.25
# 单条复合文本的最大字段描述长度（字符），防止超长文本溢出模型上下文
MAX_DESCRIPTION_LENGTH = 200

# 缓存文件路径
_STANDARD_FIELDS_PATH = Path(__file__).parent.parent / "data" / "标准字段.txt"
_CACHE_EMBEDDINGS_PATH = Path(__file__).parent.parent / "data" / "标准字段_embeddings.npy"
_CACHE_RECORDS_PATH = Path(__file__).parent.parent / "data" / "标准字段_records.json"
_CACHE_META_PATH = Path(__file__).parent.parent / "data" / "标准字段_cache_meta.json"


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
        # 截断超长描述，防止 embedding 模型输入溢出
        if len(description) > MAX_DESCRIPTION_LENGTH:
            description = description[:MAX_DESCRIPTION_LENGTH] + "..."
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


def _compute_file_md5(file_path: Path) -> str:
    """
    计算文件的 MD5 哈希值。

    Args:
        file_path: 文件路径

    Returns:
        MD5 十六进制字符串，文件不存在时返回空字符串
    """
    try:
        if not file_path.exists():
            return ""
        content = file_path.read_bytes()
        return hashlib.md5(content).hexdigest()
    except OSError as e:
        logger.warning(f"[META] 计算 MD5 失败 ({file_path}): {e}")
        return ""


def _get_cache_meta() -> Optional[dict]:
    """
    读取缓存元数据 JSON。

    Returns:
        dict 或 None（元数据文件不存在或损坏）
    """
    try:
        if not _CACHE_META_PATH.exists():
            return None
        return json.loads(_CACHE_META_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"[META] 缓存元数据读取失败: {e}")
        return None


def _save_cache_meta(file_md5: str, record_count: int) -> None:
    """
    保存缓存元数据。
    """
    meta = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "standard_fields_md5": file_md5,
        "record_count": record_count,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dim": EMBEDDING_DIM,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _CACHE_META_PATH.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"[META] 缓存元数据已保存: schema={CACHE_SCHEMA_VERSION}, md5={file_md5}")


def _build_cache(texts: list[str], records: list[dict]) -> None:
    """
    构建并持久化 embedding 缓存。

    分批调用 embedding API，每批间隔 EMBEDDING_BATCH_SLEEP 秒防止 429 限流。

    Args:
        texts: 标准字段的复合文本列表
        records: 标准字段原始记录列表
    """
    # 确保 data 目录存在（跨平台兼容）
    _CACHE_EMBEDDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

    # 分批嵌入，每批后休眠
    all_vectors: list[np.ndarray] = []
    for batch_start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[batch_start:batch_start + EMBEDDING_BATCH_SIZE]
        vectors = _call_embedding_api(batch)
        if vectors is None:
            logger.error(f"[CACHE] 第 {batch_start // EMBEDDING_BATCH_SIZE + 1} 批 embedding 失败，中断构建")
            return
        all_vectors.append(vectors)
        # 批次间休眠，防止 API 429 限流（最后一批不睡）
        if batch_start + EMBEDDING_BATCH_SIZE < len(texts):
            time.sleep(EMBEDDING_BATCH_SLEEP)

    if not all_vectors:
        return

    # 拼接所有批次
    concatenated = np.concatenate(all_vectors, axis=0)

    # 对语料矩阵作 L2 归一化（方便后续快速余弦相似度计算）
    norms = np.linalg.norm(concatenated, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-10)  # 防除零
    normalized = concatenated / norms

    # 持久化
    np.save(str(_CACHE_EMBEDDINGS_PATH), normalized)
    _CACHE_RECORDS_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 保存缓存元数据（含标准字段文件 MD5）
    file_md5 = _compute_file_md5(_STANDARD_FIELDS_PATH)
    _save_cache_meta(file_md5, len(records))

    logger.info(f"[CACHE] Embedding 缓存已保存：{len(records)} 条记录，维度 {normalized.shape[1]}")


def init_field_cache(force_refresh: bool = False) -> bool:
    """
    初始化标准字段 embedding 缓存。

    自动版本/MD5 校验：标准字段表变更时自动触发 force_refresh。
    无缓存或 stale 缓存时调用 SiliconFlow Embedding API 重新生成。
    调用时机：Web 应用启动时（有缓存时 ~50ms，无缓存时 ~2-10s 取决于字段数量）

    Args:
        force_refresh: 强制重新生成缓存（标准字段表更新后调用）

    Returns:
        bool: 缓存是否就绪（可用）
    """
    if not force_refresh and _CACHE_EMBEDDINGS_PATH.exists() and _CACHE_RECORDS_PATH.exists():
        # 检查缓存元数据：schema 版本 + 标准字段文件 MD5 是否匹配
        meta = _get_cache_meta()
        if meta:
            meta_version = meta.get("schema_version", "")
            meta_md5 = meta.get("standard_fields_md5", "")
            current_md5 = _compute_file_md5(_STANDARD_FIELDS_PATH)

            if meta_version == CACHE_SCHEMA_VERSION and meta_md5 == current_md5:
                logger.info("[CACHE] Embedding 缓存已存在且匹配（版本+MD5），跳过初始化")
                return True
            else:
                differ: list[str] = []
                if meta_version != CACHE_SCHEMA_VERSION:
                    differ.append(f"版本: {meta_version} → {CACHE_SCHEMA_VERSION}")
                if meta_md5 != current_md5:
                    differ.append(f"MD5: {meta_md5[:8]}... → {current_md5[:8]}...")
                logger.info(f"[CACHE] 标准字段表已变更 ({', '.join(differ)})，自动触发缓存刷新")
        else:
            logger.info("[CACHE] 缓存元数据缺失，触发缓存刷新")

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


def _normalize_field_name(name: str) -> str:
    """
    将字段名规范化为可比较的形式。

    处理规则：
    1. camelCase → snake_case（destAddress → dest_address）
    2. 转小写
    3. 移除下划线前的连字符（dest-address → dest_address）

    Args:
        name: 原始字段名

    Returns:
        规范化后的字段名
    """
    # 先转连字符为下划线
    name = name.replace("-", "_")
    # camelCase → snake_case：小写字母后跟大写字母 → 插入下划线
    name = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    # 连续大写后跟小写（处理首字母大写缩写如 macOS → mac_os 跳过，只处理全大写序列）
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return name.lower()


def _build_field_name_index(records: list[dict]) -> dict[str, int]:
    """
    构建「规范化字段名 → 记录索引」的精确匹配字典。

    遍历所有标准字段记录，对其「字段名称」列做规范化处理作为 key。

    Args:
        records: 标准字段记录列表

    Returns:
        dict: 规范化字段名 → 在 records 中的索引位置
    """
    index: dict[str, int] = {}
    for i, rec in enumerate(records):
        field_name = rec.get("字段名称", "")
        if field_name:
            key = _normalize_field_name(field_name)
            # 若存在多个记录映射到同一 key，保留第一个（最权威）
            if key not in index:
                index[key] = i
    return index


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


def batch_retrieve_candidates(raw_field_names: list[str], top_k: int = 5) -> str:
    """
    对一批原始字段名执行语义检索，返回紧凑格式的候选列表。

    整体链路：
    1. 加载磁盘缓存（若不存在则自动初始化）
    2. 对 raw_field_names 批量调用 Embedding API
    3. 矩阵乘法计算余弦相似度：[N_fields, N_records]
    4. 每个字段取 top_k，返回紧凑文本

    Args:
        raw_field_names: 原始字段名列表
        top_k: 每个字段返回的候选数（默认 5）

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

    # 构建精确名称匹配索引（用于语义检索兜底前置）
    exact_index = _build_field_name_index(records)

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
        seen_field_keys: set[str] = set()  # 防止精确匹配和语义检索重复

        # Layer 1: 精确名称匹配兜底（置顶）
        normalized_key = _normalize_field_name(field_name)
        exact_idx = exact_index.get(normalized_key)
        if exact_idx is not None:
            rec = records[exact_idx]
            candidates.append(
                f"{rec.get('系统属性名称', '')}(1.00, {rec.get('字段名称', '')})"
            )
            seen_field_keys.add(rec.get('字段名称', ''))

        # Layer 2: 语义检索兜底
        for idx in top_indices:
            rec = records[idx]
            rec_field_name = rec.get('字段名称', '')
            # 跳过已在精确匹配中出现的记录
            if rec_field_name in seen_field_keys:
                continue
            sim = float(sims[idx])
            if sim < SIMILARITY_THRESHOLD:
                continue
            candidates.append(
                f"{rec.get('系统属性名称', '')}({sim:.2f}, {rec_field_name})"
            )
            seen_field_keys.add(rec_field_name)

        if candidates:
            lines.append(f"{field_name} → {' | '.join(candidates)}")

    if not lines:
        return ""

    header = f"## 标准字段候选（语义检索 top-{top_k}，按相似度降序）："
    raw_output = header + "\n" + "\n".join(lines)

    # 转义特殊字符防止污染提示词格式（冒号、方括号、花括号不会破坏 Markdown 但做保守转义）
    for old, new in [
        ("{", "&#123;"),
        ("}", "&#125;"),
        ("[", "&#91;"),
        ("]", "&#93;"),
    ]:
        raw_output = raw_output.replace(old, new)

    return raw_output


def _debug_lookup(keyword: str, top_k: int = 5) -> str:
    """
    运维调试入口：根据关键词在标准字段表中做语义检索，返回人类可读结果。

    仅供终端运维调试使用，不暴露给 Agent LLM（避免 tool call 回流）。

    Args:
        keyword: 查询关键词（如 "srcAddress"）
        top_k: 返回候选数（默认 5）

    Returns:
        紧凑格式的匹配结果字符串，无匹配时返回提示信息
    """
    if not keyword or not keyword.strip():
        return "[DEBUG] 关键词为空"

    _STANDARD_FIELDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not init_field_cache():
        return "[DEBUG] 缓存未就绪，无法执行语义检索"

    return batch_retrieve_candidates([keyword.strip()], top_k=top_k)
