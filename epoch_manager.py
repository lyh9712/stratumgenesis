"""StratumGenesis 纪元基础框架与摘要确定。

本模块负责 height -> epoch 的确定性映射、主链边界扫描、内存归档标记，以及
在纪元边界确定 mock 纪元摘要（确定性规则模板 + 历史贡献加权投票，见
epoch_summary.py）。不实现真实 LLM 摘要压缩、引种提案或大断层事件；原始
区块不会被删除。摘要只在主链追加使 height % 100 == 0 时确定，选定即不可变。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from block_model import Block
from epoch_summary import EpochSummary, finalize_epoch_summary

EPOCH_BLOCKS = 100


@dataclass(frozen=True)
class EpochSnapshot:
    """一个纪元的内存快照元数据。

    summary 为 None 表示该纪元尚未封口（pending，由 summary_status 指示）；
    一旦主链越过纪元边界，summary 被确定且此后不可变（与归档只读语义一致）。
    """

    epoch_number: int
    start_height: int
    end_height: int
    block_hashes: list[bytes]
    archived: bool
    # v0.3 阶段 B 追加：已确定摘要（未封口为 None）与状态标记。
    summary: EpochSummary | None = None
    summary_status: str = "pending"  # pending / finalized
    # v0.3 阶段 C 追加：该纪元结束时链级已激活的语言特性集合（语言演化档案）。
    active_features: frozenset[str] = frozenset()


@dataclass
class EpochManager:
    """维护主链纪元快照与摘要链；快照是逻辑只读标记，不删除区块。"""

    _snapshots: list[EpochSnapshot] = field(default_factory=list)
    # v0.3 阶段 B 追加：按纪元顺序排列的已确定摘要链（为「大断层事件」留钩子）。
    _summary_chain: list[EpochSummary] = field(default_factory=list)

    @staticmethod
    def get_epoch_of_block(height: int) -> int:
        """返回区块所属纪元；每 100 个高度归入一个纪元。"""
        if not isinstance(height, int) or height < 0:
            raise ValueError("height must be a non-negative integer")
        return height // EPOCH_BLOCKS

    def scan_chain(self, main_chain: list[Block] | tuple[Block, ...]) -> tuple[EpochSnapshot, ...]:
        """扫描主链并重建快照；边界高度 h=100n 关闭前一纪元并确定其摘要。

        摘要生成只使用「该纪元自身区块」与「截止该纪元末块的主链前缀」这两份
        恒定数据（主链只追加不可变），因此：
        1. 已确定摘要随后续区块追加而不再变化（finalized 不可变语义）；
        2. 存档重放（save -> load）重建得到的摘要与保存前逐字段一致。
        """
        grouped: dict[int, list[Block]] = {}
        for block in main_chain:
            grouped.setdefault(self.get_epoch_of_block(block.height), []).append(block)
        snapshots: list[EpochSnapshot] = []
        summary_chain: list[EpochSummary] = []
        # 按高度顺序累积链级已激活特性：每个纪元快照记录「截至该纪元末尾」
        # 的语言状态（含此前纪元激活的特性），供语言演化档案展示。
        active_features: set[str] = set()
        for epoch_number in sorted(grouped):
            blocks = sorted(grouped[epoch_number], key=lambda item: item.height)
            for block in blocks:
                active_features.update(block.activation)
            start_height = epoch_number * EPOCH_BLOCKS
            end_height = blocks[-1].height
            # 只有主链已经到达下一个纪元起点，才将当前纪元标记归档。
            archived = any(item.height >= (epoch_number + 1) * EPOCH_BLOCKS for item in main_chain)
            summary = None
            summary_status = "pending"
            if archived:
                # 该纪元自身区块（不含越界区块）与截止纪元末块的主链前缀；
                # 均为恒定输入 -> 确定性摘要，重放可复现。
                epoch_blocks = [item for item in blocks if item.height < (epoch_number + 1) * EPOCH_BLOCKS]
                prefix = [item for item in main_chain if item.height <= end_height]
                summary = finalize_epoch_summary(epoch_number, epoch_blocks, prefix)
                summary_status = "finalized"
                summary_chain.append(summary)
            snapshots.append(EpochSnapshot(
                epoch_number, start_height, end_height,
                [bytes.fromhex(item.block_hash) for item in blocks], archived,
                summary, summary_status,
                frozenset(active_features),
            ))
        self._snapshots = snapshots
        self._summary_chain = summary_chain
        return tuple(snapshots)

    def get_epoch_snapshot(self, epoch_number: int) -> EpochSnapshot | None:
        """读取快照；返回对象本身，调用方不应修改其中列表。"""
        return next((item for item in self._snapshots if item.epoch_number == epoch_number), None)

    def snapshots(self) -> tuple[EpochSnapshot, ...]:
        """返回当前快照序列。"""
        return tuple(self._snapshots)

    def summary_chain(self) -> tuple[EpochSummary, ...]:
        """返回按纪元顺序排列的已确定摘要链（为「大断层事件」阶段留钩子）。"""
        return tuple(self._summary_chain)
