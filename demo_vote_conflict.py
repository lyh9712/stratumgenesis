"""StratumGenesis 候选池与历史贡献加权投票演示（ECDSA 版本）。"""

from block_model import Block, PoiRecord, Proposal, TestCase
from block_validator import MIN_POI_TOKENS, validate_block
from candidate_pool import CandidatePool
from chain_store import ChainStore
from conflict_voter import resolve_conflict
from crypto_key import generate_miner_keypair, sign_block_payload
from mock_tokenizer import MOCK_TOKENIZER_ID, count_poi_tokens
from weight_calculator import calculate_historical_weights


def make_block(store: ChainStore, miner: str, feature: str, expression: str, expected: int) -> Block:
    """生成密钥并用对应私钥签名区块，miner 只是展示标签。"""
    prompt = "design a deterministic extension proposal with sandbox tests"
    output = "reasoning token " * (MIN_POI_TOKENS + 4)
    counts = count_poi_tokens(prompt, output)
    proposal = Proposal(feature, "pure extension preserving lazy bind", expression, (TestCase(expression, expected),))
    poi = PoiRecord("manual-mock", prompt, output, MOCK_TOKENIZER_ID,
                    counts.standard_input_tokens, counts.standard_output_tokens, counts.standard_total_tokens)
    private_key, public_key = generate_miner_keypair()
    unsigned = Block(store.tip.height + 1, store.tip.block_hash, miner, proposal, poi, miner_pubkey=public_key)
    signature = sign_block_payload(private_key, unsigned.canonical_bytes())
    return Block(unsigned.height, unsigned.parent_hash, unsigned.proposer, unsigned.proposal, unsigned.poi,
                 unsigned.prototype_version, public_key, signature, epoch=unsigned.epoch)


def main() -> None:
    store = ChainStore()
    pool = CandidatePool()

    block_a = make_block(store, "miner-A", "feature-A", "(+ 1 2)", 3)
    result_a = validate_block(block_a, store)
    print("A 校验：", result_a.accepted, result_a.stage)
    store.append_main(block_a)

    block_b = make_block(store, "miner-A", "feature-B", "(+ 3 4)", 7)
    block_c = make_block(store, "miner-C", "feature-C", "(+ 5 6)", 11)
    for block in (block_b, block_c):
        validation = validate_block(block, store)
        print(block.proposer, "校验：", validation.accepted, validation.stage)
        pool.submit_validated(block, validation)

    key = next(iter(pool.groups()))
    candidates = pool.remove_group(key)
    weights = calculate_historical_weights(store.main_chain())
    vote = resolve_conflict(candidates, weights)
    store.apply_vote_result(vote)

    print("历史贡献权重：", weights)
    print("投票状态：", vote.status)
    print("投票计票明细：")
    for tally in vote.tallies:
        print(" ", tally.miner_pubkey.hex()[:16] + "...", tally.weight, tally.block_hash[:16] + "...")
    print("获胜区块：", vote.winner.proposer if vote.winner else None)
    print("主链高度：", store.height)
    print("休眠分支数量：", len(store.sleeping_branches()))


if __name__ == "__main__":
    main()
