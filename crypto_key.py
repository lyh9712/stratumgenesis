"""StratumGenesis 原型的 ECDSA 密钥与签名工具。

仅使用 ecdsa 第三方库完成实验级签名；本模块不实现网络身份认证、密钥托管或
生产级密码学协议。签名对象必须是区块去掉 signature_bytes 后的 canonical_bytes。
"""

from __future__ import annotations

from ecdsa import SigningKey, VerifyingKey, NIST256p, BadSignatureError


def generate_miner_keypair() -> tuple[bytes, bytes]:
    """生成 NIST256p ECDSA 私钥、公钥的原始字节。"""
    private_key = SigningKey.generate(curve=NIST256p)
    return private_key.to_string(), private_key.get_verifying_key().to_string()


def public_key_from_private(private_key: bytes) -> bytes:
    """从私钥导出对应公钥原始字节。"""
    return SigningKey.from_string(private_key, curve=NIST256p).get_verifying_key().to_string()


def sign_block_payload(private_key: bytes, block_canonical_bytes: bytes) -> bytes:
    """用私钥对无签名 canonical bytes 签名，返回签名字节。"""
    signing_key = SigningKey.from_string(private_key, curve=NIST256p)
    return signing_key.sign_deterministic(block_canonical_bytes)


def verify_block_signature(public_key: bytes, block_canonical_bytes: bytes, signature_bytes: bytes) -> bool:
    """验证签名；任何格式错误或签名错误都返回 False。"""
    if not public_key or not signature_bytes:
        return False
    try:
        verifying_key = VerifyingKey.from_string(public_key, curve=NIST256p)
        return verifying_key.verify(signature_bytes, block_canonical_bytes)
    except (BadSignatureError, ValueError, TypeError):
        return False
