"""Provider registry, master-key resolution and secret sealing for the admin console.

Secrets are sealed with an HMAC-SHA256 CTR keystream plus an encrypt-then-MAC
tag (stdlib only). The master key comes from ``V2_MASTER_KEY`` (base64 or hex,
32 bytes) or a ``master.key`` file inside the data directory; production
without either fails closed on every secret operation.
"""
import base64
import hashlib
import hmac
import os
from pathlib import Path

PROVIDER_LABELS = {"openai": "OpenAI", "deepseek": "DeepSeek", "siliconflow": "SiliconFlow"}
PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
}


def provider_label(provider: str) -> str:
    return PROVIDER_LABELS.get(provider, provider)


class MasterKeyUnavailable(RuntimeError):
    """Raised when provider secrets cannot be sealed or opened safely."""


def resolve_master_key(data_dir: Path, *, development: bool) -> bytes | None:
    """Env ``V2_MASTER_KEY`` first, then data-dir key file; production fails closed."""
    raw = os.environ.get("V2_MASTER_KEY", "").strip()
    if raw:
        try:
            key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)) if "-" in raw or "_" in raw else bytes.fromhex(raw)
        except (ValueError, TypeError):
            raise MasterKeyUnavailable("master_key_invalid_format")
        if len(key) < 32:
            raise MasterKeyUnavailable("master_key_invalid_format")
        return key[:32]
    key_file = data_dir / "master.key"
    if key_file.exists():
        key = key_file.read_bytes().strip()
        if len(key) >= 32:
            return key[:32]
        raise MasterKeyUnavailable("master_key_invalid_format")
    if not development:
        return None
    key = os.urandom(32)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(key)
    return key


def _subkey(master: bytes, purpose: bytes) -> bytes:
    return hmac.new(master, purpose, hashlib.sha256).digest()


def _keystream(key_enc: bytes, nonce: bytes, length: int) -> bytes:
    stream = bytearray()
    counter = 0
    while len(stream) < length:
        stream.extend(hmac.new(key_enc, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    return bytes(stream[:length])


def seal_secret(master: bytes, plaintext: str) -> dict:
    """Seal one secret version into a self-contained blob: nonce + ciphertext + tag."""
    key_enc = _subkey(master, b"provider-secret-enc")
    key_mac = _subkey(master, b"provider-secret-mac")
    nonce = os.urandom(16)
    raw = plaintext.encode("utf-8")
    ciphertext = bytes(a ^ b for a, b in zip(raw, _keystream(key_enc, nonce, len(raw))))
    tag = hmac.new(key_mac, nonce + ciphertext, hashlib.sha256).digest()
    return {"blob": nonce + ciphertext + tag, "key_id": hashlib.sha256(master).hexdigest()[:16]}


def open_secret(master: bytes, blob: bytes) -> str:
    key_mac = _subkey(master, b"provider-secret-mac")
    nonce, ciphertext, tag = blob[:16], blob[16:-32], blob[-32:]
    if not hmac.compare_digest(hmac.new(key_mac, nonce + ciphertext, hashlib.sha256).digest(), tag):
        raise MasterKeyUnavailable("master_key_invalid")
    key_enc = _subkey(master, b"provider-secret-enc")
    raw = bytes(a ^ b for a, b in zip(ciphertext, _keystream(key_enc, nonce, len(ciphertext))))
    return raw.decode("utf-8")
