"""StratumGenesis ECDSA 区块签名流程演示。"""

from dataclasses import replace

from block_model import Block, PoiRecord, Proposal, TestCase
from block_validator import MIN_POI_TOKENS, validate_block
from chain_store import ChainStore
from crypto_key import generate_miner_keypair, sign_block_payload
from mock_tokenizer import MOCK_TOKENIZER_ID, count_poi_tokens


def make_unsigned(store: ChainStore, public_key: bytes, feature: str, specification: str = "pure extension") -> Block:
    prompt = "design a deterministic signed extension with sandbox tests"
    output = "reasoning token " * (MIN_POI_TOKENS + 3)
    counts = count_poi_tokens(prompt, output)
    proposal = Proposal(feature, specification, "(+ 1 2)", (TestCase("(+ 1 2)", 3),))
    poi = PoiRecord("manual", prompt, output, MOCK_TOKENIZER_ID,
                    counts.standard_input_tokens, counts.standard_output_tokens, counts.standard_total_tokens)
    return Block(1, store.tip.block_hash, "miner-A", proposal, poi, miner_pubkey=public_key)


def sign(block: Block, private_key: bytes) -> Block:
    """只对无 signature 字段的 canonical_bytes 签名，再构造最终区块。"""
    return replace(block, signature_bytes=sign_block_payload(private_key, block.canonical_bytes()))


def show(label: str, result) -> None:
    print(f"{label}: accepted={result.accepted}, stage={result.stage}, code={result.error_code}")


def main() -> None:
    store = ChainStore()
    private_a, public_a = generate_miner_keypair()
    private_b, public_b = generate_miner_keypair()

    unsigned = make_unsigned(store, public_a, "signed-feature")
    valid = sign(unsigned, private_a)
    show("正常签名", validate_block(valid, store))

    tampered = replace(valid, proposal=replace(valid.proposal, specification="tampered"))
    show("篡改区块字段", validate_block(tampered, store))

    wrong_key_signature = sign_block_payload(private_b, unsigned.canonical_bytes())
    mismatched = replace(unsigned, signature_bytes=wrong_key_signature)
    show("B私钥+A公钥", validate_block(mismatched, store))

    print("A公钥长度：", len(public_a), "B公钥长度：", len(public_b))
    print("注意：本演示使用标准库外 ecdsa 包，但不实现生产级密钥托管或网络身份认证。")


if __name__ == "__main__":
    main()
