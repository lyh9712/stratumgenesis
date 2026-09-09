"""单机原型的 mock 矿工身份层。

miner_pubkey 只是稳定身份字符串；mock_sign 只是可读标记，绝不执行真实
ECDSA 或任何密码学校验。真实密钥与签名留给后续迭代。
"""

from __future__ import annotations


def mock_sign(miner_pubkey: str, payload_hash: str) -> str:
    """生成非密码学签名标记，仅用于数据结构演示。"""
    return f"MOCK-SIGNATURE::{miner_pubkey}::{payload_hash[:16]}"
