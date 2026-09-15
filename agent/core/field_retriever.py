"""
标准字段语义检索器 — 字段展开、候选检索、余弦相似度与重排序

组件：
- FieldRetriever: 管理 embedding 缓存（磁盘持久化）
- batch_retrieve_candidates(): 运行时批量语义检索

语义检索链路：
  标准字段表 (654行) → 复合文本 → 嵌入客户端 → numpy (.npy) + records (.json) 缓存
  用户字段列表 → 嵌入客户端（去重+进程内缓存） → 矩阵乘法余弦相似度 → top-K 紧凑候选

依赖项：numpy（版本 >= 1.21）；嵌入模型/URL/密钥/重试等 HTTP 细节自 #246 起收拢于
agent/core/embedding_client.py，本模块零网络细节。
"""

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

import numpy as np

from agent.core.embedding_client import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    QUERY_EMBEDDING_CACHE,
    call_embedding_api,
    embed_query_texts,
    get_api_key,
    query_cache_key,
)
from agent.core.standard_field_catalog import (
    compact_field_name,
    get_standard_field_catalog,
    normalize_field_name,
)
from agent.shared.logger import get_logger

logger = get_logger("field_retriever")

# 兼容接缝（#246）：以下划线名保留既有 patch/import 入口——
# 现有测试 monkeypatch field_retriever._call_embedding_api / _get_api_key，
# log_pattern_store 仍从本模块导入 _call_embedding_api（收口待 #202 系列协调）。
_call_embedding_api = call_embedding_api
_get_api_key = get_api_key
_QUERY_EMBEDDING_CACHE = QUERY_EMBEDDING_CACHE
_query_cache_key = query_cache_key

# 缓存 schema 版本：标准字段表格式变更时递增，触发自动刷新
CACHE_SCHEMA_VERSION = "4"  # v4: tag_rules 新增 http tag + synonyms_md5 追踪 + 复合 key 回退，需重建缓存

# 相似度阈值：低于此值的候选不返回
SIMILARITY_THRESHOLD = 0.15
# 单条复合文本的最大字段描述长度（字符），防止超长文本溢出模型上下文
MAX_DESCRIPTION_LENGTH = 200

# 检索诊断日志开关：设为 True 后，batch_retrieve_candidates 会在 DEBUG 级别
# 逐字段打印候选在「纯向量 → 候选收集 → token重排序」各阶段的排名轨迹，
# 便于定位候选被压到 top_k 之外的原因。排查完毕可改回 False 关闭。
RETRIEVE_DEBUG_TRACE = True

# 字段同义词表路径（外置配置：缩写→英文全称 + 中文同义词）
_SYNONYMS_PATH = Path(__file__).parent.parent.parent / "config" / "field_synonyms.json"

def _load_synonyms():
    """Compatibility wrapper for Catalog-owned synonym facts."""
    return get_standard_field_catalog().synonyms


# 缓存文件路径
_STANDARD_FIELDS_PATH = Path(__file__).parent.parent.parent / "config" / "标准字段.txt"
_CACHE_EMBEDDINGS_PATH = Path(__file__).parent.parent.parent / "config" / "标准字段_embeddings.npy"
_CACHE_RECORDS_PATH = Path(__file__).parent.parent.parent / "config" / "标准字段_records.json"
_CACHE_META_PATH = Path(__file__).parent.parent.parent / "config" / "标准字段_cache_meta.json"


_TAG_RULES_PATH = Path(__file__).parent.parent.parent / "config" / "tag_rules.json"
def _load_tag_rules():
    """Compatibility wrapper for Catalog-owned deterministic tag rules."""
    return get_standard_field_catalog().tag_rules


def _generate_field_tags(field_name: str) -> list[str]:
    """
    从字段名自动推断元数据标签（纯规则，零 LLM 调用）。

    规则来自外置 tag_rules.json。字段名拆分为 token 后逐个匹配：
    任一 token 命中某标签的关键词集合，即打上该标签。
    token 级匹配可避免子串误匹配（如 'severity' 不再误触发 version）。

    Args:
        field_name: 字段名称（英文，如 destAddress, src_ip_list）

    Returns:
        排序后的语义标签列表
    """
    rules = _load_tag_rules()
    if not rules:
        return []

    # 拆分为小写 token（与 _normalize_field_name 一致的 camelCase 处理）
    name = field_name.replace("-", "_")
    name = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    tokens = set(t.lower() for t in name.split("_"))

    tags: set[str] = set()
    for tag, keywords in rules.items():
        if tokens & set(keywords):
            tags.add(tag)
    return sorted(tags)


def _expand_field_name(field_name: str) -> str:
    """将缩写字段名展开为全英文描述，例如 destAddress → destination address。

    展开规则来自外置同义词表 field_synonyms.json 的 en 字段（替代原硬编码 ABBR_EXPANSIONS）。
    """
    synonyms = _load_synonyms()
    # camelCase/pascalCase → snake_case 拆分（与 _normalize_field_name 一致）
    name = field_name.replace("-", "_")
    name = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    tokens = name.split("_")
    expanded = []
    for t in tokens:
        entry = synonyms.get(t.lower())
        expanded.append(entry["en"] if entry and entry.get("en") else t)
    # 回退查询：整字段名作为复合 key 查 synonyms（如 attack_type/http_url）
    # 修复 133 个带下划线死条目：单 token 查不到时，复合 key 的 en 定义才生效
    full_entry = synonyms.get(name.lower())
    if full_entry and full_entry.get("en"):
        expanded.append(full_entry["en"])
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
    records = get_standard_field_catalog().records()
    for entry in records:
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
    return records


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
    tag_md5 = _compute_file_md5(_TAG_RULES_PATH) if _TAG_RULES_PATH.exists() else ""
    synonyms_md5 = _compute_file_md5(_SYNONYMS_PATH) if _SYNONYMS_PATH.exists() else ""
    meta = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "standard_fields_md5": file_md5,
        "tag_rules_md5": tag_md5,
        "synonyms_md5": synonyms_md5,
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
        # 检查缓存元数据：schema 版本 + 标准字段文件 MD5 + tag规则 MD5 + 同义词表 MD5 + 模型/维度 是否匹配
        meta = _get_cache_meta()
        if meta:
            meta_version = meta.get("schema_version", "")
            meta_md5 = meta.get("standard_fields_md5", "")
            meta_tag_md5 = meta.get("tag_rules_md5", "")
            meta_synonyms_md5 = meta.get("synonyms_md5", "")
            # 向量空间随嵌入模型/维度变化；缺失或漂移时旧向量不可比，必须重建
            meta_model = meta.get("embedding_model", "")
            meta_dim = meta.get("embedding_dim", 0)
            current_md5 = _compute_file_md5(_STANDARD_FIELDS_PATH)
            # tag 规则影响索引端 _composite_text，变更需重建缓存
            current_tag_md5 = _compute_file_md5(_TAG_RULES_PATH) if _TAG_RULES_PATH.exists() else ""
            # synonyms 影响索引端 _composite_text（_expand_field_name 展开），变更需重建缓存
            current_synonyms_md5 = _compute_file_md5(_SYNONYMS_PATH) if _SYNONYMS_PATH.exists() else ""

            if (meta_version == CACHE_SCHEMA_VERSION
                    and meta_md5 == current_md5
                    and meta_tag_md5 == current_tag_md5
                    and meta_synonyms_md5 == current_synonyms_md5
                    and meta_model == EMBEDDING_MODEL
                    and meta_dim == EMBEDDING_DIM):
                logger.info("[CACHE] Embedding 缓存已存在且匹配（版本+MD5+tag规则+同义词+模型+维度），跳过初始化")
                return True
            else:
                differ: list[str] = []
                if meta_version != CACHE_SCHEMA_VERSION:
                    differ.append(f"版本: {meta_version} → {CACHE_SCHEMA_VERSION}")
                if meta_md5 != current_md5:
                    differ.append(f"字段表MD5: {meta_md5[:8]}... → {current_md5[:8]}...")
                if meta_tag_md5 != current_tag_md5:
                    differ.append(f"tag规则MD5: {meta_tag_md5[:8]}... → {current_tag_md5[:8]}...")
                if meta_synonyms_md5 != current_synonyms_md5:
                    differ.append(f"同义词MD5: {meta_synonyms_md5[:8]}... → {current_synonyms_md5[:8]}...")
                if meta_model != EMBEDDING_MODEL:
                    differ.append(f"模型: {meta_model} → {EMBEDDING_MODEL}")
                if meta_dim != EMBEDDING_DIM:
                    differ.append(f"维度: {meta_dim} → {EMBEDDING_DIM}")
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
    return normalize_field_name(name)


def _compact_field_name(name: str) -> str:
    """去除所有分隔符的紧凑形式（file_name → filename）。

    用于精确匹配的二级 key，消除 camelCase 拆分（file_name）与无分隔符命名
    （filename）之间的差异。标准字段表里 filename / file_name / fileName
    会被归一化到同一个紧凑形式，从而在 Layer1 精确匹配时命中。
    """
    return compact_field_name(name)


def _build_field_name_index(records: list[dict]) -> dict[str, int]:
    """
    构建「规范化字段名 → 记录索引」的精确匹配字典。

    遍历所有标准字段记录，对其「字段名称」列做规范化处理作为 key。
    另注册两级中文 key 以修复中文 query 的精确匹配漏网：
    - 中文系统属性名（如「协议」「事件动作」）直接作为 key
    - synonyms.zh 反向索引：synonyms key 恰为某记录字段名称时，
      其 zh 同义词全部注册指向同一记录（如 threat_type.zh 含「攻击类型」）
    中文 query「协议」「攻击类型」原被迫走向量检索被字面相似词压过，
    现可经 Layer1 精确命中 sim=1.0 置顶。

    Args:
        records: 标准字段记录列表

    Returns:
        dict: 规范化字段名 → 在 records 中的索引位置
    """
    return get_standard_field_catalog().build_name_index(records)


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


def _collect_zh_synonyms(field_name: str) -> list[str]:
    """收集字段名各 token 对应的中文同义词（去重，保持顺序）。

    用于在 query 文本中桥接中文标准字段——embedding 模型对中英跨语言对齐能力有限，
    在 query 里补上中文同义词可显著提升对中文系统属性名（如"协议""文件名称"）的召回。
    """
    synonyms = _load_synonyms()
    name = field_name.replace("-", "_")
    name = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    tokens = name.split("_")
    zh_set: list[str] = []
    seen: set[str] = set()
    for t in tokens:
        entry = synonyms.get(t.lower())
        if not entry:
            continue
        for zh in entry.get("zh", []):
            if zh and zh not in seen:
                zh_set.append(zh)
                seen.add(zh)
    # 回退查询：整字段名作为复合 key 查 synonyms（如 attack_type → 威胁类型/攻击类型）
    # 修复复合 key 死条目：单 token 命中不到中文同义词时，复合 key 的 zh 定义才生效
    full_entry = synonyms.get(name.lower())
    if full_entry:
        for zh in full_entry.get("zh", []):
            if zh and zh not in seen:
                zh_set.append(zh)
                seen.add(zh)
    return zh_set


def _build_query_text_for_embedding(field_name: str) -> str:
    """
    为 Embedding API 查询构建带标签与中文同义词的增强输入文本。

    - 标签（[TAGS:...]）：使查询端与索引端使用相同的标签格式，BGE-m3 可将拥有
      相同标签的查询与候选字段在向量空间中拉近。
    - 中文同义词：补在标签后，桥接中文标准字段，提升跨语言召回（如 appProtocol →
      补"协议"，使其更易命中系统属性名"协议 protocol"）。

    Args:
        field_name: 原始字段名（如 destAddress, src_ip_list）

    Returns:
        带标签与中文同义词的文本，供 Embedding API 编码
    """
    tags = _generate_field_tags(field_name)
    expanded = _expand_field_name(field_name)
    zh_synonyms = _collect_zh_synonyms(field_name)
    parts = [expanded]
    if tags:
        parts.append(f"[TAGS:{' '.join(tags)}]")
    if zh_synonyms:
        parts.append(" ".join(zh_synonyms))
    return " ".join(parts)


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
    similarity_matrix: np.ndarray,
    candidates_tmp: list[tuple],
    candidates: list[str],
    records: list[dict],
    elapsed_seconds: float,
) -> None:
    """打印单个字段检索各阶段候选排名与相似度的诊断日志（DEBUG 级别）。

    阶段说明：
    - 阶段1 纯向量：embedding 余弦相似度 top5（即喂给 Layer2 的 sims）
    - 阶段2 收集候选：Layer1/1.5/2/2.5 汇总的候选（含精确匹配与去前缀变体）
    - 阶段3 重排序后：token 重排序后的最终输出（即注入 LLM 的候选）

    记录字段名、候选标准字段名与相似度分数，供字段映射优化分析；这里不接触日志原值。
    """
    stage1 = _format_top_n(similarity_matrix[i], records)
    stage2 = " | ".join(item[0] for item in candidates_tmp) or "(空)"
    stage3 = " | ".join(candidates) or "(空-被阈值过滤/重排序丢弃)"
    logger.debug(
        "[RETRIEVE_TRACE] field=%s elapsed_seconds=%.3f\n"
        "  阶段1 纯向量top5 : %s\n"
        "  阶段2 收集候选(%s): %s\n"
        "  阶段3 重排序输出 : %s",
        field_name,
        elapsed_seconds,
        stage1,
        len(candidates_tmp),
        stage2,
        stage3,
    )

def _apply_mapping_exclusions(
    embeddings: Optional[np.ndarray], records: list[dict]
) -> tuple[Optional[np.ndarray], list[dict]]:
    """按映射目标黑名单同步剔除记录行与嵌入行（issue #125）。

    系统固定字段（事件名称/事件级别/日志类型）不允许被字段映射占用，
    在结构化阶段统一剔除，使精确匹配、去前缀变体与语义检索三层候选
    都不再出现这些字段。嵌入矩阵与记录按行对齐同步删除，不触碰磁盘缓存。
    """
    from agent.tools.rule_generator.field_mapping import MAPPING_EXCLUDED_STANDARD_FIELDS

    if not records or embeddings is None:
        return embeddings, records
    keep_indices = [
        i for i, rec in enumerate(records)
        if rec.get("系统属性名称", "") not in MAPPING_EXCLUDED_STANDARD_FIELDS
    ]
    if len(keep_indices) == len(records):
        return embeddings, records
    dropped = len(records) - len(keep_indices)
    filtered_records = [records[i] for i in keep_indices]
    filtered_embeddings = embeddings[np.array(keep_indices, dtype=int)]
    logger.info(
        "[RETRIEVE] 映射目标黑名单生效：剔除 %s 条固定字段记录，剩余 %s 条",
        dropped,
        len(filtered_records),
    )
    return filtered_embeddings, filtered_records


CandidateRow = tuple[str, float, str, str]
"""单条候选：(系统属性名称, 相似度, 字段英文名, by_stripped 变体名；非变体候选为空串)。"""

CandidateTable = dict[str, list[CandidateRow]]
"""结构化候选出口：原始字段名 → token 重排序后的候选行列表（#180）。"""


def _format_candidate(row: CandidateRow) -> str:
    """把结构化候选行渲染为紧凑展示串（与既有 markdown 输出逐字节一致）。"""
    name, score, english, variant = row
    suffix = f", by_stripped={variant}" if variant else ""
    return f"{name}({score:.2f}, {english}{suffix})"


def batch_retrieve_candidates_table(
    raw_field_names: list[str],
    top_k: int = 6,
    *,
    include_mapping_excluded: bool = False,
) -> CandidateTable:
    """
    对一批原始字段名执行语义检索，返回结构化候选表（#180 结构化出口）。

    整体链路：
    1. 加载磁盘缓存（若不存在则自动初始化）
    2. 对 raw_field_names 批量调用 Embedding API
    3. 矩阵乘法计算余弦相似度：[N_fields, N_records]
    4. 每个字段取 top_k，token 重排序后输出结构化行

    Args:
        raw_field_names: 原始字段名列表
        top_k: 每个字段返回的候选数（默认 6，调用方常用 5）
        include_mapping_excluded: 保留映射黑名单记录（默认剔除）。
            #173 威胁链路 X 判定需要检索黑名单字段「威胁类型」自身的相似度，
            这是黑名单记录唯一的合法消费场景。

    Returns:
        {原始字段名: [(系统属性名称, 相似度, 字段英文名, by_stripped变体)]}；
        无候选的字段不出现（与 markdown 出口只输出非空行一致）。
    """
    if not raw_field_names:
        return {}

    # 加载缓存，不存在则自动初始化；随后按映射目标黑名单剔除固定字段行
    embeddings, records = _load_cache()
    if embeddings is None or records is None:
        logger.info("[RETRIEVE] 缓存不存在，尝试自动初始化")
        if not init_field_cache():
            logger.warning("[RETRIEVE] 缓存初始化失败，返回空候选")
            return {}
        embeddings, records = _load_cache()
        if embeddings is None or records is None:
            return {}
    if not include_mapping_excluded:
        embeddings, records = _apply_mapping_exclusions(embeddings, records)

    # 批量嵌入用户字段名 — 保序去重 + 进程内缓存，仅对 miss 分批调 API（#245/#246）
    query_vecs = embed_query_texts(
        [_build_query_text_for_embedding(n) for n in raw_field_names],
        failure_label="语义检索失败",
        api_call=_call_embedding_api,
    )

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

    # 批量嵌入去前缀变体（与主字段轮共享进程内缓存，#245/#246）
    stripped_vecs: Optional[np.ndarray] = None
    if stripped_variants:
        try:
            stripped_vecs = embed_query_texts(
                [_build_query_text_for_embedding(v) for v in stripped_variants],
                failure_label="去前缀变体嵌入失败",
                api_call=_call_embedding_api,
            )
            # L2 归一化
            norms_s = np.linalg.norm(stripped_vecs, axis=1, keepdims=True)
            norms_s = np.maximum(norms_s, 1e-10)
            stripped_vecs = stripped_vecs / norms_s
            # 计算去前缀变体的相似度矩阵
            stripped_sim_matrix = np.dot(stripped_vecs, embeddings.T)
        except RuntimeError as e:
            logger.warning(f"[RETRIEVE] 去前缀变体嵌入失败，跳过: {e}")
            stripped_variants.clear()

    table: CandidateTable = {}
    for i, field_name in enumerate(raw_field_names):
        field_started_at = time.monotonic()
        sims = similarity_matrix[i]

        # 取 top_k（用 argpartition 比 argsort 更快）
        if len(sims) <= top_k:
            top_indices = np.argsort(sims)[::-1]
        else:
            # 分区后取 top_k
            partitioned = np.argpartition(sims, -top_k)[-top_k:]
            top_indices = partitioned[np.argsort(sims[partitioned])[::-1]]

        # 收集候选（相似度 >= 阈值）— 暂存为 (formatted_str, field_name, sim_score, row) 元组
        candidates_tmp: list[tuple[str, str, float, CandidateRow]] = []
        seen_field_keys: set[str] = set()  # 防止精确匹配和语义检索重复

        # Layer 1: 精确名称匹配兜底（置顶）— 先试原始字段名
        normalized_key = _normalize_field_name(field_name)
        exact_idx = exact_index.get(normalized_key)
        # 紧凑形式兜底：消除 file_name（camelCase 拆分）与 filename（无分隔符）的鸿沟
        if exact_idx is None:
            exact_idx = exact_index.get(_compact_field_name(field_name))
        if exact_idx is not None:
            rec = records[exact_idx]
            rfn = rec.get('字段名称', '')
            candidates_tmp.append(
                (
                    f"{rec.get('系统属性名称', '')}(1.00, {rfn})",
                    rfn,
                    1.0,
                    (rec.get('系统属性名称', ''), 1.0, rfn, ""),
                )
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
                            (
                                f"{v_rec.get('系统属性名称', '')}(1.00, {v_key_name}, by_stripped={variant})",
                                v_key_name,
                                1.0,
                                (v_rec.get('系统属性名称', ''), 1.0, v_key_name, variant),
                            )
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
                (
                    f"{rec.get('系统属性名称', '')}({sim:.2f}, {rec_field_name})",
                    rec_field_name,
                    sim,
                    (rec.get('系统属性名称', ''), sim, rec_field_name, ""),
                )
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
                        (
                            f"{v_rec.get('系统属性名称', '')}({v_sim:.2f}, {v_rfn}, by_stripped={variant_name})",
                            v_rfn,
                            v_sim,
                            (v_rec.get('系统属性名称', ''), v_sim, v_rfn, variant_name),
                        )
                    )
                    seen_field_keys.add(v_rfn)

        # Token 重叠重排序：精确匹配优先，其次按展开 token 重叠数降序，再按相似度降序
        source_tokens = _get_field_name_tokens(field_name)
        reranked_rows: list[tuple[int, int, float, str, CandidateRow]] = []
        for fmt_str, cand_field, sim, candidate_row in candidates_tmp:
            cand_tokens = _get_field_name_tokens(cand_field)
            overlap = len(source_tokens & cand_tokens)
            tier = 0 if sim >= 0.999 else 1
            reranked_rows.append((tier, -overlap, -sim, fmt_str, candidate_row))
        reranked_rows.sort()
        candidates = [row[4] for row in reranked_rows]

        # 检索诊断：追踪候选在「纯向量 → 候选收集 → token 重排序」各阶段的排名与相似度。
        if RETRIEVE_DEBUG_TRACE and logger.isEnabledFor(logging.DEBUG):
            _log_retrieve_trace(
                field_name,
                i,
                similarity_matrix,
                candidates_tmp,
                [_format_candidate(row) for row in candidates],
                records,
                elapsed_seconds=time.monotonic() - field_started_at,
            )

        if candidates:
            table[field_name] = candidates

    return table


def render_candidates_markdown(table: CandidateTable, top_k: int) -> str:
    """把结构化候选表渲染为紧凑 markdown（与历史 batch_retrieve_candidates 输出逐字节一致）。"""
    lines = [
        f"{field_name} → {' | '.join(_format_candidate(row) for row in rows)}"
        for field_name, rows in table.items()
    ]
    if not lines:
        return ""

    raw_output = (
        f"## 标准字段候选（语义检索 top-{top_k}，按相似度降序）："
        + "\n"
        + "\n".join(lines)
    )

    # 转义特殊字符防止污染提示词格式（冒号、方括号、花括号不会破坏 Markdown 但做保守转义）
    for old, new in [
        ("{", "&#123;"),
        ("}", "&#125;"),
        ("[", "&#91;"),
        ("]", "&#93;"),
    ]:
        raw_output = raw_output.replace(old, new)

    return raw_output


def batch_retrieve_candidates(raw_field_names: list[str], top_k: int = 6) -> str:
    """
    对一批原始字段名执行语义检索，返回紧凑格式的候选列表（markdown 展示串）。

    内部分工为「batch_retrieve_candidates_table 取结构化 →
    render_candidates_markdown 渲染」；本函数签名与返回字节保持历史兼容
    （tests/test_standard_field_catalog_characterization.py 表征锁定）。

    Args:
        raw_field_names: 原始字段名列表
        top_k: 每个字段返回的候选数（默认 6，调用方常用 5）

    Returns:
        紧凑格式字符串，无候选时返回空字符串
    """
    if not raw_field_names:
        return ""

    return render_candidates_markdown(
        batch_retrieve_candidates_table(raw_field_names, top_k=top_k), top_k=top_k
    )


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
