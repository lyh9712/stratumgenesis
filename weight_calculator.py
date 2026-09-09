"""主链历史贡献权重计算。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from block_model import Block


def calculate_historical_weights(main_chain: Iterable[Block]) -> dict[str, int]:
    """仅累加主链已确认区块的 standard_total_tokens。

    休眠分支不会出现在传入的主链列表中，因此不会获得投票权重；创世块的
    0 token 记录自然不产生贡献。返回普通字典，便于投票模块读取。
    """
    weights: defaultdict[str, int] = defaultdict(int)
    for block in main_chain:
        weights[block.miner_pubkey] += block.poi.standard_total_tokens
    return dict(weights)
