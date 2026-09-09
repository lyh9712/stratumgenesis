"""按父区块哈希与目标高度分组的候选区块池。"""

from __future__ import annotations

from dataclasses import dataclass, field

from block_model import Block
from block_validator import ValidationResult, validate_block
from chain_store import ChainStore


@dataclass(frozen=True)
class CandidateGroupKey:
    """同一父区块与同一目标高度构成一个冲突候选组。"""

    parent_block_hash: str
    target_height: int


@dataclass(frozen=True)
class CandidatePool:
    """单机候选池；只接收验证通过的候选区块。"""

    _groups: tuple[tuple[CandidateGroupKey, tuple[Block, ...]], ...] = field(default_factory=tuple)

    def _mapping(self) -> dict[CandidateGroupKey, tuple[Block, ...]]:
        return dict(self._groups)

    def submit_validated(self, block: Block, validation: ValidationResult) -> CandidateGroupKey:
        """接收已经通过 block_validator 的区块；失败结果会被拒绝。"""
        if not validation.accepted:
            raise ValueError("candidate pool accepts only validated blocks")
        if block.parent_hash is None:
            raise ValueError("candidate block must have parent hash")
        key = CandidateGroupKey(block.parent_hash, block.height)
        groups = self._mapping()
        if block in groups.get(key, ()):
            raise ValueError("duplicate candidate")
        groups[key] = groups.get(key, ()) + (block,)
        object.__setattr__(self, "_groups", tuple(sorted(groups.items(), key=lambda item: (item[0].target_height, item[0].parent_block_hash))))
        return key

    def validate_and_submit(self, block: Block, store: ChainStore) -> tuple[CandidateGroupKey, ValidationResult]:
        """便捷接口：先校验，再把合法候选放入相应分组。"""
        result = validate_block(block, store)
        if not result.accepted:
            raise ValueError(f"invalid candidate: {result.error_code}")
        return self.submit_validated(block, result), result

    def get_group(self, parent_block_hash: str, target_height: int) -> tuple[Block, ...]:
        return self._mapping().get(CandidateGroupKey(parent_block_hash, target_height), ())

    def groups(self) -> dict[CandidateGroupKey, tuple[Block, ...]]:
        return self._mapping()

    def remove_group(self, key: CandidateGroupKey) -> tuple[Block, ...]:
        """取出并删除一个待处理组，防止重复投票。"""
        groups = self._mapping()
        candidates = groups.pop(key, ())
        object.__setattr__(self, "_groups", tuple(sorted(groups.items(), key=lambda item: (item[0].target_height, item[0].parent_block_hash))))
        return candidates
