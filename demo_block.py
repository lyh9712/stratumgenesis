"""StratumGenesis 最小区块层演示。

演示合法区块、各阶段非法区块，以及合法但落选后进入休眠分支的候选区块。
本脚本不实现网络、投票、签名、纪元或磁盘持久化。
"""

from block_model import Block, PoiRecord, Proposal, TestCase
from block_validator import MIN_POI_TOKENS, validate_block
from chain_store import ChainStore
from crypto_key import generate_miner_keypair, sign_block_payload
from mock_tokenizer import MOCK_TOKENIZER_ID, count_poi_tokens


def make_candidate(store: ChainStore, *, feature: str, demo: str, test: str, expected: object,
                   specification: str = "add a pure extension") -> Block:
    """构造候选区块：先生成无签名对象，再签 canonical_bytes。"""
    prompt = "design a deterministic NovScript extension proposal"
    output = "reasoning " + "token " * (MIN_POI_TOKENS + 2)
    counts = count_poi_tokens(prompt, output)
    proposal = Proposal(feature, specification, demo, (TestCase(test, expected),))
    poi = PoiRecord("manual-mock", prompt, output, MOCK_TOKENIZER_ID,
                    counts.standard_input_tokens, counts.standard_output_tokens,
                    counts.standard_total_tokens)
    private_key, public_key = generate_miner_keypair()
    unsigned = Block(store.tip.height + 1, store.tip.block_hash, "demo-author", proposal, poi, miner_pubkey=public_key)
    signature = sign_block_payload(private_key, unsigned.canonical_bytes())
    return Block(unsigned.height, unsigned.parent_hash, unsigned.proposer, unsigned.proposal, unsigned.poi,
                 unsigned.prototype_version, public_key, signature, epoch=unsigned.epoch)


def show(store: ChainStore, block: Block, label: str, *, main: bool = False) -> None:
    """校验并根据演示意图写入主链或休眠分支。"""
    result = validate_block(block, store)
    print(f"[{label}] accepted={result.accepted}, stage={result.stage}, code={result.error_code}")
    if result.accepted and main:
        store.append_main(block)
        print(f"  -> 已追加主链：height={block.height}, hash={block.block_hash[:16]}...")
    elif result.accepted:
        branch_id = store.add_sleeping_branch(block)
        print(f"  -> 已保存休眠分支：parent={branch_id[:16]}...")


def main() -> None:
    store = ChainStore()
    valid = make_candidate(store, feature="integer-demo", demo="(+ 1 2)", test="(+ 1 2)", expected=3)
    show(store, valid, "合法区块", main=True)

    bad_height = Block(valid.height + 2, valid.parent_hash, valid.proposer, valid.proposal, valid.poi,
                       valid.prototype_version, valid.miner_pubkey, valid.signature_bytes,
                       epoch=valid.epoch)
    show(store, bad_height, "高度错误")

    bad_kernel = make_candidate(store, feature="bad-kernel", demo="(+ 1 2)", test="(+ 1 2)", expected=3,
                                specification="修改创世内核并启用严格求值")
    show(store, bad_kernel, "违反创世内核")

    bad_test = make_candidate(store, feature="wrong-test", demo="(+ 1 2)", test="(+ 1 2)", expected=99)
    show(store, bad_test, "沙箱预期不匹配")

    branch = make_candidate(store, feature="sleeping-candidate", demo="(+ 4 5)", test="(+ 4 5)", expected=9)
    show(store, branch, "合法休眠分支候选", main=False)
    print(f"主链高度={store.height}，休眠分支数量={len(store.sleeping_branches())}")


if __name__ == "__main__":
    main()
