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

    # ------------------------------------------------------------------
    # 阶段 E：休眠分支升级 / 主链重组（Branch Promotion / Reorg）
    # 算法与不变量见 BRANCH_PROMOTION_DESIGN.md §1–§7：
    # scratch 构建 + 原子换入；任何失败路径只丢弃 scratch，live 零变化。
    # ------------------------------------------------------------------
    def _walk_branch(self, head_block_hash: str) -> tuple[list[Block], int]:
        """链回溯（纯只读，设计 §2.1）：返回 (C, f)。

        C = (b_1 … b_k) 为从分支首块到 head 的休眠链；f = 分叉父在主链的高度。
        失败抛 PromotionError：
        - 头不在全店 / 头在主链 -> PROMOTION_NOT_FOUND（E1）
        - 回溯中父缺失（无法锚定主链）-> PROMOTION_PARENT_MISSING（E3）
        - 环 / 步数超界 -> PROMOTION_CHAIN_BROKEN（E2 防御）
        """
        head = self.get_block(head_block_hash)
        if head is None or any(item.block_hash == head_block_hash for item in self._main_chain):
            raise PromotionError("PROMOTION_NOT_FOUND", "head block not found in sleeping branches")
        chain: list[Block] = []
        seen: set[str] = set()
        current = head
        while True:
            if current.block_hash in seen:
                raise PromotionError("PROMOTION_CHAIN_BROKEN", "cycle detected while walking branch")
            seen.add(current.block_hash)
            if len(seen) > self.height + 1:
                raise PromotionError("PROMOTION_CHAIN_BROKEN", "branch walk exceeded depth bound")
            chain.append(current)
            parent = self.get_block(current.parent_hash) if current.parent_hash else None
            if parent is None:
                raise PromotionError(
                    "PROMOTION_PARENT_MISSING", "branch chain cannot be anchored to main chain"
                )
            if any(item.block_hash == current.parent_hash for item in self._main_chain):
                chain.reverse()
                return chain, parent.height
            current = parent

    def inspect_promotion(self, head_block_hash: str) -> PromotionResult:
        """只读资格预检（E1–E6，不含 E7 重放）：供 GET /branches 展示阻塞原因。"""
        from block_validator import check_promotion_eligibility
        try:
            chain, fork_height = self._walk_branch(head_block_hash)
        except PromotionError as error:
            return PromotionResult("rejected", error.code, error.message, old_tip_height=self.height)
        eligibility = check_promotion_eligibility(chain, fork_height, self)
        if not eligibility.accepted:
            return PromotionResult(
                "rejected", eligibility.error_code, eligibility.message, old_tip_height=self.height
            )
        return PromotionResult(
            "ready",
            message="branch is structurally eligible (semantic replay is checked at promote time)",
            fork_height=fork_height,
            old_tip_height=self.height,
            new_tip_height=fork_height + len(chain),
        )

    def branch_head_candidates(self) -> tuple[Block, ...]:
        """返回可作为 promote 起点的全部休眠块（walk 可达主链；按高度升序）。

        供库级调用方 / GET /branches 预览「可提升链」；含深层分支的中间块——
        提升中间块会把它之上（以其为父）的休眠子孙保留在休眠，语义合法。
        """
        candidates = []
        main_hashes = {item.block_hash for item in self._main_chain}
        for block in self.all_blocks():
            if block.block_hash in main_hashes:
                continue
            try:
                self._walk_branch(block.block_hash)
            except PromotionError:
                continue
            candidates.append(block)
        return tuple(sorted(candidates, key=lambda item: item.height))

    def promote_branch(
        self,
        head_block_hash: str,
        *,
        validator=None,
        eligibility_checker=None,
    ) -> PromotionResult:
        """休眠分支升级 / 主链重组（设计 §3 S1–S4）。

        - S1 链回溯 walk；S2 结构资格 E1–E6（check_promotion_eligibility）；
        - S3 在全新 scratch ChainStore 上重放「保留前缀 M[1..f] -> 分支链 C
          （逐块完整校验 E7）-> 休眠迁移（S\\C 原分组序 + 旧后缀按高度升序）」；
        - S4 单临界区原子换入（唯一提交点），live store 零中间态。
        任何失败返回 rejected 且本 store 全部可观测状态不变（I-11）。
        依赖注入避免循环导入：validator / eligibility_checker 默认取
        block_validator 的既有函数（延迟导入）。
        """
        from block_validator import check_promotion_eligibility, validate_block
        validator = validator or validate_block
        eligibility_checker = eligibility_checker or check_promotion_eligibility

        old_tip_height = self.height

        # S1 链回溯（纯只读）。
        try:
            chain, fork_height = self._walk_branch(head_block_hash)
        except PromotionError as error:
            return PromotionResult(
                "rejected", error.code, error.message, old_tip_height=old_tip_height
            )

        # S2 结构资格判定 E1–E6（纯函数，只读）。
        eligibility = eligibility_checker(chain, fork_height, self)
        if not eligibility.accepted:
            return PromotionResult(
                "rejected", eligibility.error_code, eligibility.message,
                old_tip_height=old_tip_height,
            )

        # S3 scratch 构建：任何失败丢弃 scratch，live 不动。
        scratch = ChainStore()
        try:
            # S3a 重放保留前缀 M[1..f]（创世块 M[0] 已由 ChainStore() 自带）。
            for block in self._main_chain[1 : fork_height + 1]:
                scratch.append_main(block)
            # S3b 分支链逐块完整校验并追加（E7 语义资格）。
            for index, block in enumerate(chain):
                result = validator(block, scratch)
                if not result.accepted:
                    raise PromotionError(
                        result.error_code or "PROMOTION_REPLAY_FAILED",
                        f"branch block #{index + 1} at height={block.height} rejected in new world "
                        f"({result.stage}: {result.error_code or result.message})",
                    )
                scratch.append_main(block)
            # S3c 休眠迁移：S\\C 按原分组顺序跳过被提升块。
            for _branch_id, branch_blocks in self._sleeping_branches:
                for block in branch_blocks:
                    if any(item.block_hash == block.block_hash for item in chain):
                        continue
                    scratch.add_sleeping_branch(block)
            # 旧后缀按高度升序入休眠（设计 §6.2 确定性写入顺序）。
            for block in self._main_chain[fork_height + 1 :]:
                scratch.add_sleeping_branch(block)
        except PromotionError as error:
            return PromotionResult(
                "rejected", error.code, error.message, old_tip_height=old_tip_height
            )
        except Exception as error:
            return PromotionResult(
                "rejected", "PROMOTION_REPLAY_FAILED",
                f"internal replay error: {error}", old_tip_height=old_tip_height,
            )

        # S4 原子换入（唯一提交点）：七个内部引用整体替换为 scratch 对应对象。
        demoted = [block.block_hash for block in self._main_chain[fork_height + 1 :]]
        object.__setattr__(self, "_main_chain", scratch._main_chain)
        object.__setattr__(self, "_sleeping_branches", scratch._sleeping_branches)
        object.__setattr__(self, "utxo_ledger", scratch.utxo_ledger)
        object.__setattr__(self, "epoch_manager", scratch.epoch_manager)
        object.__setattr__(self, "language_registry", scratch.language_registry)
        object.__setattr__(self, "epoch_registry", scratch.epoch_registry)
        object.__setattr__(self, "_language_snapshots", scratch._language_snapshots)
        return PromotionResult(
            "promoted",
            message="branch promoted",
            promoted_hashes=tuple(block.block_hash for block in chain),
            demoted_hashes=tuple(demoted),
            fork_height=fork_height,
            old_tip_height=old_tip_height,
            new_tip_height=self.height,
        )


# ---------------------------------------------------------------------------
# 阶段 E：休眠分支升级 / 主链重组（Branch Promotion / Reorg）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PromotionResult:
    """一次 promote 的结果（设计文档 §6 S6）。

    status="promoted" 时 promoted_hashes / demoted_hashes 为已提升 / 已降级的
    块哈希（hex 串）；status="rejected" 时 error_code + message 说明失败原因，
    且 store 零状态变化（I-11）。
    """

    status: str  # "promoted" | "rejected"
    error_code: str | None = None
    message: str = ""
    promoted_hashes: tuple[str, ...] = ()
    demoted_hashes: tuple[str, ...] = ()
    fork_height: int | None = None
    old_tip_height: int | None = None
    new_tip_height: int | None = None


class PromotionError(Exception):
    """promote 内部失败；携带 stage="promotion" 的错误码与确定性消息。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
