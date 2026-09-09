"""StratumGenesis 单机 UTXO 与交易模型。

UTXO 凭证只属于链内实验记账，不具有现实货币价值，也不参与投票权重。
交易签名使用输入所有者私钥，对交易去掉 tx_signature 的 canonical bytes 签名。
本原型一笔交易使用一个 tx_signature，因此要求所有输入属于同一公钥；多签/聚合
签名不在当前范围内。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Iterable

from crypto_key import sign_block_payload


@dataclass(frozen=True)
class UTXO:
    tx_hash: bytes
    output_index: int
    pubkey: bytes
    amount: int

    def key(self) -> tuple[bytes, int]:
        return self.tx_hash, self.output_index


@dataclass(frozen=True)
class Transaction:
    """不可变交易；输入/输出采用 tuple，兼容传入 list 的构造调用。"""

    inputs: tuple[UTXO, ...] | list[UTXO]
    outputs: tuple[UTXO, ...] | list[UTXO]
    tx_signature: bytes
    transaction_hash: bytes = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "inputs", tuple(self.inputs))
        object.__setattr__(self, "outputs", tuple(self.outputs))
        object.__setattr__(self, "transaction_hash", calculate_transaction_hash(self))

    def unsigned_payload(self) -> dict[str, Any]:
        """不含签名和输出 tx_hash 的交易内容；避免交易哈希自引用。"""
        return {
            "inputs": [
                {"tx_hash": item.tx_hash.hex(), "output_index": item.output_index,
                 "pubkey": item.pubkey.hex(), "amount": item.amount}
                for item in self.inputs
            ],
            "outputs": [
                {"output_index": index, "pubkey": item.pubkey.hex(), "amount": item.amount}
                for index, item in enumerate(self.outputs)
            ],
        }

    def canonical_bytes(self) -> bytes:
        return json.dumps(self.unsigned_payload(), sort_keys=True, separators=(",", ":")).encode("utf-8")


def calculate_transaction_hash(transaction: Transaction) -> bytes:
    return hashlib.sha256(transaction.canonical_bytes()).digest()


def make_signed_transaction(private_key: bytes, input_utxos: Iterable[UTXO], output_specs: Iterable[tuple[bytes, int]]) -> Transaction:
    """根据输入 UTXO 和 (收款公钥, 金额) 创建并签名交易。"""
    inputs = tuple(input_utxos)
    specs = tuple(output_specs)
    if not inputs:
        raise ValueError("transaction requires at least one input")
    if not specs:
        raise ValueError("transaction requires at least one output")
    # 先用占位 tx_hash 构造交易以计算稳定交易哈希；输出 UTXO 的 tx_hash 随后固定。
    placeholder_outputs = tuple(UTXO(b"", index, pubkey, amount) for index, (pubkey, amount) in enumerate(specs))
    unsigned = Transaction(inputs, placeholder_outputs, b"")
    tx_hash = unsigned.transaction_hash
    outputs = tuple(UTXO(tx_hash, index, pubkey, amount) for index, (pubkey, amount) in enumerate(specs))
    final_unsigned = Transaction(inputs, outputs, b"")
    signature = sign_block_payload(private_key, final_unsigned.canonical_bytes())
    return Transaction(inputs, outputs, signature)
