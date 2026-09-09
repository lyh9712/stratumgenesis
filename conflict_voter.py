"""同父同高度候选区块的 mock 历史贡献加权投票。"""

from __future__ import annotations

from dataclasses import dataclass

from block_model import Block


@dataclass(frozen=True)
class VoteTally:
    """一个候选的计票明细。"""

    block_hash: str
    miner_pubkey: str
    weight: int


@dataclass(frozen=True)
class VoteResult:
    """投票结果；tie 时 winner 为 None，所有候选均为落选项。"""

    winner: Block | None
    losers: tuple[Block, ...]
    tallies: tuple[VoteTally, ...]
    status: str  # no_conflict / won / vote_tie


def resolve_conflict(candidates: list[Block] | tuple[Block, ...], weights: dict[str, int]) -> VoteResult:
    """对已合法、同父、同高度候选执行确定性加权选择。

    权重完全相等时按协议要求返回 vote_tie，不写主链，由 ChainStore 统一保存全部候选。
    """
    if not candidates:
        raise ValueError("candidate collection must not be empty")
    tallies = tuple(VoteTally(block.block_hash, block.miner_pubkey, weights.get(block.miner_pubkey, 0)) for block in candidates)
    if len(candidates) == 1:
        return VoteResult(candidates[0], (), tallies, "no_conflict")
    highest = max(tally.weight for tally in tallies)
    winners = tuple(index for index, tally in enumerate(tallies) if tally.weight == highest)
    if len(winners) != 1:
        return VoteResult(None, tuple(candidates), tallies, "vote_tie")
    winner_index = winners[0]
    return VoteResult(candidates[winner_index], tuple(block for index, block in enumerate(candidates) if index != winner_index), tallies, "won")
