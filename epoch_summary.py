"""StratumGenesis 纪元摘要：确定性规则模板生成 + 历史贡献加权投票（mock 版）。

对应设计白皮书 §7.2–7.4「多节点并行压缩与摘要投票」的仿真实现：

- 纪元边界（主链追加使 height % 100 == 0）时，用 2–3 套不同规则模板从该纪元
  主链区块生成若干摘要候选；
- 复用 weight_calculator.calculate_historical_weights 的历史贡献权重（仅主链、
  截止该纪元边界）对候选加权投票；
- 平票按模板名排序取首个，但显式记录 tie_occurred=True；
- 投票只影响摘要选择，绝不触碰区块合法性、UTXO 账本、休眠分支逻辑。

全程 mock：不调用任何真实 LLM 或网络；同一状态可复现。

⚠️ 未来替换点（接入真实 LLM 时）：
1. 保留 SummaryCandidate / EpochSummary 数据结构与投票/归档语义；
2. 将 generate_candidates() 内的三套规则模板替换为「统一压缩提示词 + 真实 LLM
   并行生成」，每个候选仍带 template 名与生产者标签；
3. 投票输入权重仍来自 calculate_historical_weights（主链历史贡献），语义不变；
4. 风险提示（必须保留在文档与注释中）：真实 LLM 摘要存在信息衰减与幻觉风险，
   摘要链仍线性低速增长；落选候选按白皮书 §7.3 归档为「备选摘要」供考古参考。
"""

from __future__ import annotations

from dataclasses import dataclass

from block_model import Block
from weight_calculator import calculate_historical_weights

# 摘要方法族标签：未来接入真实 LLM 时改为如 "llm-summary-v1"。
METHOD_LABEL = "mock-rule-v1"

# 三套确定性规则模板名（也作为候选 id，投票/归档/前端展示均使用）。
TEMPLATE_KEYWORD_TOP = "keyword-top"                 # 特性关键词词频 Top
TEMPLATE_CONTRIBUTOR = "contributor-distribution"    # 贡献者分布
TEMPLATE_NARRATIVE = "first-last-narrative"          # 首末特性串讲
_TEMPLATES = (TEMPLATE_KEYWORD_TOP, TEMPLATE_CONTRIBUTOR, TEMPLATE_NARRATIVE)

# 关键词词频模板使用的固定词表（仅计数、不修改链上任何内容）。
_KEYWORDS = ("函数", "lambda", "增量", "绑定", "bind", "变量", "求和", "加法",
             "注释", "闭包", "负整数", "聚合")

_GENESIS_LABEL = "创世者"


@dataclass(frozen=True)
class SummaryCandidate:
    """一个摘要候选：模板名、文本、生产者（标签 + 公钥）、投票权重。"""

    candidate_id: str
    text: str
    producer_label: str
    producer_pubkey: bytes
    weight: int = 0


@dataclass(frozen=True)
class EpochSummary:
    """一个已确定（finalized）的纪元摘要；确定后不可变。

    - status 恒为 "finalized"（pending 状态由 EpochSnapshot.summary=None 表示）；
    - candidates 保存全部候选（含落选，作为「备选摘要」归档语义）；
    - tie_occurred=True 表示本次投票发生过平票并按模板名排序回退。
    """

    epoch_number: int
    method_label: str = METHOD_LABEL
    status: str = "finalized"
    candidates: tuple[SummaryCandidate, ...] = ()
    winner_candidate_id: str | None = None
    winner_producer_label: str | None = None
    final_text: str | None = None
    tie_occurred: bool = False


def _feature_display_name(block: Block) -> str:
    """区块特性的人名化显示名（与 server.py 的种子命名规则保持一致）。"""
    if block.height == 0:
        return "创世内核"
    description = block.proposal.specification
    if description.startswith("预沉积演示特性"):
        return description.replace("预沉积演示特性 ", "").split("（")[0]
    return block.proposal.feature_id


def _producers_of(epoch_blocks: list[Block]) -> list[tuple[bytes, str]]:
    """该纪元内参与生产的矿工（公钥, 标签），按公钥字节排序保证确定性。"""
    seen: dict[bytes, str] = {}
    for block in epoch_blocks:
        if block.height == 0 or block.miner_pubkey == b"genesis":
            continue
        seen.setdefault(block.miner_pubkey, block.proposer)
    return sorted(seen.items(), key=lambda item: item[0])


def _template_keyword_top(epoch_blocks: list[Block]) -> str:
    """模板 1：特性关键词词频 Top3（按 (-次数, 关键词) 排序，确定性）。"""
    counts: dict[str, int] = {}
    for block in epoch_blocks:
        haystack = (block.proposal.specification + block.proposal.feature_id).lower()
        for keyword in _KEYWORDS:
            if keyword in haystack:
                counts[keyword] = counts.get(keyword, 0) + 1
    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:3]
    if not top:
        return "本纪元未检出显著特性关键词。"
    return "本纪元高频主题 Top{}：{}。".format(
        len(top), "、".join(f"{kw}（{count} 次）" for kw, count in top)
    )


def _template_contributor(epoch_blocks: list[Block]) -> str:
    """模板 2：贡献者（生产者）分布，按 (-块数, 标签) 排序。"""
    counts: dict[str, int] = {}
    for block in epoch_blocks:
        label = _GENESIS_LABEL if block.height == 0 else block.proposer
        counts[label] = counts.get(label, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    total = sum(counts.values())
    return "贡献者分布：{}（合计 {} 块）。".format(
        " · ".join(f"{label} {count} 块" for label, count in ordered), total
    )


def _template_narrative(epoch_blocks: list[Block]) -> str:
    """模板 3：首末特性串讲 + 特性覆盖面。"""
    first, last = epoch_blocks[0], epoch_blocks[-1]
    name_counts: dict[str, int] = {}
    for block in epoch_blocks:
        name = _feature_display_name(block)
        name_counts[name] = name_counts.get(name, 0) + 1
    covered = sorted(name_counts.items(), key=lambda item: (-item[1], item[0]))[:6]
    return "从首块「{}」（H{}）到末块「{}」（H{}），共 {} 块；涵盖特性：{}。".format(
        _feature_display_name(first), first.height,
        _feature_display_name(last), last.height,
        len(epoch_blocks),
        "、".join(f"{name}×{count}" for name, count in covered),
    )


def generate_candidates(
    epoch_number: int,
    epoch_blocks: list[Block],
    method_label: str = METHOD_LABEL,
) -> list[SummaryCandidate]:
    """用全部规则模板生成摘要候选；纯函数、与链状态无关、完全可复现。"""
    if not epoch_blocks:
        raise ValueError("epoch_blocks must not be empty")
    producers = _producers_of(epoch_blocks)
    if not producers:
        producers = [(b"genesis", _GENESIS_LABEL)]
    templates = (TEMPLATE_KEYWORD_TOP, TEMPLATE_CONTRIBUTOR, TEMPLATE_NARRATIVE)
    texts = (
        _template_keyword_top(epoch_blocks),
        _template_contributor(epoch_blocks),
        _template_narrative(epoch_blocks),
    )
    candidates = []
    for index, (template, text) in enumerate(zip(templates, texts)):
        pubkey, label = producers[index % len(producers)]
        candidates.append(SummaryCandidate(
            candidate_id=f"{method_label}:{template}",
            text=text,
            producer_label=label,
            producer_pubkey=pubkey,
        ))
    return candidates


def vote_summary(
    epoch_number: int,
    candidates: list[SummaryCandidate] | tuple[SummaryCandidate, ...],
    weights: dict[str, int],
) -> EpochSummary:
    """对候选按历史贡献权重投票；平票按候选 id（模板名）排序取首并记录。

    weights 键为矿工公钥原始字节（与 calculate_historical_weights 输出一致）。
    本函数不触碰区块/账本/休眠分支，仅选择摘要。
    """
    tallied = tuple(
        SummaryCandidate(
            candidate_id=item.candidate_id,
            text=item.text,
            producer_label=item.producer_label,
            producer_pubkey=item.producer_pubkey,
            weight=weights.get(item.producer_pubkey, 0),
        )
        for item in candidates
    )
    highest = max(item.weight for item in tallied)
    winners = tuple(item for item in tallied if item.weight == highest)
    tie_occurred = len(winners) != 1
    if tie_occurred:
        winner = sorted(winners, key=lambda item: item.candidate_id)[0]
    else:
        winner = winners[0]
    return EpochSummary(
        epoch_number=epoch_number,
        method_label=winner.candidate_id.split(":", 1)[0] if ":" in winner.candidate_id else METHOD_LABEL,
        status="finalized",
        candidates=tallied,
        winner_candidate_id=winner.candidate_id,
        winner_producer_label=winner.producer_label,
        final_text=winner.text,
        tie_occurred=tie_occurred,
    )


def finalize_epoch_summary(
    epoch_number: int,
    epoch_blocks: list[Block],
    main_chain_prefix: list[Block] | tuple[Block, ...],
    method_label: str = METHOD_LABEL,
) -> EpochSummary:
    """完整流程：生成候选 → 按截止纪元边界的历史权重投票 → 返回已确定摘要。

    main_chain_prefix 必须为主链上截止该纪元末块（含末块）的区块序列，保证
    权重「仅主链、截止纪元边界」；主链只追加不可变，因此该前缀对已归档纪元
    恒定，重建（save→load 重放）得到的摘要与保存前逐字段一致。
    """
    candidates = generate_candidates(epoch_number, epoch_blocks, method_label)
    weights = calculate_historical_weights(main_chain_prefix)
    return vote_summary(epoch_number, candidates, weights)
