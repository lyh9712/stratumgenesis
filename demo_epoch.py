"""StratumGenesis 纪元基础框架演示。

连续写入 1~102 号主链区块，展示 height // 100、height=100 的纪元边界，
以及休眠分支区块只计算自身 epoch、不生成主链快照。摘要、摘要投票、引种和
大断层事件均未实现；原始区块仍保留在内存主链中。
"""

from dataclasses import replace

from block_model import Block, PoiRecord, Proposal, TestCase
from block_validator import MIN_POI_TOKENS, validate_block
from chain_store import ChainStore
from crypto_key import generate_miner_keypair, sign_block_payload
from epoch_manager import EpochManager
from mock_tokenizer import MOCK_TOKENIZER_ID, count_poi_tokens


def make_block(store: ChainStore, private_key: bytes, public_key: bytes, height: int | None = None) -> Block:
    """构造一个无交易、带正确 epoch 和 ECDSA 签名的测试区块。"""
    target_height = store.height + 1 if height is None else height
    prompt = "design a deterministic extension with epoch sandbox tests"
    output = "reasoning token " * (MIN_POI_TOKENS + 2)
    counts = count_poi_tokens(prompt, output)
    proposal = Proposal(f"epoch-feature-{target_height}", "pure extension", "(+ 1 2)", (TestCase("(+ 1 2)", 3),))
    poi = PoiRecord("manual", prompt, output, MOCK_TOKENIZER_ID,
                    counts.standard_input_tokens, counts.standard_output_tokens, counts.standard_total_tokens)
    unsigned = Block(target_height, store.tip.block_hash, "epoch-miner", proposal, poi, miner_pubkey=public_key)
    return replace(unsigned, signature_bytes=sign_block_payload(private_key, unsigned.canonical_bytes()))


def main() -> None:
    store = ChainStore()
    private_key, public_key = generate_miner_keypair()
    boundary_report = None
    for height in range(1, 103):
        block = make_block(store, private_key, public_key, height)
        result = validate_block(block, store)
        if not result.accepted:
            raise RuntimeError(result)
        store.append_main(block)
        if height in (1, 99, 100, 101, 102):
            print(f"height={height}, epoch={block.epoch}, hash={block.block_hash[:12]}...")
        if height == 100:
            boundary_report = store.epoch_manager.get_epoch_snapshot(0)

    print("\n纪元快照列表：")
    for snapshot in store.epoch_manager.snapshots():
        print(
            f"epoch={snapshot.epoch_number}, range={snapshot.start_height}-{snapshot.end_height}, "
            f"blocks={len(snapshot.block_hashes)}, archived={snapshot.archived}"
        )
    print("\nheight=100 触发的 epoch0 归档：", boundary_report.archived if boundary_report else None)

    # 休眠区块本身仍由 Block 自动计算 epoch=1，但不调用 append_main，
    # 因此不会改变已有纪元快照列表。为构造休眠示例，使用已知的 height=102 父哈希。
    sleeping = make_block(store, private_key, public_key, 103)
    before = store.epoch_manager.snapshots()
    store.add_sleeping_branch(sleeping)
    print("\n休眠分支区块：height=", sleeping.height, "epoch=", sleeping.epoch)
    print("休眠分支写入后快照数量：", len(store.epoch_manager.snapshots()), "（此前：", len(before), "）")
    print("原始区块未删除；本阶段未实现 LLM 摘要、摘要投票、引种提案和大断层事件。")


if __name__ == "__main__":
    main()
