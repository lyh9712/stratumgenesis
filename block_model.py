"""StratumGenesis 区块数据模型与 ECDSA 签名前规范化序列化。

区块对象全部 frozen。区块哈希和 ECDSA 签名都基于同一份 canonical_bytes；该字节
序列明确排除 signature_bytes，避免签名字段自引用。当前仍是单机内存实验原型，
不提供 P2P、磁盘持久化、UTXO 或生产级密钥管理。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any

from utxo_model import Transaction


@dataclass(frozen=True)
class TestCase:
    program: str
    expected: Any


@dataclass(frozen=True)
class Proposal:
    feature_id: str
    specification: str
    demo_code: str
    test_cases: tuple[TestCase, ...]
    kind: str = "extension"


@dataclass(frozen=True)
class PoiRecord:
    model_metadata: str
    prompt: str
    output: str
    standard_tokenizer: str
    standard_input_tokens: int
    standard_output_tokens: int
    standard_total_tokens: int


@dataclass(frozen=True)
class Block:
    """不可变区块；miner_pubkey 和 signature_bytes 均为原始字节。"""

    height: int
    parent_hash: str | None
    proposer: str
    proposal: Proposal
    poi: PoiRecord
    prototype_version: str = "block-layer-prototype-0.1"
    miner_pubkey: bytes = b""
    signature_bytes: bytes = b""
    transactions: tuple[Transaction, ...] | list[Transaction] = field(default_factory=tuple)
    # 本区块激活的新语言原语名（来自 BUILTIN_POOL 的扩展特性）；
    # 空元组表示普通区块（不改变语言能力）。
    activation: tuple[str, ...] | list[str] = field(default_factory=tuple)
    # -1 是“未由调用方指定”的哨兵；正常构造时自动填充 height // 100。
    # 若调用方显式传入其他值，必须与计算结果一致，否则立即报错。
    epoch: int = -1
    block_hash: str = field(init=False)

    def __post_init__(self) -> None:
        expected_epoch = self.height // 100
        if self.epoch == -1:
            object.__setattr__(self, "epoch", expected_epoch)
        elif self.epoch != expected_epoch:
            raise ValueError(
                f"epoch mismatch: height {self.height} requires epoch {expected_epoch}, got {self.epoch}"
            )
        object.__setattr__(self, "transactions", tuple(self.transactions))
        object.__setattr__(self, "activation", tuple(self.activation))
        object.__setattr__(self, "block_hash", calculate_block_hash(self))

    def canonical_payload(self) -> dict[str, Any]:
        """返回去掉 signature_bytes 和 block_hash 的规范化对象。"""
        return {
            "height": self.height,
            "parent_hash": self.parent_hash,
            "proposer": self.proposer,
            "miner_pubkey_hex": self.miner_pubkey.hex(),
            "prototype_version": self.prototype_version,
            "epoch": self.epoch,
            "activation": list(self.activation),
            "transactions": [
                {
                    "inputs": [
                        {"tx_hash": item.tx_hash.hex(), "output_index": item.output_index,
                         "pubkey": item.pubkey.hex(), "amount": item.amount}
                        for item in transaction.inputs
                    ],
                    "outputs": [
                        {"tx_hash": item.tx_hash.hex(), "output_index": item.output_index,
                         "pubkey": item.pubkey.hex(), "amount": item.amount}
                        for item in transaction.outputs
                    ],
                    "tx_signature": transaction.tx_signature.hex(),
                }
                for transaction in self.transactions
            ],
            "proposal": {
                "kind": self.proposal.kind,
                "feature_id": self.proposal.feature_id,
                "specification": self.proposal.specification,
                "demo_code": self.proposal.demo_code,
                "test_cases": [
                    {"program": case.program, "expected": case.expected}
                    for case in self.proposal.test_cases
                ],
            },
            "poi": {
                "model_metadata": self.poi.model_metadata,
                "prompt": self.poi.prompt,
                "output": self.poi.output,
                "standard_tokenizer": self.poi.standard_tokenizer,
                "standard_input_tokens": self.poi.standard_input_tokens,
                "standard_output_tokens": self.poi.standard_output_tokens,
                "standard_total_tokens": self.poi.standard_total_tokens,
            },
        }

    def canonical_bytes(self) -> bytes:
        """返回签名与哈希共同使用的确定性 UTF-8 JSON 字节。"""
        return json.dumps(
            self.canonical_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")


def calculate_block_hash(block: Block) -> str:
    """SHA-256 哈希明确排除 signature_bytes。"""
    return hashlib.sha256(block.canonical_bytes()).hexdigest()


def make_genesis_block() -> Block:
    """创建未签名的创世锚点；创世块不是普通候选区块。"""
    proposal = Proposal(
        "novscript-genesis-kernel",
        "S-expression; lazy evaluation; immutable bind; integer and function values; builtin +.",
        "1",
        (TestCase("1", 1),),
        kind="genesis-kernel",
    )
    poi = PoiRecord("genesis", "", "", "mock-v1", 0, 0, 0)
    return Block(0, None, "genesis", proposal, poi, miner_pubkey=b"genesis")
