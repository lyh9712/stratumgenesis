"""单机内存 UTXO 账本。

只有成功进入主链的区块才允许调用奖励和交易应用；休眠/落选区块不触碰本账本。
本模块不实现手续费、磁盘持久化、UTXO 转账之外的资产逻辑或现实货币兑换。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from block_model import Block
from crypto_key import verify_block_signature
from utxo_model import Transaction, UTXO


class UTXOValidationError(ValueError):
    """UTXO 双花、金额、所有权或签名校验失败。"""


@dataclass
class UTXOLedger:
    """可控更新的单机账本；UTXO 集合键为 (tx_hash, output_index)。"""

    _unspent: dict[tuple[bytes, int], UTXO] = field(default_factory=dict)
    _reward_amount: int = 100

    def snapshot(self) -> tuple[UTXO, ...]:
        return tuple(self._unspent.values())

    def get_balance(self, pubkey: bytes) -> int:
        """查询余额；该数值与投票权重完全隔离。"""
        return sum(item.amount for item in self._unspent.values() if item.pubkey == pubkey)

    def apply_block_rewards(self, block: Block) -> UTXO:
        """为已成功主链区块生成奖励 UTXO；调用方不得对休眠区块调用。"""
        reward_hash = bytes.fromhex(block.block_hash)
        reward = UTXO(reward_hash, 0, block.miner_pubkey, self._reward_amount)
        self._unspent[reward.key()] = reward
        return reward

    def validate_transactions(self, transactions: tuple[Transaction, ...] | list[Transaction]) -> None:
        """在不修改账本的前提下验证区块内全部交易，包含区块内双花。"""
        spent_in_batch: set[tuple[bytes, int]] = set()
        for transaction in transactions:
            if not transaction.inputs or not transaction.outputs:
                raise UTXOValidationError("transaction must contain inputs and outputs")
            owners = {item.pubkey for item in transaction.inputs}
            if len(owners) != 1:
                raise UTXOValidationError("prototype transaction inputs must share one owner pubkey")
            input_total = 0
            for input_utxo in transaction.inputs:
                key = input_utxo.key()
                if key in spent_in_batch or key not in self._unspent:
                    raise UTXOValidationError("input UTXO is missing or already spent")
                current = self._unspent[key]
                if current != input_utxo:
                    raise UTXOValidationError("input UTXO does not match ledger record")
                spent_in_batch.add(key)
                input_total += current.amount
            output_total = sum(output.amount for output in transaction.outputs)
            if any(output.amount < 0 for output in transaction.outputs):
                raise UTXOValidationError("output amount cannot be negative")
            if input_total < output_total:
                raise UTXOValidationError("input amount is smaller than output amount")
            owner = next(iter(owners))
            if not verify_block_signature(owner, transaction.canonical_bytes(), transaction.tx_signature):
                raise UTXOValidationError("transaction signature verification failed")

    def apply_transactions(self, transactions: tuple[Transaction, ...] | list[Transaction]) -> None:
        """原子应用交易：先全部验证，再统一消费输入、生成输出。"""
        self.validate_transactions(transactions)
        for transaction in transactions:
            for input_utxo in transaction.inputs:
                del self._unspent[input_utxo.key()]
            for output in transaction.outputs:
                if output.key() in self._unspent:
                    raise UTXOValidationError("output UTXO collision")
                self._unspent[output.key()] = output
