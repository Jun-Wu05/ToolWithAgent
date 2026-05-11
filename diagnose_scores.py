"""Diagnose similarity scores for destAddress, srcAddress, destMacAddress."""
import json
import os
import re
import time

import numpy as np
from dotenv import load_dotenv

load_dotenv()

EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"
EMBEDDING_DIM = 4096
EMBEDDING_API_URL = "https://api.siliconflow.cn/v1/embeddings"
EMBEDDING_TIMEOUT = 60.0
SIMILARITY_THRESHOLD = 0.15
TOP_K = 6

ABBR_EXPANSIONS = {
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


def expand_field_name(field_name):
    # camelCase/pascalCase → snake_case 拆分（与 _expand_field_name 一致）
    name = field_name.replace("-", "_")
    name = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    tokens = name.split("_")
    return " ".join(ABBR_EXPANSIONS.get(t.lower(), t) for t in tokens)


def get_field_tokens(field_name):
    return set(expand_field_name(field_name).split())


def rerank_by_token_overlap(field_name, candidates):
    """Re-rank candidates by (tier, -overlap, -sim) where tier=0 for exact (sim≥0.999)."""
    source_tokens = get_field_tokens(field_name)
    rows = []
    for fmt_str, cand_field, sim in candidates:
        overlap = len(source_tokens & get_field_tokens(cand_field))
        tier = 0 if sim >= 0.999 else 1
        rows.append((tier, -overlap, -sim, fmt_str))
    rows.sort()
    return [r[3] for r in rows]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_EMBEDDINGS_PATH = os.path.join(BASE_DIR, "config", "标准字段_embeddings.npy")
CACHE_RECORDS_PATH = os.path.join(BASE_DIR, "config", "标准字段_records.json")


def get_api_key():
    return os.getenv("SILICONFLOW_API_KEY", "") or os.getenv("FALLBACK_API_KEY", "")


def call_embedding_api(texts):
    import requests

    api_key = get_api_key()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": EMBEDDING_MODEL, "input": texts, "encoding_format": "float"}
    try:
        response = requests.post(
            EMBEDDING_API_URL, headers=headers, json=payload, timeout=EMBEDDING_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
        embeddings = sorted(data["data"], key=lambda x: x["index"])
        return np.array([item["embedding"] for item in embeddings], dtype=np.float32)
    except Exception as e:
        print(f"[ERROR] Embedding API call failed: {e}")
        return None


def main():
    # Load cache
    embeddings = np.load(CACHE_EMBEDDINGS_PATH)
    with open(CACHE_RECORDS_PATH, "r", encoding="utf-8") as f:
        records = json.load(f)

    print(f"Cache: {embeddings.shape[0]} records, dim={embeddings.shape[1]}")
    print()

    test_fields = ["destAddress", "srcAddress", "destMacAddress"]

    # Get embeddings for test fields
    test_vecs = call_embedding_api(test_fields)
    if test_vecs is None:
        return 1

    # L2 normalize
    norms = np.linalg.norm(test_vecs, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-10)
    test_vecs = test_vecs / norms

    # Compute similarity matrix
    sim_matrix = np.dot(test_vecs, embeddings.T)  # (3, 653)

    for i, field in enumerate(test_fields):
        sims = sim_matrix[i]
        # Get top-K
        if len(sims) <= TOP_K:
            top_indices = np.argsort(sims)[::-1]
        else:
            partitioned = np.argpartition(sims, -TOP_K)[-TOP_K:]
            top_indices = partitioned[np.argsort(sims[partitioned])[::-1]]

        # Collect candidates (same logic as field_retriever.py)
        candidates_tmp = []
        for idx in top_indices:
            sim = float(sims[idx])
            if sim < SIMILARITY_THRESHOLD:
                continue
            rec = records[idx]
            rfn = rec.get('字段名称', '')
            candidates_tmp.append(
                (f"{rec.get('系统属性名称', '')}({sim:.2f}, {rfn})", rfn, sim)
            )

        # Show raw embedding order
        print(f"=== {field} (RAW embedding order, top {TOP_K} ≥ {SIMILARITY_THRESHOLD}) ===")
        for fmt_str, rfn, sim in candidates_tmp:
            print(f"  [{sim:.4f}] {fmt_str}")
        print()

        # Show re-ranked order with overlap debug
        reranked = rerank_by_token_overlap(field, candidates_tmp)
        print(f"=== {field} (RE-RANKED by token overlap) ===")
        source_tokens = get_field_tokens(field)
        print(f"  Source tokens: {source_tokens}")
        for fmt_str, cf, sim in candidates_tmp:
            cf_tokens = get_field_tokens(cf)
            ov = len(source_tokens & cf_tokens)
            print(f"  [ov={ov}, sim={sim:.4f}] {fmt_str}")
        print(f"  Final order:")
        for line in reranked:
            print(f"  {line}")
        print()

    # Also check exact match for standard fields containing these keywords
    print("=== Exact/substring match in standard fields ===")
    for field in test_fields:
        matches = [
            r for r in records
            if field.lower() in r.get("字段名称", "").lower()
            or field.lower() in r.get("系统属性名称", "").lower()
        ]
        if matches:
            print(f"  {field}: {len(matches)} matches")
            for m in matches[:5]:
                print(f"    {m.get('系统属性名称', '?')} | {m.get('字段名称', '?')}")
        else:
            print(f"  {field}: NO exact matches")
        print()

    # Summary statistics
    print("=" * 60)
    print("SUMMARY: Top-1 similarity scores")
    for i, field in enumerate(test_fields):
        top_sim = float(np.max(sim_matrix[i]))
        top_idx = int(np.argmax(sim_matrix[i]))
        top_rec = records[top_idx]
        print(
            f"  {field:20s} → [{top_sim:.4f}] {top_rec.get('系统属性名称', '?'):30s} | {top_rec.get('字段名称', '?')}"
        )

    return 0


if __name__ == "__main__":
    exit(main())