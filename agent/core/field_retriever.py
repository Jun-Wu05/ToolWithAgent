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
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

import numpy as np

try:
    from rank_bm25 import BM25Okapi
    _BM25_AVAILABLE = True
except ImportError:
    _BM25_AVAILABLE = False
    BM25Okapi = None  # type: ignore

from agent.shared.logger import get_logger

logger = get_logger("field_retriever")

# 缓存 schema 版本：标准字段表格式变更时递增，触发自动刷新
CACHE_SCHEMA_VERSION = "2"

# Embedding 模型配置
EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"
EMBEDDING_DIM = 4096
EMBEDDING_API_URL = "https://api.siliconflow.cn/v1/embeddings"
# CHANGED: 调整为更稳健的配置（适配 Qwen3-Embedding-8B 大模型批量推理）
EMBEDDING_BATCH_SIZE = 15  # 每次 API 调用最多嵌入 15 个文本（减半，降低服务端单次负载，防 413）
EMBEDDING_BATCH_SLEEP = 0.3  # 每批请求间隔（秒），防止 API 429 限流（保持不变）
EMBEDDING_TIMEOUT = 30.0  # 单次 API 调用超时（秒）— 8B 模型批量推理需更长时间，原 10s 易误超时
EMBEDDING_MAX_RETRIES = 3  # 最多重试次数（+1 次容错）

# 相似度阈值：低于此值的候选不返回
SIMILARITY_THRESHOLD = 0.15
# 单条复合文本的最大字段描述长度（字符），防止超长文本溢出模型上下文
MAX_DESCRIPTION_LENGTH = 200

# 检索诊断日志开关：设为 True 后，batch_retrieve_candidates 会在 DEBUG 级别
# 逐字段打印候选在「纯向量 → BM25融合 → 候选收集 → token重排序」各阶段的排名轨迹，
# 便于定位候选被压到 top_k 之外的原因。排查完毕可改回 False 关闭。
RETRIEVE_DEBUG_TRACE = True

# 网络协议字段常见缩写 → 全称展开（覆盖所有标准字段，零手动维护）
ABBR_EXPANSIONS: dict[str, str] = {
    "dest": "destination",
    "dst": "destination",
    "src": "source",
    "addr": "address",
    "mac": "mac_address",
    "ip": "ip_address",
    "sip": "source_ip",
    "dip": "destination_ip",
    "dev": "device",
    "host": "host",
    "num": "number",
    "id": "identifier",
    "info": "information",
    "desc": "description",
    "cnt": "count",
    "len": "length",
    "seq": "sequence",
    "ack": "acknowledgement",
    "syn": "synchronize",
    "pkt": "packet",
    "msg": "message",
    "cfg": "configuration",
    "max": "maximum",
    "min": "minimum",
    "avg": "average",
    "total": "total",
    "list": "list",
    "type": "type",
    "name": "name",
    "code": "code",
    "flag": "flag",
    "port": "port",
    "proto": "protocol",
    "ver": "version",
    "uri": "uri",
    "url": "url",
    "svc": "service",
    "loc": "location",
    "prov": "province",
    "cty": "city",
    "cntry": "country",
    "grp": "group",
    "usr": "user",
    "pwd": "password",
    "tgt": "target",
    "ref": "reference",
    "orig": "origin",
    "sub": "sub",
    "pub": "public",
    "priv": "private",
    "ext": "external",
    "int": "internal",
    "nat": "network_address_translation",
    "dns": "domain_name_system",
    "dhcp": "dynamic_host_configuration_protocol",
    "http": "hypertext_transfer_protocol",
    "https": "hypertext_transfer_protocol_secure",
    "ftp": "file_transfer_protocol",
    "smtp": "simple_mail_transfer_protocol",
    "tcp": "transmission_control_protocol",
    "udp": "user_datagram_protocol",
    "icmp": "internet_control_message_protocol",
    "arp": "address_resolution_protocol",
    "vlan": "virtual_local_area_network",
    "vpn": "virtual_private_network",
    "os": "operating_system",
    "hw": "hardware",
    "sw": "software",
    "fw": "firewall",
}

# 缓存文件路径
_STANDARD_FIELDS_PATH = Path(__file__).parent.parent.parent / "config" / "标准字段.txt"
_CACHE_EMBEDDINGS_PATH = Path(__file__).parent.parent.parent / "config" / "标准字段_embeddings.npy"
_CACHE_RECORDS_PATH = Path(__file__).parent.parent.parent / "config" / "标准字段_records.json"
_CACHE_META_PATH = Path(__file__).parent.parent.parent / "config" / "标准字段_cache_meta.json"

# BM25 混合检索状态（懒加载）
_BM25_INDEX = None  # type: ignore[valid-type]
_BM25_RECORDS: Optional[list[dict]] = None
_BM25_INIT_ATTEMPTED: bool = False


def _init_bm25_index() -> bool:
    """
    懒加载 BM25 关键词检索索引。

    基于标准字段记录的「字段名称 + 系统属性名称」（展开缩写后）构建。
    只在 rank_bm25 可用且缓存已加载时初始化。

    Returns:
        bool: BM25 索引是否就绪
    """
    global _BM25_INDEX, _BM25_RECORDS, _BM25_INIT_ATTEMPTED
    if _BM25_INDEX is not None:
        return True
    if _BM25_INIT_ATTEMPTED:
        return False
    _BM25_INIT_ATTEMPTED = True

    if not _BM25_AVAILABLE:
        logger.info("[BM25] rank_bm25 未安装，降级为纯向量检索")
        return False

    # 加载缓存确保 records 可用
    _emb, records = _load_cache()
    if records is None:
        logger.info("[BM25] 缓存未就绪，无法构建 BM25 索引")
        return False

    # 构建语料：每条记录的展开 token 序列
    corpus: list[list[str]] = []
    for rec in records:
        field_name = rec.get('字段名称', '')
        sys_name = rec.get('系统属性名称', '')
        entry_text = f"{_expand_field_name(field_name)} {_expand_field_name(sys_name)}"
        corpus.append(entry_text.split())

    try:
        _BM25_INDEX = BM25Okapi(corpus)
        _BM25_RECORDS = records
        logger.info(f"[BM25] 索引构建成功：{len(records)} 条文档")
        return True
    except Exception as e:
        logger.warning(f"[BM25] 索引构建失败: {e}")
        return False


def _compute_bm25_scores(query_fields: list[str], bm25_index) -> np.ndarray:
    """
    对一批查询字段计算 BM25 分数矩阵。

    Args:
        query_fields: 查询字段名列表
        bm25_index: BM25Okapi 索引实例

    Returns:
        (N_fields, N_docs) 的 float64 矩阵，每行为该查询对全部文档的 BM25 分数
    """
    n_fields = len(query_fields)
    n_docs = bm25_index.corpus_size
    scores = np.zeros((n_fields, n_docs), dtype=np.float64)
    for i, field in enumerate(query_fields):
        query_tokens = _expand_field_name(field).split()
        doc_scores = bm25_index.get_scores(query_tokens)
        scores[i, :] = np.array(doc_scores, dtype=np.float64)
    return scores


def _generate_field_tags(field_name: str) -> list[str]:
    """
    从字段名自动推断元数据标签（纯规则，零 LLM 调用）。

    标签用于嵌入复合文本增强，使拥有相同标签的字段在向量空间中互相靠近。

    Args:
        field_name: 字段名称（英文，如 destAddress, src_ip_list）

    Returns:
        排序后的语义标签列表
    """
    tags: set[str] = set()
    name_lower = _normalize_field_name(field_name)

    # --- 方向标签 ---
    if any(x in name_lower for x in ("src", "source")):
        tags.update(("source", "network"))
    if any(x in name_lower for x in ("dst", "dest", "destination")):
        tags.update(("destination", "network"))

    # --- 语义类型标签 ---
    if any(x in name_lower for x in ("address", "addr", "ip", "sip", "dip")):
        tags.add("address")
    if "port" in name_lower:
        tags.add("port")
    if "mac" in name_lower:
        tags.add("mac_address")
    if any(x in name_lower for x in ("time", "timestamp", "date", "duration", "ttl")):
        tags.add("time")
    if any(x in name_lower for x in ("name", "label", "title")):
        tags.add("name")
    if any(x in name_lower for x in ("id", "identifier", "guid", "uuid", "xid")):
        tags.add("identifier")
    if any(x in name_lower for x in ("type", "category", "class", "code", "opcode", "op")):
        tags.add("type")
    if any(x in name_lower for x in ("count", "number", "size", "len", "length", "num",
                                       "total", "cnt")):
        tags.add("numeric")
    if any(x in name_lower for x in ("status", "state", "flag")):
        tags.add("status")
    if any(x in name_lower for x in ("version", "ver")):
        tags.add("version")
    if any(x in name_lower for x in ("hash", "md5", "sha", "checksum")):
        tags.add("hash")
    if any(x in name_lower for x in ("path", "directory", "dir", "folder")):
        tags.add("path")
    if any(x in name_lower for x in ("protocol", "proto")):
        tags.add("protocol")
    if any(x in name_lower for x in ("dns", "dhcp", "http", "ftp", "smtp", "tcp", "udp",
                                       "icmp", "arp", "ssh", "tls", "ssl")):
        tags.add("protocol")
    if any(x in name_lower for x in ("list", "items", "entries")):
        tags.add("collection")

    return sorted(tags)


def _expand_field_name(field_name: str) -> str:
    """将缩写字段名展开为全英文描述，例如 destAddress → destination address"""
    # camelCase/pascalCase → snake_case 拆分（与 _normalize_field_name 一致）
    name = field_name.replace("-", "_")
    name = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    tokens = name.split("_")
    expanded = [ABBR_EXPANSIONS.get(t.lower(), t) for t in tokens]
    return " ".join(expanded)


def _get_field_name_tokens(field_name: str) -> set[str]:
    """将字段名拆分为展开后的 token 集合，用于候选重排序中的 token 重叠计算。"""
    return set(_expand_field_name(field_name).split())


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
        english_expanded = _expand_field_name(field_name)
        field_tags = _generate_field_tags(field_name)
        tag_text = f"[TAGS:{' '.join(field_tags)}]" if field_tags else ""
        entry["_composite_text"] = f"{english_expanded} {tag_text} || {system_name} | {field_name} | {obj} | {data_type} | {description}"
        entry["_tags"] = field_tags
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


def _build_query_text_for_embedding(field_name: str) -> str:
    """
    为 Embedding API 查询构建带标签的增强输入文本。

    使查询端与索引端使用相同的标签格式，
    BGE-m3 可将拥有相同标签的查询与候选字段在向量空间中拉近。

    Args:
        field_name: 原始字段名（如 destAddress, src_ip_list）

    Returns:
        带标签的文本，供 Embedding API 编码
    """
    tags = _generate_field_tags(field_name)
    expanded = _expand_field_name(field_name)
    if tags:
        return f"{expanded} [TAGS:{' '.join(tags)}]"
    return expanded


def _strip_field_prefix(name: str) -> list[str]:
    """
    对嵌套字段名（如 data.severity, original_log_1.origin.sip）生成去前缀变体。

    规则：
    - 去掉最外层前缀（data.xxx → xxx）
    - 再去掉一层前缀（data.origin.sip → origin.sip, sip）

    返回按优先级排列的无前缀变体列表（不含原 name）。
    """
    variants: list[str] = []
    parts = name.split(".")
    if len(parts) <= 1:
        return variants
    # 去掉第一层
    variants.append(".".join(parts[1:]))
    # 去掉前两层（如果还有足够深度）
    if len(parts) > 2:
        variants.append(".".join(parts[2:]))
    return variants


def _format_top_n(sims_row: Optional[np.ndarray], records: list[dict], n: int = 5) -> str:
    """将一行相似度向量格式化为 "名(分数) | 名(分数) ..." 的 top-N 文本（诊断用）。"""
    if sims_row is None:
        return "(未启用诊断)"
    k = min(n, len(sims_row))
    top = np.argsort(sims_row)[::-1][:k]
    return " | ".join(
        f"{records[idx].get('系统属性名称', '')}({float(sims_row[idx]):.2f})" for idx in top
    )


def _log_retrieve_trace(
    field_name: str,
    i: int,
    pure_vector_matrix: Optional[np.ndarray],
    similarity_matrix: np.ndarray,
    candidates_tmp: list[tuple[str, str, float]],
    candidates: list[str],
    records: list[dict],
) -> None:
    """打印单个字段检索各阶段候选排名的诊断日志（DEBUG 级别）。

    阶段说明：
    - 阶段1 纯向量：embedding 余弦相似度 top5（BM25 融合前）
    - 阶段2 融合后：BM25 融合后 top5（即喂给 Layer2 的 sims）
    - 阶段3 收集候选：Layer1/1.5/2/2.5 汇总的候选（含精确匹配与去前缀变体）
    - 阶段4 重排序后：token 重排序后的最终输出（即注入 LLM 的候选）
    """
    stage1 = _format_top_n(pure_vector_matrix[i] if pure_vector_matrix is not None else None, records)
    stage2 = _format_top_n(similarity_matrix[i], records)
    stage3 = " | ".join(fmt for fmt, _, _ in candidates_tmp) or "(空)"
    stage4 = " | ".join(candidates) or "(空-被阈值过滤/重排序丢弃)"
    logger.debug(
        f"[TRACE] '{field_name}'\n"
        f"  阶段1 纯向量top5 : {stage1}\n"
        f"  阶段2 BM25融合后 : {stage2}\n"
        f"  阶段3 收集候选({len(candidates_tmp)}): {stage3}\n"
        f"  阶段4 重排序输出 : {stage4}"
    )


def batch_retrieve_candidates(raw_field_names: list[str], top_k: int = 6) -> str:
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

    # 批量嵌入用户字段名 — 按 EMBEDDING_BATCH_SIZE 分批，防止 413 Request Entity Too Large
    all_vectors: list[np.ndarray] = []
    for batch_start in range(0, len(raw_field_names), EMBEDDING_BATCH_SIZE):
        batch_raw = raw_field_names[batch_start:batch_start + EMBEDDING_BATCH_SIZE]
        batch_tagged = [_build_query_text_for_embedding(n) for n in batch_raw]
        vectors = _call_embedding_api(batch_tagged)
        if vectors is None:
            raise RuntimeError(
                f"[EMBEDDING] 语义检索失败（第 {batch_start // EMBEDDING_BATCH_SIZE + 1} 批），"
                f"共 {len(raw_field_names)} 个字段，批次大小 {EMBEDDING_BATCH_SIZE}"
            )
        all_vectors.append(vectors)
        # 批次间休眠，防止 API 429 限流（最后一批不睡）
        if batch_start + EMBEDDING_BATCH_SIZE < len(raw_field_names):
            time.sleep(EMBEDDING_BATCH_SLEEP)
    query_vecs = np.concatenate(all_vectors, axis=0)

    # L2 归一化查询向量
    norms = np.linalg.norm(query_vecs, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-10)
    query_vecs = query_vecs / norms

    # 矩阵乘法：一次计算所有字段的相似度
    # query_vecs: (N_fields, D), embeddings: (N_records, D)
    # 结果: (N_fields, N_records)
    similarity_matrix = np.dot(query_vecs, embeddings.T)

    # 保存纯向量相似度副本，供诊断日志对比 BM25 融合前后的排名变化
    pure_vector_matrix = similarity_matrix.copy() if RETRIEVE_DEBUG_TRACE else None

    # BM25 混合检索：在纯向量相似度基础上融合关键词匹配分数
    # 权重分配：向量 70%，BM25 30%（当 BM25 索引就绪时）
    bm25_weight: float = 0.3
    if _init_bm25_index() and _BM25_INDEX is not None:
        try:
            bm25_scores = _compute_bm25_scores(raw_field_names, _BM25_INDEX)
            # 对 BM25 分数做 min-max 归一化至 [0, 1]
            bm25_min = bm25_scores.min(axis=1, keepdims=True)
            bm25_max = bm25_scores.max(axis=1, keepdims=True)
            bm25_range = np.maximum(bm25_max - bm25_min, 1e-10)
            bm25_norm = (bm25_scores - bm25_min) / bm25_range
            # 融合：向量相似度 * (1-w) + BM25 归一化分数 * w
            similarity_matrix = similarity_matrix * (1.0 - bm25_weight) + bm25_norm * bm25_weight
            logger.info(f"[BM25] 混合检索已融合：bm25_weight={bm25_weight}，{len(raw_field_names)} 个查询字段")
        except Exception as e:
            logger.warning(f"[BM25] 混合融合失败，降级为纯向量检索: {e}")
    else:
        logger.info("[BM25] 跳过混合检索（索引未就绪）")

    # 构建精确名称匹配索引（用于语义检索兜底前置）
    exact_index = _build_field_name_index(records)

    # 为嵌套字段（含 . ）收集去前缀变体，统一做一次额外 Embedding
    stripped_fields_map: dict[int, list[str]] = {}  # 原始索引 → 变体字段名列表
    stripped_variants: list[str] = []                # 顺序变体列表
    stripped_to_original: dict[int, int] = {}        # 变体在 stripped_variants 中的索引 → 原始字段索引
    for i, name in enumerate(raw_field_names):
        variants = _strip_field_prefix(name)
        if variants:
            stripped_fields_map[i] = variants
            for v in variants:
                stripped_to_original[len(stripped_variants)] = i
                stripped_variants.append(v)

    # 批量嵌入去前缀变体
    stripped_vecs: Optional[np.ndarray] = None
    if stripped_variants:
        try:
            stripped_vecs_list: list[np.ndarray] = []
            for bs in range(0, len(stripped_variants), EMBEDDING_BATCH_SIZE):
                batch_raw = stripped_variants[bs:bs + EMBEDDING_BATCH_SIZE]
                batch_tagged = [_build_query_text_for_embedding(v) for v in batch_raw]
                vecs = _call_embedding_api(batch_tagged)
                if vecs is None:
                    raise RuntimeError(f"[EMBEDDING] 去前缀变体嵌入失败（第 {bs // EMBEDDING_BATCH_SIZE + 1} 批）")
                stripped_vecs_list.append(vecs)
                if bs + EMBEDDING_BATCH_SIZE < len(stripped_variants):
                    time.sleep(EMBEDDING_BATCH_SLEEP)
            stripped_vecs = np.concatenate(stripped_vecs_list, axis=0)
            # L2 归一化
            norms_s = np.linalg.norm(stripped_vecs, axis=1, keepdims=True)
            norms_s = np.maximum(norms_s, 1e-10)
            stripped_vecs = stripped_vecs / norms_s
            # 计算去前缀变体的相似度矩阵
            stripped_sim_matrix = np.dot(stripped_vecs, embeddings.T)
        except RuntimeError as e:
            logger.warning(f"[RETRIEVE] 去前缀变体嵌入失败，跳过: {e}")
            stripped_variants.clear()

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

        # 收集候选（相似度 >= 阈值）— 暂存为 (formatted_str, field_name, sim_score) 元组
        candidates_tmp: list[tuple[str, str, float]] = []
        seen_field_keys: set[str] = set()  # 防止精确匹配和语义检索重复

        # Layer 1: 精确名称匹配兜底（置顶）— 先试原始字段名
        normalized_key = _normalize_field_name(field_name)
        exact_idx = exact_index.get(normalized_key)
        if exact_idx is not None:
            rec = records[exact_idx]
            rfn = rec.get('字段名称', '')
            candidates_tmp.append(
                (f"{rec.get('系统属性名称', '')}(1.00, {rfn})", rfn, 1.0)
            )
            seen_field_keys.add(rfn)

        # Layer 1.5: 去前缀变体的精确名称匹配兜底
        if field_name in stripped_fields_map:
            for variant in stripped_fields_map[field_name]:
                v_key = _normalize_field_name(variant)
                v_exact_idx = exact_index.get(v_key)
                if v_exact_idx is not None:
                    v_rec = records[v_exact_idx]
                    v_key_name = v_rec.get('字段名称', '')
                    if v_key_name not in seen_field_keys:
                        candidates_tmp.append(
                            (f"{v_rec.get('系统属性名称', '')}(1.00, {v_key_name}, by_stripped={variant})", v_key_name, 1.0)
                        )
                        seen_field_keys.add(v_key_name)

        # Layer 2: 语义检索兜底（原始字段名）
        for idx in top_indices:
            rec = records[idx]
            rec_field_name = rec.get('字段名称', '')
            # 跳过已在精确匹配中出现的记录
            if rec_field_name in seen_field_keys:
                continue
            sim = float(sims[idx])
            if sim < SIMILARITY_THRESHOLD:
                continue
            candidates_tmp.append(
                (f"{rec.get('系统属性名称', '')}({sim:.2f}, {rec_field_name})", rec_field_name, sim)
            )
            seen_field_keys.add(rec_field_name)

        # Layer 2.5: 去前缀变体的语义检索结果合并
        if stripped_variants and stripped_sim_matrix is not None:
            for v_idx, orig_idx in stripped_to_original.items():
                if orig_idx != i:
                    continue
                v_sims = stripped_sim_matrix[v_idx]
                if len(v_sims) <= top_k:
                    v_top = np.argsort(v_sims)[::-1]
                else:
                    v_partitioned = np.argpartition(v_sims, -top_k)[-top_k:]
                    v_top = v_partitioned[np.argsort(v_sims[v_partitioned])[::-1]]
                for vi in v_top:
                    v_rec = records[vi]
                    v_rfn = v_rec.get('字段名称', '')
                    if v_rfn in seen_field_keys:
                        continue
                    v_sim = float(v_sims[vi])
                    if v_sim < SIMILARITY_THRESHOLD:
                        continue
                    variant_name = stripped_variants[v_idx]
                    candidates_tmp.append(
                        (f"{v_rec.get('系统属性名称', '')}({v_sim:.2f}, {v_rfn}, by_stripped={variant_name})", v_rfn, v_sim)
                    )
                    seen_field_keys.add(v_rfn)

        # Token 重叠重排序：精确匹配优先，其次按展开 token 重叠数降序，再按相似度降序
        source_tokens = _get_field_name_tokens(field_name)
        reranked_rows: list[tuple[int, int, float, str]] = []
        for fmt_str, cand_field, sim in candidates_tmp:
            cand_tokens = _get_field_name_tokens(cand_field)
            overlap = len(source_tokens & cand_tokens)
            tier = 0 if sim >= 0.999 else 1
            reranked_rows.append((tier, -overlap, -sim, fmt_str))
        reranked_rows.sort()
        candidates = [row[3] for row in reranked_rows]

        # 检索诊断：追踪候选在「纯向量 → BM25融合 → 候选收集 → token重排序」各阶段的排名
        if RETRIEVE_DEBUG_TRACE and logger.isEnabledFor(logging.DEBUG):
            _log_retrieve_trace(
                field_name, i, pure_vector_matrix, similarity_matrix,
                candidates_tmp, candidates, records,
            )

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


def _debug_lookup(keyword: str, top_k: int = 6) -> str:
    """
    运维调试入口：根据关键词在标准字段表中做语义检索，返回人类可读结果。

    仅供终端运维调试使用，不暴露给 Agent LLM（避免 tool call 回流）。

    Args:
        keyword: 查询关键词（如 "srcAddress"）
        top_k: 返回候选数（默认 3）

    Returns:
        紧凑格式的匹配结果字符串，无匹配时返回提示信息
    """
    if not keyword or not keyword.strip():
        return "[DEBUG] 关键词为空"

    _STANDARD_FIELDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not init_field_cache():
        return "[DEBUG] 缓存未就绪，无法执行语义检索"

    return batch_retrieve_candidates([keyword.strip()], top_k=top_k)
