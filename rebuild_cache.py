"""Standalone script to rebuild embedding cache without importing full agent module.
Usage: python rebuild_cache.py
"""
import json
import hashlib
import os
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

load_dotenv()

# ---- Config (mirrors field_retriever.py) ----
EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"
EMBEDDING_DIM = 4096
EMBEDDING_API_URL = "https://api.siliconflow.cn/v1/embeddings"
EMBEDDING_BATCH_SIZE = 30
EMBEDDING_BATCH_SLEEP = 0.3
EMBEDDING_TIMEOUT = 15.0
EMBEDDING_MAX_RETRIES = 2
MAX_DESCRIPTION_LENGTH = 200
CACHE_SCHEMA_VERSION = "1"

ABBR_EXPANSIONS = {
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

BASE_DIR = Path(__file__).parent
STANDARD_FIELDS_PATH = BASE_DIR / "config" / "标准字段.txt"
CACHE_EMBEDDINGS_PATH = BASE_DIR / "config" / "标准字段_embeddings.npy"
CACHE_RECORDS_PATH = BASE_DIR / "config" / "标准字段_records.json"
CACHE_META_PATH = BASE_DIR / "config" / "标准字段_cache_meta.json"


def expand_field_name(field_name):
    """Expand abbreviated field name tokens to full English description."""
    tokens = field_name.replace("-", "_").split("_")
    return " ".join(ABBR_EXPANSIONS.get(t.lower(), t) for t in tokens)


def get_api_key():
    return os.getenv("SILICONFLOW_API_KEY", "") or os.getenv("FALLBACK_API_KEY", "")


def load_standard_fields():
    records = []
    raw = STANDARD_FIELDS_PATH.read_text(encoding="utf-8")
    lines = raw.strip().split("\n")
    header = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        cols = [c.strip() for c in line.split("\t")]
        if header is None:
            if cols:
                cols[0] = cols[0].lstrip("\ufeff")
            header = cols
            continue
        if len(cols) < len(header):
            cols.extend([""] * (len(header) - len(cols)))
        entry = dict(zip(header, cols[:len(header)]))
        system_name = entry.get("系统属性名称", "")
        field_name = entry.get("字段名称", "")
        description = entry.get("描述", "")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            description = description[:MAX_DESCRIPTION_LENGTH] + "..."
        obj = entry.get("对象", "")
        data_type = entry.get("属性类型", "")
        english_expanded = expand_field_name(field_name)
        entry["_composite_text"] = f"{english_expanded} || {system_name} | {field_name} | {obj} | {data_type} | {description}"
        records.append(entry)
    return records


def call_embedding_api(texts, retries=EMBEDDING_MAX_RETRIES):
    import requests

    api_key = get_api_key()
    if not api_key:
        print("[ERROR] No SILICONFLOW_API_KEY found in .env")
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
                EMBEDDING_API_URL, headers=headers, json=payload, timeout=EMBEDDING_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
            embeddings = sorted(data["data"], key=lambda x: x["index"])
            vectors = np.array([item["embedding"] for item in embeddings], dtype=np.float32)
            print(f"  [API] {len(texts)} texts → ({vectors.shape[0]}, {vectors.shape[1]})")
            return vectors
        except Exception as e:
            print(f"  [WARN] Attempt {attempt + 1}/{retries + 1}: {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)
    print("[ERROR] All API attempts failed")
    return None


def compute_md5(file_path):
    if not file_path.exists():
        return ""
    return hashlib.md5(file_path.read_bytes()).hexdigest()


def main():
    print("=" * 60)
    print("Rebuilding embedding cache with new composite text format")
    print(f"  Model: {EMBEDDING_MODEL}, dim={EMBEDDING_DIM}")
    print(f"  Threshold: 0.15, TOP_K: 6 (runtime defaults)")
    print("=" * 60)

    api_key = get_api_key()
    if not api_key:
        print("[FATAL] No API key. Set SILICONFLOW_API_KEY in .env")
        return 1

    records = load_standard_fields()
    print(f"Loaded {len(records)} standard field records")

    texts = [r["_composite_text"] for r in records]

    # Show sample composite text
    print(f"\nSample composite text (first 3):")
    for i in range(min(3, len(texts))):
        print(f"  [{i}] {texts[i][:120]}...")

    all_vectors = []
    total_batches = (len(texts) + EMBEDDING_BATCH_SIZE - 1) // EMBEDDING_BATCH_SIZE
    for batch_idx, start in enumerate(range(0, len(texts), EMBEDDING_BATCH_SIZE)):
        batch = texts[start:start + EMBEDDING_BATCH_SIZE]
        print(f"  Batch {batch_idx + 1}/{total_batches} ({len(batch)} texts)...")
        vectors = call_embedding_api(batch)
        if vectors is None:
            print(f"[FATAL] Batch {batch_idx + 1} failed")
            return 1
        all_vectors.append(vectors)
        if start + EMBEDDING_BATCH_SIZE < len(texts):
            time.sleep(EMBEDDING_BATCH_SLEEP)

    concatenated = np.concatenate(all_vectors, axis=0)
    print(f"Total embeddings: {concatenated.shape}")

    # L2 normalize
    norms = np.linalg.norm(concatenated, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-10)
    normalized = concatenated / norms

    # Save
    np.save(str(CACHE_EMBEDDINGS_PATH), normalized)
    CACHE_RECORDS_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Save metadata
    meta = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "standard_fields_md5": compute_md5(STANDARD_FIELDS_PATH),
        "record_count": len(records),
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dim": EMBEDDING_DIM,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    CACHE_META_PATH.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n[DONE] Cache saved:")
    print(f"  {CACHE_EMBEDDINGS_PATH} ({normalized.shape})")
    print(f"  {CACHE_RECORDS_PATH} ({len(records)} records)")
    print(f"  {CACHE_META_PATH}")
    print(f"  MD5: {meta['standard_fields_md5']}")
    return 0


if __name__ == "__main__":
    exit(main())