"""StratumGenesis 单机内存链存储。

主链按顺序保存；落选候选保存为休眠分支。这里不实现冲突投票，调用方显式决定
合法候选加入主链还是进入分支。ChainStore 也使用 frozen dataclass；内部快照仅通过
受控方法以 object.__setattr__ 替换，避免对外暴露可变容器。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from block_model import Block, make_genesis_block
from conflict_voter import VoteResult
from epoch_manager import EPOCH_BLOCKS, EpochManager
from novscript.language import LanguageSnapshot
from novscript.registry import BUILTIN_POOL, FeatureRegistry
from utxo_ledger import UTXOLedger


@dataclass(frozen=True)
class ChainStore:
    """不可变接口外观的内存存储；更新操作产生新的内部快照。"""

    _main_chain: tuple[Block, ...] = field(default_factory=tuple)
    _sleeping_branches: tuple[tuple[str, tuple[Block, ...]], ...] = field(default_factory=tuple)
    utxo_ledger: UTXOLedger = field(default_factory=UTXOLedger, compare=False)
    epoch_manager: EpochManager = field(default_factory=EpochManager, compare=False)
    # 历史层（provenance，只增不减）：链上曾经激活过的全部扩展原语。
    # 用于判定「引种 vs 新特性」与对外 cumulative_active_features。
    language_registry: FeatureRegistry = field(default_factory=FeatureRegistry, compare=False)
    # 纪元层：当前纪元已激活的扩展原语（纪元首块 height%100==0 时重置为空）。
    # 语言作用域是纪元内有效：跨纪元默认失忆，需引种（Inoculation）。
    epoch_registry: FeatureRegistry = field(default_factory=FeatureRegistry, compare=False)
    # 主链高度 -> 该高度上链后的【纪元作用域】语言快照（版本化重放的权威依据）。
    _language_snapshots: dict[int, LanguageSnapshot] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        if not self._main_chain:
            object.__setattr__(self, "_main_chain", (make_genesis_block(),))
        if self._main_chain[0].height != 0 or self._main_chain[0].parent_hash is not None:
            raise ValueError("main chain must start with genesis block")
        # 创世高度也必须有语言快照（空特性集）：语言演化链条从创世块起，
        # 保证「每个主链高度都能版本化重放」这一不变量。
        if not self._language_snapshots:
            object.__setattr__(
                self, "_language_snapshots",
                {0: LanguageSnapshot.from_registry(self.epoch_registry, 0)},
            )

    @property
    def tip(self) -> Block:
        return self._main_chain[-1]

    @property
    def height(self) -> int:
        return self.tip.height

    def main_chain(self) -> tuple[Block, ...]:
        return self._main_chain

    def _branch_map(self) -> dict[str, tuple[Block, ...]]:
        return dict(self._sleeping_branches)

    def all_blocks(self) -> tuple[Block, ...]:
        branches = tuple(block for branch in self._branch_map().values() for block in branch)
        return self._main_chain + branches

    def get_block(self, block_hash: str) -> Block | None:
        return next((block for block in self.all_blocks() if block.block_hash == block_hash), None)

    def contains(self, block_hash: str) -> bool:
        return self.get_block(block_hash) is not None

    def append_main(self, block: Block) -> None:
        """受控追加主链区块；不接受错误父节点或重复区块。

        语言演化（纪元作用域）：
        - 纪元首块（height%100==0 且非创世）先把纪元层重置为空（失忆起点）；
        - activation 中每个名字：历史层无 -> 新特性（注册进历史层，只增不减）；
          历史层已有 -> 引种（历史层不变，不抛 already registered）；
          纪元层照常累积；
        - 语言快照记录「纪元作用域」已激活集（跨纪元默认失忆，需引种）。
        休眠分支不会走到这里。
        """
        if block.parent_hash != self.tip.block_hash or block.height != self.tip.height + 1:
            raise ValueError("block does not connect to current main-chain tip")
        if self.contains(block.block_hash):
            raise ValueError("block already exists")
        # 先验证交易，避免主链和账本出现半更新状态；休眠分支不会走这里。
        self.utxo_ledger.validate_transactions(block.transactions)
        object.__setattr__(self, "_main_chain", self._main_chain + (block,))
        self.utxo_ledger.apply_block_rewards(block)
        self.utxo_ledger.apply_transactions(block.transactions)
        # 纪元首块：重置纪元层（新纪元从创世内核起步，扩展原语默认失忆）。
        if block.height % EPOCH_BLOCKS == 0 and block.height > 0:
            object.__setattr__(self, "epoch_registry", FeatureRegistry())
        for name in block.activation:
            spec = BUILTIN_POOL.get(name)
            if spec is None:
                raise ValueError(f"cannot activate unknown feature: {name}")
            if not self.language_registry.has(name):
                # 历史首次激活 -> 新特性：注册进历史层（provenance，只增不减）。
                try:
                    self.language_registry.register(spec)
                except Exception as error:
                    raise ValueError(f"cannot activate feature {name}: {error}") from error
            # 历史层已有 -> 引种：历史层不变（不得抛 already registered）。
            if not self.epoch_registry.has(name):
                try:
                    self.epoch_registry.register(spec)
                except Exception as error:
                    raise ValueError(f"cannot activate feature {name} in epoch: {error}") from error
        object.__setattr__(
            self, "_language_snapshots",
            {**self._language_snapshots, block.height: LanguageSnapshot.from_registry(
                self.epoch_registry, block.height)},
        )
        # 只有主链追加触发纪元扫描；休眠分支的 epoch 只由区块自身计算，
        # 不会生成或改变主链纪元快照。
        self.epoch_manager.scan_chain(self._main_chain)

    def language_snapshot_at(self, height: int) -> LanguageSnapshot | None:
        """返回指定高度上链后的【纪元作用域】语言快照；未知高度返回 None。"""
        return self._language_snapshots.get(height)

    def current_language_snapshot(self) -> LanguageSnapshot:
        """返回当前主链顶端的【纪元作用域】语言快照（含创世块：仅内核，无扩展特性）。"""
        snapshot = self._language_snapshots.get(self.height)
        if snapshot is not None:
            return snapshot
        return LanguageSnapshot(height=self.height, active_features=frozenset())

    def epoch_active_features(self) -> frozenset[str]:
        """当前纪元已激活的扩展原语集（纪元作用域语言基线之上的累积）。"""
        return self.epoch_registry.snapshot()

    def ever_active_features(self) -> frozenset[str]:
        """链上曾经激活过的全部扩展原语（历史层 provenance，只增不减）。"""
        return self.language_registry.snapshot()

    def epoch_of_height(self, height: int) -> int:
        """高度 -> 纪元号（每 EPOCH_BLOCKS 个高度一个纪元）。"""
        return EpochManager.get_epoch_of_block(height)

    def first_activation_epoch(self, name: str) -> int | None:
        """返回某原语首次在主链激活的纪元号；从未激活返回 None。

        供 UNIMPORTED_FEATURE 语义化报错（'feature X belongs to epoch N ...'）。
        """
        for block in self._main_chain:
            if name in block.activation:
                return self.epoch_of_height(block.height)
        return None

    def branch_active_features(self, branch_id: str) -> frozenset[str]:
        """休眠分支自身的额外激活集（分支内区块 activation 的累积）。

        不包含主链已激活特性；作为分支级语言演化的基础数据。
        """
        branch = self._branch_map().get(branch_id, ())
        features: set[str] = set()
        for block in branch:
            features.update(block.activation)
        return frozenset(features)

    def add_sleeping_branch(self, block: Block) -> str:
        """保存休眠分支候选，不改变主链。"""
        if self.contains(block.block_hash):
            raise ValueError("block already exists")
        branch_id = block.parent_hash or "orphan"
        branch_map = self._branch_map()
        branch_map[branch_id] = branch_map.get(branch_id, ()) + (block,)
        object.__setattr__(self, "_sleeping_branches", tuple(sorted(branch_map.items())))
        return branch_id

    def apply_vote_result(self, result: VoteResult) -> None:
        """将投票结果写入存储。

        唯一获胜者追加主链；落选者保存休眠分支。vote_tie 的 winner 为 None，
        因而所有候选都会保存且主链保持不变。此方法不执行投票本身。
        """
        if result.winner is not None:
            self.append_main(result.winner)
        for block in result.losers:
            self.add_sleeping_branch(block)

    def sleeping_branches(self) -> dict[str, tuple[Block, ...]]:
        """返回新的字典快照，调用方无法修改存储内部集合。"""
        return self._branch_map()
