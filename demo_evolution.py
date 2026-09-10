"""StratumGenesis 语言真实演化演示。

本脚本用完整校验流水线演示「提案真的改变语言」：
1. 创世链上只有内核 +，调用未激活原语 (- 10 3) 报 NameError；
2. 矿工 A 提交激活 "-" 的提案，通过 8 步校验（正测试：(- 10 3)->7；
   负测试：旧语言下 (- 10 3) 失败）后上链，语言升级；
3. 后续区块即可直接使用减法原语；
4. 历史块按当时的语言快照版本化重放，结果与当年一致；
5. 再激活 "list"，语言继续演化；
6. 重复激活 "-" 被校验拒绝；
7. 打印语言演化时间线。

运行：python demo_evolution.py
"""

from __future__ import annotations

from dataclasses import replace

from block_model import Block, PoiRecord, Proposal, TestCase
from block_validator import MIN_POI_TOKENS, validate_block
from chain_store import ChainStore
from crypto_key import generate_miner_keypair, sign_block_payload
from mock_tokenizer import MOCK_TOKENIZER_ID, count_poi_tokens
from novscript import run_sandbox
from novscript.language import LanguageSnapshot


def make_extension_block(
    store: ChainStore,
    private_key: bytes,
    public_key: bytes,
    *,
    feature_name: str,
    description: str,
    activation: tuple[str, ...],
    demo: str,
    tests: tuple[TestCase, ...],
    proposer: str = "矿工·演化者",
) -> Block:
    """构造一个激活指定原语的候选区块（含合法 PoI、真实 ECDSA 签名）。"""
    prompt = f"design a NovScript extension named {feature_name}: {description}"
    output = demo + " " + " ".join(t.program for t in tests) + " " + "reasoning token " * (MIN_POI_TOKENS + 3)
    counts = count_poi_tokens(prompt, output)
    proposal = Proposal(feature_name, description, demo, tests)
    poi = PoiRecord(
        "manual-mock", prompt, output, MOCK_TOKENIZER_ID,
        counts.standard_input_tokens, counts.standard_output_tokens, counts.standard_total_tokens,
    )
    unsigned = Block(store.height + 1, store.tip.block_hash, proposer, proposal, poi,
                     miner_pubkey=public_key, activation=activation)
    return replace(unsigned, signature_bytes=sign_block_payload(private_key, unsigned.canonical_bytes()))


def main() -> None:
    print("=" * 64)
    print("StratumGenesis · 语言真实演化演示")
    print("=" * 64)

    store = ChainStore()
    private_key, public_key = generate_miner_keypair()

    # 1) 创世语言：只有内核 +。
    print("\n[1] 创世语言（仅内核 +）")
    result = run_sandbox("(- 10 3)", registry=store.language_registry)
    print(f"    调用未激活原语 (- 10 3) -> ok={result.ok}, error={result.error_type}（期望 NameError）")
    assert not result.ok and result.error_type == "NameError"
    snapshot0 = store.current_language_snapshot()
    print(f"    创世语言快照 height={snapshot0.height}, 特性={sorted(snapshot0.active_features)}")

    # 2) 矿工 A 提交激活 "-" 的提案。
    print("\n[2] 矿工 A 提交「激活减法原语 -」提案")
    block_sub = make_extension_block(
        store, private_key, public_key,
        feature_name="减法原语",
        description="激活整数减法原语 -，扩展语言算术能力",
        activation=("-",),
        demo="(- 10 3)",
        tests=(TestCase("(- 10 3)", 7),),
    )
    result = validate_block(block_sub, store)
    print(f"    8 步校验 -> accepted={result.accepted}, stage={result.stage}, checked={result.checked_stages}")
    assert result.accepted, result
    store.append_main(block_sub)
    snapshot1 = store.current_language_snapshot()
    print(f"    区块 height={block_sub.height} 上链，语言快照特性={sorted(snapshot1.active_features)}")

    # 3) 语言已升级：后续区块可直接使用 -。
    print("\n[3] 语言升级后直接使用减法")
    result = run_sandbox("(- 10 3)", registry=store.language_registry)
    print(f"    (- 10 3) -> value={result.value}（期望 7）")
    assert result.ok and result.value == 7

    # 4) 版本化重放：按 height=1 的语言快照重放该块 demo，与当年结果一致。
    print("\n[4] 历史块版本化重放")
    replay_registry = LanguageSnapshot.build_registry(snapshot1)
    replay = run_sandbox(block_sub.proposal.demo_code, registry=replay_registry)
    print(f"    用 height={snapshot1.height} 的语言快照重放 demo -> value={replay.value}（期望 7，与上链时一致）")
    assert replay.ok and replay.value == 7
    # 用创世快照（无 -）重放必须失败：证明当时确实依赖新原语。
    genesis_registry = LanguageSnapshot.build_registry(snapshot0)
    genesis_replay = run_sandbox(block_sub.proposal.demo_code, registry=genesis_registry)
    print(f"    用创世快照重放同一 demo -> ok={genesis_replay.ok}, error={genesis_replay.error_type}（期望失败）")
    assert not genesis_replay.ok

    # 5) 再激活列表原语族（list + head），语言持续演化。
    print("\n[5] 矿工 A 提交「激活列表原语族 list/head」提案")
    block_list = make_extension_block(
        store, private_key, public_key,
        feature_name="列表原语",
        description="激活列表构造原语 list 与取头原语 head，引入嵌套对数据结构",
        activation=("list", "head"),
        demo="(head (list 1 2 3))",
        tests=(TestCase("(head (list 1 2 3))", 1),),
    )
    result = validate_block(block_list, store)
    print(f"    8 步校验 -> accepted={result.accepted}, stage={result.stage}")
    assert result.accepted, result
    store.append_main(block_list)
    snapshot2 = store.current_language_snapshot()
    print(f"    区块 height={block_list.height} 上链，语言快照特性={sorted(snapshot2.active_features)}")
    result = run_sandbox("(head (list 7 8 9))", registry=LanguageSnapshot.build_registry(snapshot2))
    print(f"    组合使用 list/head 原语 (head (list 7 8 9)) -> value={result.value}（期望 7）")
    assert result.ok and result.value == 7

    # 6) 重复激活 "-" 被拒绝。
    print("\n[6] 尝试重复激活「-」")
    block_dup = make_extension_block(
        store, private_key, public_key,
        feature_name="重复减法原语",
        description="再次激活减法原语 -（应被拒绝）",
        activation=("-",),
        demo="(- 10 3)",
        tests=(TestCase("(- 10 3)", 7),),
    )
    result = validate_block(block_dup, store)
    print(f"    8 步校验 -> accepted={result.accepted}, stage={result.stage}, code={result.error_code}")
    assert not result.accepted and result.stage == "activation" and result.error_code == "DUPLICATE_FEATURE"
    store.add_sleeping_branch(block_dup)
    branch_features = store.branch_active_features(block_dup.parent_hash or "orphan")
    print(f"    被拒区块进入休眠分支；分支自身激活集={sorted(branch_features)}（不污染链级注册表）")
    assert store.language_registry.snapshot() == frozenset({"-", "list", "head"})

    # 7) 语言演化时间线。
    print("\n[7] 语言演化时间线")
    timeline = []
    for block in store.main_chain():
        snapshot = store.language_snapshot_at(block.height)
        timeline.append((block.height, len(snapshot.active_features) if snapshot else 0))
    for height, count in timeline:
        print(f"    height={height:<4} 语言特性数={count}")
    print(f"\n最终链高={store.height}，已激活特性={sorted(store.language_registry.snapshot())}")
    print("\n演示完成：提案激活的原语真实进入解释器，历史块按当时语言版本重放，语言在链上真实演化。")


if __name__ == "__main__":
    main()
