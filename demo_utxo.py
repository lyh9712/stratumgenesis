"""StratumGenesis UTXO 内存账本端到端演示。"""

from dataclasses import replace

from block_model import Block, PoiRecord, Proposal, TestCase
from block_validator import MIN_POI_TOKENS, validate_block
from chain_store import ChainStore
from crypto_key import generate_miner_keypair, sign_block_payload
from mock_tokenizer import MOCK_TOKENIZER_ID, count_poi_tokens
from utxo_ledger import UTXOValidationError
from utxo_model import Transaction, UTXO, make_signed_transaction


def make_block(store: ChainStore, public_key: bytes, feature: str, transactions=()) -> Block:
    prompt = "design a deterministic extension with sandbox tests"
    output = "reasoning token " * 12
    counts = count_poi_tokens(prompt, output)
    proposal = Proposal(feature, "pure extension", "(+ 1 2)", (TestCase("(+ 1 2)", 3),))
    poi = PoiRecord("manual", prompt, output, MOCK_TOKENIZER_ID,
                    counts.standard_input_tokens, counts.standard_output_tokens, counts.standard_total_tokens)
    unsigned = Block(store.height + 1, store.tip.block_hash, "miner", proposal, poi,
                     miner_pubkey=public_key, transactions=transactions)
    return replace(unsigned, signature_bytes=sign_block_payload(MINER_PRIVATE_KEYS[public_key], unsigned.canonical_bytes()))


MINER_PRIVATE_KEYS: dict[bytes, bytes] = {}


def main() -> None:
    store = ChainStore()
    miner_a_private, miner_a_public = generate_miner_keypair()
    miner_b_private, miner_b_public = generate_miner_keypair()
    MINER_PRIVATE_KEYS.update({miner_a_public: miner_a_private, miner_b_public: miner_b_private})

    block1 = make_block(store, miner_a_public, "miner-A-feature")
    print("height=1 校验：", validate_block(block1, store))
    store.append_main(block1)
    reward = next(item for item in store.utxo_ledger.snapshot() if item.pubkey == miner_a_public)
    print("A 挖矿奖励：", reward.amount, "A余额：", store.utxo_ledger.get_balance(miner_a_public))

    tx = make_signed_transaction(miner_a_private, [reward], [(miner_b_public, 40), (miner_a_public, 60)])
    block2 = make_block(store, miner_a_public, "transfer-A-to-B", (tx,))
    print("正常转账校验：", validate_block(block2, store))
    store.append_main(block2)
    print("转账后 A余额：", store.utxo_ledger.get_balance(miner_a_public))
    print("转账后 B余额：", store.utxo_ledger.get_balance(miner_b_public))

    # 同一个已消费 reward 再次作为输入，构造另一笔签名交易；第 6 步会拒绝双花。
    double_spend = make_signed_transaction(miner_a_private, [reward], [(miner_b_public, 100)])
    bad_block = make_block(store, miner_a_public, "double-spend", (double_spend,))
    bad_result = validate_block(bad_block, store)
    print("双花校验：", bad_result)
    print("双花后主链高度：", store.height)

    # 休眠分支不调用 apply_block_rewards/apply_transactions，账本余额保持不变。
    print("注意：UTXO余额仅为链内实验记账，不参与投票权重，也无现实货币价值。")


if __name__ == "__main__":
    main()
