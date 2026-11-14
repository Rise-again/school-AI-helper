"""教务口令的对称加密。

- 算法：AES-256-GCM，随机 12 字节 nonce，输出 nonce + 密文（含 tag）。
- 密钥：优先用 EDU_CRED_KEY（32 字节 hex）；留空时由 JWT_SECRET 派生。
  课程项目没有 KMS，派生方案能避免把第二个密钥散落在部署文档里；
  若日后要轮换，配置 EDU_CRED_KEY 即可，旧数据重绑一次。
- AAD 绑定 user_id：把 A 用户的密文挪给 B 用会解密失败。
"""

from __future__ import annotations

import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings

_NONCE_BYTES = 12


def _cred_key(settings: Settings) -> bytes:
    raw = (settings.edu_cred_key or "").strip()
    if raw:
        key = bytes.fromhex(raw)
        if len(key) != 32:
            raise ValueError("EDU_CRED_KEY 必须是 32 字节（64 位十六进制）")
        return key
    return hashlib.sha256(b"campus-edu-cred:" + settings.jwt_secret.encode("utf-8")).digest()


def encrypt_secret(settings: Settings, user_id: int, plaintext: str) -> bytes:
    nonce = os.urandom(_NONCE_BYTES)
    cipher = AESGCM(_cred_key(settings))
    blob = cipher.encrypt(nonce, plaintext.encode("utf-8"), f"edu:{user_id}".encode())
    return nonce + blob


def decrypt_secret(settings: Settings, user_id: int, blob: bytes | None) -> str:
    if not blob:
        raise ValueError("未绑定教务账号")
    if len(blob) <= _NONCE_BYTES:
        raise ValueError("教务口令密文损坏")
    nonce, payload = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    cipher = AESGCM(_cred_key(settings))
    return cipher.decrypt(nonce, payload, f"edu:{user_id}".encode()).decode("utf-8")
