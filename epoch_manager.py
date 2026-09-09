"""StratumGenesis 纪元基础框架。

本模块只负责 height -> epoch 的确定性映射、主链边界扫描和内存归档标记。
不实现 LLM 摘要压缩、摘要投票、引种提案或大断层事件；原始区块不会被删除。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from block_model import Block

EPOCH_BLOCKS = 100


@dataclass(frozen=True)
class EpochSnapshot:
    """一个纪元的内存快照元数据。"""

    epoch_number: int
    start_height: int
    end_height: int
    block_hashes: list[bytes]
    archived: bool


@dataclass
class EpochManager:
    """维护主链纪元快照；快照是逻辑只读标记，不删除区块。"""

    _snapshots: list[EpochSnapshot] = field(default_factory=list)

    @staticmethod
    def get_epoch_of_block(height: int) -> int:
        """返回区块所属纪元；每 100 个高度归入一个纪元。"""
        if not isinstance(height, int) or height < 0:
            raise ValueError("height must be a non-negative integer")
        return height // EPOCH_BLOCKS

    def scan_chain(self, main_chain: list[Block] | tuple[Block, ...]) -> tuple[EpochSnapshot, ...]:
        """扫描主链并重建快照；边界高度 h=100n 关闭前一纪元。"""
        grouped: dict[int, list[Block]] = {}
        for block in main_chain:
            grouped.setdefault(self.get_epoch_of_block(block.height), []).append(block)
        snapshots: list[EpochSnapshot] = []
        for epoch_number in sorted(grouped):
            blocks = sorted(grouped[epoch_number], key=lambda item: item.height)
            start_height = epoch_number * EPOCH_BLOCKS
            end_height = blocks[-1].height
            # 只有主链已经到达下一个纪元起点，才将当前纪元标记归档。
            archived = any(item.height >= (epoch_number + 1) * EPOCH_BLOCKS for item in main_chain)
            snapshots.append(EpochSnapshot(
                epoch_number, start_height, end_height,
                [bytes.fromhex(item.block_hash) for item in blocks], archived,
            ))
        self._snapshots = snapshots
        return tuple(snapshots)

    def get_epoch_snapshot(self, epoch_number: int) -> EpochSnapshot | None:
        """读取快照；返回对象本身，调用方不应修改其中列表。"""
        return next((item for item in self._snapshots if item.epoch_number == epoch_number), None)

    def snapshots(self) -> tuple[EpochSnapshot, ...]:
        """返回当前快照序列。"""
        return tuple(self._snapshots)
