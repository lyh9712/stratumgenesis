"""StratumGenesis v0.3 · 并行线 C —— 离线链分析器与实验指标。

把「语言演化实验」的链数据变成可复现、可发布的指标，对应设计白皮书
§13（学术价值）与 §14.5（长期：定期导出完整链数据、撰写实验报告）。

用法
----
    python analyze_chain.py <存档或导出 JSON> [--verify] [--by-model] [--json out.json]
    python analyze_chain.py --synthetic [--by-model] [--json out.json]
    python analyze_chain.py [--by-model] [--json out.json]   # 无存档：提示 + 内存合成链演示，退出码 0

无位置参数时的行为（已被监督者接受，自动化调用方请勿当作「参数被忽略」）：
分析器打印一行中文提示，改用内存合成链（跨 3 个纪元）跑完整指标，退出码仍为 0。
区分演示与真实数据看 source.label（"合成链（无存档模式）"）与 source.path。

[警示] 无参回退与 --synthetic 需要本机 ecdsa 可用才能 exit 0（合成链构造要走
crypto_key 真实签名）。缺少 ecdsa 时打印中文可执行提示（pip install ecdsa /
用已装 ecdsa 的解释器如 py -3.13）并以非零码退出，绝不打印原始 ImportError 英文栈。

--by-model：跨 AI 创造力指标（每个参与者带自己的 AI 出提案的比较实验）。
数据全部来自 blocks[].poi.model_metadata + blocks[].activation + height // 100，
零后端改动；语言类指标仅主链，接受/产出统计含休眠分支（详见 EXPERIMENT_METRICS.md）。

签名重验
--------
--verify 统一走项目既有 crypto_key.verify_block_signature（与 persistence.load_state
同一实现来源），本脚本**不再内嵌任何手写 ECDSA / P-256 实现**。本机缺少 ecdsa 依赖时，
分析器打印「本机缺少 ecdsa 依赖，跳过签名重验」，并在 --json 的 schema 中标记
ecdsa_backend="unavailable"、signature_verification="skipped_no_ecdsa"，同时写入
warnings；绝不用手写实现冒充真实验签。

指标口径（关键约束）
--------------------
全部指标只从 blocks[] 的稳定字段推导：
    blocks[].activation / blocks[].height / blocks[].epoch
    blocks[].poi.standard_* / blocks[].poi.model_metadata / blocks[].transactions
    blocks[].proposer / blocks[].miner_pubkey_b64 / blocks[].block_hash
纪元粒度：epoch = height // 100（与 epoch_manager.EPOCH_BLOCKS 一致）。

刻意**不依赖**以下字段（语义正在 v0.3 变更中，且都能由 blocks[] 重新推导）：
    epochs[].active_features / current_active_features / language_features
    summary_chain / miner_label / reason

每个指标的定义、计算口径、来源字段与已知局限见 EXPERIMENT_METRICS.md。

并行开发边界
------------
- 只新增文件：本脚本、EXPERIMENT_METRICS.md、tests/test_analyze_chain.py；
- 不修改、不删除任何既有文件；不读写 data/ 与 data/chain_v1.json；
- 不起 HTTP 服务（127.0.0.1:28417 归其他并行线），不跑全量测试；
- 纯标准库 + 项目既有模块，无第三方库，无联网。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from dataclasses import replace
from statistics import mean, median
from typing import Any

EXPECTED_FORMAT_VERSION = "chain-v2"   # 与 persistence.FORMAT_VERSION 对齐
EPOCH_BLOCKS = 100                     # 与 epoch_manager.EPOCH_BLOCKS 对齐
ANALYZER_NAME = "analyze_chain.py"
ANALYZER_SCHEMA_VERSION = 1

# metrics.json 的公开契约版本（由 `export_public.py --metrics` 落盘，供前端直接消费）。
# 递增规则：只增不减。metrics.json 顶层键名（PUBLIC_METRICS_KEYS）发生增/删/改名，
# 或任一既有键的值语义发生变化时 +1，并在 EXPERIMENT_METRICS.md 记录变更。
# ⚠️ 它与 report["schema"]["schema_version"]（分析器报告口径版本）是两条独立的
# 版本线：前者描述「公开文件契约」，后者描述「指标计算口径」，不要混用。
METRICS_SCHEMA_VERSION = 1

# metrics.json 顶层键名契约（顺序即 build_metrics 的写出顺序；UI 可按名取值）。
PUBLIC_METRICS_KEYS = (
    "schema_version", "generated_by", "readonly", "chain_height",
    "schema", "source", "chain", "language_evolution", "chain_consensus",
    "ledger", "poi", "by_model", "field_provenance", "warnings",
)

BACKEND_PYTHON_ECDSA = "python-ecdsa"          # ecdsa 可用：走 crypto_key.verify_block_signature
BACKEND_UNAVAILABLE = "unavailable"            # 本机缺少 ecdsa：不验签，仅标注
VERIFY_SKIPPED_NO_ECDSA = "skipped_no_ecdsa"   # --json 中 signature_verification 的取值
VERIFY_ENABLED = "enabled"

# 缺 ecdsa 时的中文可执行提示（无参回退 / --synthetic / 验签共用）。
MISSING_ECDSA_HINT = (
    "本机缺少 ecdsa 依赖：请先执行 `python -m pip install ecdsa`，"
    "或用已安装 ecdsa 的解释器运行（例如 `py -3.13`；无参回退与 --synthetic "
    "需要 ecdsa 可用才能正常演示并以 exit 0 结束）。"
)

# 引种留存率的样本量警示阈值：低于该值只出「估计」，并显式提示谨慎解读。
SAMPLE_SIZE_WARNING_THRESHOLD = 5


def detect_signature_backend() -> str:
    """探测签名重验后端；不注入 sys.modules，不引入任何手写 ECDSA 实现。

    只用真实 import 判定：本机有 ecdsa 时返回 python-ecdsa（crypto_key 与
    persistence 同一实现来源），缺失时返回 unavailable，由调用方明确标注跳过。
    """
    try:
        import ecdsa  # noqa: F401
    except Exception:  # noqa: BLE001
        return BACKEND_UNAVAILABLE
    return BACKEND_PYTHON_ECDSA


ECDSA_BACKEND = detect_signature_backend()


def require_ecdsa_for_synthetic() -> None:
    """构造/重放合成链前检查 ecdsa 可用性（构造要走 crypto_key 真实签名）。

    缺失时抛 AnalysisError（含中文可执行提示），由 CLI 打印 [错误] 并以非零码
    退出；绝不让 import crypto_key 的原始 ImportError 英文栈直接冒到用户面前。
    纯函数、可单测（测试里通过临时改写 ECDSA_BACKEND 模拟缺失）。
    """
    if ECDSA_BACKEND == BACKEND_UNAVAILABLE:
        raise AnalysisError(MISSING_ECDSA_HINT)

DERIVED_FROM = (
    "blocks[].activation", "blocks[].height",
    "blocks[].poi.standard_input_tokens", "blocks[].poi.standard_output_tokens",
    "blocks[].poi.standard_total_tokens", "blocks[].poi.standard_tokenizer",
    "blocks[].poi.model_metadata",
    "blocks[].transactions", "blocks[].proposer", "blocks[].miner_pubkey_b64",
    "blocks[].block_hash",
    "sleeping_branches[].branch_id", "sleeping_branches[].blocks[]",
    "miners[].public_key_b64", "miners[].label", "rejection_reasons",
)
AVOIDED_FIELDS = (
    "blocks[].epoch",                  # 只用 height // EPOCH_BLOCKS 重新推导，不信任存档值
    "epochs[].active_features",
    "current_active_features",
    "language_features",
    "blocks[].proposal.kind",          # 已解析但未纳入任何指标
    "blocks[].proposal.feature_id",
    "summary_chain", "miner_label", "reason",
)


# ============================================================================
# 1) 存档读取
# ============================================================================
class AnalysisError(Exception):
    """存档损坏 / 格式版本不匹配 / 必要字段缺失；信息为中文，供 CLI 直接展示。"""


def load_archive(path: str) -> dict:
    """读取 chain-v2 存档/导出 JSON，仅做结构与版本校验（不做逐块重验）。"""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as error:
        raise AnalysisError(f"存档文件无法读取：{path}（{error}）") from error
    except json.JSONDecodeError as error:
        raise AnalysisError(f"存档 JSON 已损坏，无法解析：{path}（{error}）") from error
    if not isinstance(data, dict):
        raise AnalysisError(f"存档根节点必须是 JSON 对象：{path}")
    version = data.get("format_version")
    if version != EXPECTED_FORMAT_VERSION:
        raise AnalysisError(
            f"存档格式版本不匹配：期望 {EXPECTED_FORMAT_VERSION}，实际 {version!r}（{path}）。"
            "本文件未被修改；如需分析旧格式样本，请先用 "
            "`python server.py --archive <新路径> --fresh` 生成一份 chain-v2 存档后再分析。"
        )
    if "blocks" not in data:
        raise AnalysisError(f"存档缺少必要字段 'blocks'：{path}")
    return data


# ============================================================================
# 2) 存档条目的规范化视图（只取稳定字段）
# ============================================================================
def _decode_b64(value: Any) -> str | None:
    """b64 -> hex 字符串；输入非法时返回 None（分析器不做校验，只做尽力映射）。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        return base64.b64decode(value).hex()
    except (ValueError, TypeError):
        return None


def _miner_labels(miners: Any) -> dict[str, str]:
    """公钥(hex) -> 标签。

    存档里矿工公钥是 base64（miners[].public_key_b64），而 UTXO 账本与区块视图
    统一使用原始 hex，因此这里同时登记两种键，报告与账本才能对齐到同一矿工名。
    """
    labels: dict[str, str] = {}
    if not isinstance(miners, list):
        return labels
    for entry in miners:
        if not isinstance(entry, dict):
            continue
        raw_b64 = entry.get("public_key_b64")
        if not isinstance(raw_b64, str) or not raw_b64:
            continue
        label = entry.get("label")
        label = str(label) if label else f"矿工({raw_b64[:8]}…)"
        labels[raw_b64] = label
        key_hex = _decode_b64(raw_b64)
        if key_hex is not None:
            labels[key_hex] = label
    return labels


def _label_of(key: Any, labels: dict[str, str]) -> str:
    """矿工公钥（hex 或 b64）-> 显示用标签。"""
    if not isinstance(key, str) or not key:
        return "未知矿工"
    return labels.get(key, f"矿工({key[:8]}…)")


def _block_view(entry: Any, where: str) -> dict:
    """把存档里的一个区块条目规范化成分析视图。

    纪元一律按 height // EPOCH_BLOCKS 重新计算，不信任 blocks[].epoch；
    刻意不读取 epochs[].active_features / current_active_features /
    language_features 等派生字段（见 EXPERIMENT_METRICS.md「刻意避开的字段」）。
    """
    if not isinstance(entry, dict):
        raise AnalysisError(f"{where} 存在非对象的区块条目，存档已损坏")
    height = entry.get("height")
    if not isinstance(height, int) or height < 0:
        raise AnalysisError(f"{where} 区块缺少非负整数 'height'，存档已损坏")
    poi = entry.get("poi")
    if not isinstance(poi, dict):
        raise AnalysisError(f"{where} height={height} 的 'poi' 不是对象，存档已损坏")
    try:
        total_tokens = int(poi.get("standard_total_tokens") or 0)
        input_tokens = int(poi.get("standard_input_tokens") or 0)
        output_tokens = int(poi.get("standard_output_tokens") or 0)
    except (TypeError, ValueError) as error:
        raise AnalysisError(
            f"{where} height={height} 的 poi.standard_*_tokens 不是整数，存档已损坏"
        ) from error
    activation = entry.get("activation")
    if activation is None:
        activation = []
    if not isinstance(activation, list):
        raise AnalysisError(f"{where} height={height} 的 'activation' 不是数组，存档已损坏")
    transactions = entry.get("transactions")
    if transactions is None:
        transactions = []
    if not isinstance(transactions, list):
        raise AnalysisError(f"{where} height={height} 的 'transactions' 不是数组，存档已损坏")
    proposal = entry.get("proposal")
    if not isinstance(proposal, dict):
        proposal = {}
    return {
        "height": height,
        "epoch": height // EPOCH_BLOCKS,          # 由高度重新推导，权威口径
        "block_hash": str(entry.get("block_hash") or ""),
        "miner_pubkey_b64": str(entry.get("miner_pubkey_b64") or ""),
        "proposer": str(entry.get("proposer") or ""),
        "proposal_kind": str(proposal.get("kind") or ""),
        "activation": [str(item) for item in activation],
        "model_metadata": str(poi.get("model_metadata") or ""),
        "poi_total_tokens": total_tokens,
        "poi_input_tokens": input_tokens,
        "poi_output_tokens": output_tokens,
        "tokenizer": str(poi.get("standard_tokenizer") or ""),
        "transactions": transactions,
    }


# ============================================================================
# 3) 合成链生成器：只读复用既有模块，构造跨 3 个纪元的内存主链
# ============================================================================
# 场景设计（用于演示「引种 / 失忆」指标，见 EXPERIMENT_METRICS.md 运行示例）：
#   纪元 0 (height  0..99)  激活 -、list/head  -> 历史首次，记为「新激活」
#   纪元 1 (height 100..199) 首块 activation 含 -  -> 更早纪元出现过，记为「引种」
#                                    其后激活 *      -> 「新激活」
#   纪元 2 (height 200..)   首块不引种              -> 制造「失忆」
# 全程走既有 ChainStore.append_main 的真实追加路径（含纪元首块重置），
# 因此生成的 JSON 与 server.py 导出的 chain-v2 格式完全一致。
#
# 模型身份（--by-model 演示剧情，v0.3 线③扩展）：
#   矿工·A 挂 synthetic-model-a：激活 -  （纪元 0），纪元 1 首块被其引种 -> 「A 的特性被引种」
#   矿工·B 挂 synthetic-model-b：激活 list/head（纪元 0）、*（纪元 1），全被遗忘 -> 「B 的被遗忘」
#   矿工·C 挂 synthetic-model-c：只出普通块，无首次激活特性（演示单模型退化/n/a 路径）
# ============================================================================
_SYNTHETIC_MINERS = (("矿工·A",),)  # 占位；实际密钥在 build_synthetic_chain 内生成


# 矿工 -> 模型身份的确定性映射（每个参与者带自己的 AI）。
SYNTHETIC_MODELS = {
    "矿工·A": "synthetic-model-a",
    "矿工·B": "synthetic-model-b",
    "矿工·C": "synthetic-model-c",
}


def _synth_poi(feature_id: str, description: str, demo: str, tests, pad: int = 3,
               model_metadata: str = "synthetic-mock") -> Any:
    """生成一条 mock 标准分词的 PoI 记录（不依赖真实 LLM）。"""
    import block_model
    import mock_tokenizer

    prompt = f"design a NovScript extension named {feature_id}: {description}"
    output = demo + " " + " ".join(t.program for t in tests) + " reasoning token " * pad
    counts = mock_tokenizer.count_poi_tokens(prompt, output)
    return block_model.PoiRecord(
        model_metadata, prompt, output, mock_tokenizer.MOCK_TOKENIZER_ID,
        counts.standard_input_tokens, counts.standard_output_tokens, counts.standard_total_tokens,
    )


def _synth_block(store, private_key: bytes, public_key: bytes, label: str,
                 feature_id: str, description: str, demo: str, tests,
                 activation: tuple[str, ...], pad: int = 3,
                 model_metadata: str = "synthetic-mock") -> Any:
    """构造并签名一个候选区块（含合法 PoI），返回已签名 Block。"""
    import block_model
    import crypto_key

    poi = _synth_poi(feature_id, description, demo, tests, pad, model_metadata)
    proposal = block_model.Proposal(feature_id, description, demo, tests, kind="extension")
    unsigned = block_model.Block(
        store.height + 1, store.tip.block_hash, label, proposal, poi,
        miner_pubkey=public_key, activation=activation,
    )
    return replace(unsigned, signature_bytes=crypto_key.sign_block_payload(
        private_key, unsigned.canonical_bytes()))


def build_synthetic_chain() -> dict:
    """构造跨 3 个纪元的合成主链（含 1 个休眠分支），返回 chain-v2 字典。

    只读复用既有模块：block_model / chain_store / crypto_key / mock_tokenizer /
    persistence.serialize_state。不启动 HTTP 服务，不读写 data/。
    """
    # 缺 ecdsa 时在这里就给出中文可执行提示（非零退出），而不是冒英文栈；
    # 必须在任何 import crypto_key 之前判定（crypto_key 顶层依赖 ecdsa）。
    require_ecdsa_for_synthetic()

    import block_model
    import chain_store
    import crypto_key
    import persistence

    store = chain_store.ChainStore()
    miners: dict[bytes, tuple[str, bytes]] = {}
    identities = []
    for label in ("矿工·A", "矿工·B", "矿工·C"):
        private_key, public_key = crypto_key.generate_miner_keypair()
        miners[public_key] = (label, private_key)
        identities.append((label, private_key, public_key))

    filler_demo = "(+ 1 2)"
    filler_tests = (block_model.TestCase("(+ 1 2)", 3),)

    # 确定性轮换：区块 i 由矿工 (i % 3) 签署，保证三个矿工都有产出；
    # 每个矿工带的模型身份固定（SYNTHETIC_MODELS），写入 poi.model_metadata。
    miner_cursor = 0

    def add(feature_id: str, description: str, demo: str, tests,
            activation: tuple[str, ...] = (), pad: int = 3) -> Any:
        nonlocal miner_cursor
        label, private_key, public_key = identities[miner_cursor % len(identities)]
        miner_cursor += 1
        block = _synth_block(store, private_key, public_key, label,
                             feature_id, description, demo, tests, activation, pad,
                             model_metadata=SYNTHETIC_MODELS[label])
        store.append_main(block)
        return block

    # ---- 纪元 0：历史首次激活 -、list/head（新激活） ----
    add("减法原语", "激活整数减法原语 -", "(- 10 3)",
        (block_model.TestCase("(- 10 3)", 7),), activation=("-",))
    add("列表原语族", "激活列表构造与取头原语", "(head (list 1 2 3))",
        (block_model.TestCase("(head (list 1 2 3))", 1),), activation=("list", "head"))
    while store.height < 99:
        add(f"填充原语-{store.height + 1}", "普通内核区块", filler_demo, filler_tests, pad=1)

    # ---- 纪元 1：首块引种 -（更早纪元出现过）+ 新激活 * ----
    add("纪元1引种减法", "在纪元 1 引种 -", "(- 10 3)",
        (block_model.TestCase("(- 10 3)", 7),), activation=("-",))
    add("乘法原语", "激活整数乘法原语 *", "(* 3 4)",
        (block_model.TestCase("(* 3 4)", 12),), activation=("*",))
    while store.height < 199:
        add(f"填充原语-{store.height + 1}", "普通内核区块", filler_demo, filler_tests, pad=1)

    # ---- 纪元 2：首块不引种，制造失忆 ----
    add(f"填充原语-{store.height + 1}", "普通内核区块（未引种，失忆）", filler_demo, filler_tests, pad=1)
    while store.height < 205:
        add(f"填充原语-{store.height + 1}", "普通内核区块", filler_demo, filler_tests, pad=1)

    # ---- 一个休眠分支：与主链同一父区块的落选候选（模型身份：矿工·B）----
    loser = _synth_block(
        store, identities[1][1], identities[1][2], identities[1][0],
        "乘法原语(落选)", "在纪元 2 引种 -", "(- 5 2)",
        (block_model.TestCase("(- 5 2)", 3),), activation=("-",),
        model_metadata=SYNTHETIC_MODELS["矿工·B"],
    )
    store.add_sleeping_branch(loser)

    rejection_reasons = {"%s" % (loser.parent_hash or "orphan"): "冲突投票落选，保存为休眠分支"}
    return persistence.serialize_state(store, miners, rejection_reasons)


# ============================================================================
# 4) 账本重建：从主链区块确定性重放（账本不直接序列化在存档中）
# ============================================================================
def rebuild_ledger(data: dict):
    """用既有 persistence.rebuild_store 重放主链，重建 UTXO 账本与纪元快照。

    persistence.py 明确说明账本与纪元快照不直接序列化，而是按既有规则从主链
    确定性重建，因此这里复用同一入口即可得到权威余额。
    返回 (store, 是否成功)；失败时返回 (None, False)，由调用方降级。
    """
    try:
        import persistence
        return persistence.rebuild_store(data.get("blocks", []), data.get("sleeping_branches", [])), True
    except Exception:  # noqa: BLE001 - 降级路径，具体原因记录在已知局限
        return None, False


def ledger_metrics(data: dict) -> dict:
    """账本指标：各矿工余额、总发行量、交易笔数。"""
    blocks = [_block_view(b, "blocks[]") for b in data["blocks"]]
    labels = _miner_labels(data.get("miners"))
    store, ok = rebuild_ledger(data)
    reward_amount = 100  # 与 utxo_ledger.UTXOLedger._reward_amount 一致

    tx_count = 0
    consumed = 0
    for entry in data.get("blocks", []):
        if not isinstance(entry, dict):
            continue
        txs = entry.get("transactions") or []
        tx_count += len(txs)
        for tx in txs:
            if isinstance(tx, dict):
                for utxo in tx.get("inputs") or []:
                    if isinstance(utxo, dict):
                        consumed += int(utxo.get("amount") or 0)

    if not ok:
        return {
            "method": "derived-fallback（账本重放失败，仅按奖励减消费估算）",
            "reward_amount": reward_amount,
            "rewarded_blocks": max(len(blocks) - 1, 0),
            "genesis_block_excluded_from_rewards": len(blocks) > 0,
            "total_supply": reward_amount * max(len(blocks) - 1, 0) - consumed,
            "rewards_issued": reward_amount * max(len(blocks) - 1, 0),
            "consumed_by_transactions": consumed,
            "balances": [],
            "unspent_utxos": 0,
            "transaction_count": tx_count,
            "warnings": ["UTXO 账本重放失败，余额与发行量为估算值"],
        }

    balances: dict[str, dict] = {}
    for utxo in store.utxo_ledger.snapshot():
        key = utxo.pubkey.hex()
        row = balances.setdefault(key, {
            "miner": _label_of(key, labels), "public_key_hex": key,
            "balance": 0, "unspent_utxos": 0,
        })
        row["balance"] += utxo.amount
        row["unspent_utxos"] += 1
    rows = sorted(balances.values(), key=lambda item: (-item["balance"], item["miner"]))
    total_supply = sum(item["balance"] for item in rows)

    # persistence.rebuild_store 显式跳过 height==0（创世块已由 ChainStore 初始化，
    # 不重放奖励），因此实际发放奖励的块数 = 主链块数 - 1（创世块）。
    rewarded_blocks = max(len(blocks) - 1, 0)
    return {
        "method": "replayed-via-persistence.rebuild_store（与存档加载同一重建路径）",
        "reward_amount": reward_amount,
        "rewarded_blocks": rewarded_blocks,
        "genesis_block_excluded_from_rewards": len(blocks) > 0,
        "total_supply": total_supply,
        "rewards_issued": reward_amount * rewarded_blocks,
        "consumed_by_transactions": consumed,
        "balances": rows,
        "unspent_utxos": sum(item["unspent_utxos"] for item in rows),
        "transaction_count": tx_count,
        "warnings": [],
    }


# ============================================================================
# 5) 指标计算
# ============================================================================
def _percentile(sorted_values: list[float], ratio: float) -> float:
    """线性插值分位数；空列表返回 0。"""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * ratio
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def _rate(numerator: int, denominator: int) -> float | None:
    """比率；分母为 0 时返回 None（区分「无样本」与「0%」）。"""
    return None if denominator == 0 else numerator / denominator


def _group_by_epoch(blocks: list[dict]) -> list[tuple[int, list[dict]]]:
    """按纪元号分组并各自按高度排序；保持纪元号升序。"""
    grouped: dict[int, list[dict]] = {}
    for block in blocks:
        grouped.setdefault(block["epoch"], []).append(block)
    return [
        (epoch_number, sorted(grouped[epoch_number], key=lambda item: item["height"]))
        for epoch_number in sorted(grouped)
    ]


def _count_values(mapping: Any) -> dict[str, int]:
    """把 {branch_id: reason} 统计成 {reason: 次数}，便于看拒绝原因分布。"""
    counts: dict[str, int] = {}
    if not isinstance(mapping, dict):
        return counts
    for key, reason in mapping.items():
        if not reason:
            continue
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: -item[1]))


def analyze_language(data: dict) -> dict:
    """语言演化指标。

    - 每个原语的首次激活高度（历史层 provenance）；
    - 每个纪元内「新激活 / 引种 / 未引种」三类清单与计数；
    - 每纪元开篇的可用原语集与相对上一纪元的「失忆集合」。

    判定口径（阶段 D 之前的临时语义，见 EXPERIMENT_METRICS.md）：
    「引种」= 该原语在更早纪元的 blocks[].activation 中出现过；
    「新激活」= 历史首次出现；「失忆集合」= 上一纪元末累计可用 - 本纪元开篇可用。
    全部指标只由 blocks[].activation + blocks[].height 推导。
    """
    blocks = [_block_view(b, "blocks[]") for b in data["blocks"]]

    first_activation: dict[str, dict] = {}
    cumulative: set[str] = set()          # 上一纪元末的累计可用集
    epoch_records: list[dict] = []

    for epoch_number, group in _group_by_epoch(blocks):
        available_at_open: set[str] = set()   # 该纪元开篇可用原语集
        newly_activated: set[str] = set()
        inoculated: set[str] = set()
        first_activation_heights: dict[str, int] = {}
        blocks_with_activation = 0

        seen_in_epoch: set[str] = set()
        for block in group:
            names = block["activation"]
            if not names:
                continue
            blocks_with_activation += 1
            # 该纪元第一处 activation 即开篇可用集：纪元作用域下语言从空起步，
            # 只有首块（或该纪元首个激活块）的 activation 能在纪元开篇生效。
            if not available_at_open:
                available_at_open = set(names)
            for name in names:
                if name in seen_in_epoch:
                    continue
                seen_in_epoch.add(name)
                first_activation_heights.setdefault(name, block["height"])
                if name in cumulative:
                    inoculated.add(name)
                else:
                    newly_activated.add(name)
                    first_activation[name] = {
                        "height": block["height"],
                        "epoch": epoch_number,
                        "proposer": block["proposer"],
                    }

        lost_memory = (cumulative - available_at_open) if epoch_number > 0 else set()
        epoch_records.append({
            "epoch": epoch_number,
            "start_height": epoch_number * EPOCH_BLOCKS,
            "end_height": group[-1]["height"],
            "blocks": len(group),
            "blocks_with_activation": blocks_with_activation,
            "available_at_open": sorted(available_at_open),
            "lost_memory": sorted(lost_memory),
            "lost_memory_count": len(lost_memory),
            "newly_activated": sorted(newly_activated),
            "newly_activated_count": len(newly_activated),
            "inoculated": sorted(inoculated),
            "inoculated_count": len(inoculated),
            "first_activation_heights": dict(sorted(first_activation_heights.items())),
            "cumulative_ever_active": sorted(cumulative | newly_activated),
        })
        cumulative |= newly_activated

    activation_events = sum(len(block["activation"]) for block in blocks)
    return {
        "first_activation": dict(sorted(first_activation.items())),
        "first_activation_count": len(first_activation),
        "epochs": epoch_records,
        "activation_events_total": activation_events,
        "cumulative_ever_active": sorted(cumulative),
        "total_inoculation_events": sum(r["inoculated_count"] for r in epoch_records),
        "total_new_activations": sum(r["newly_activated_count"] for r in epoch_records),
        "total_lost_memory_features": sum(r["lost_memory_count"] for r in epoch_records),
    }


def analyze_chain_consensus(data: dict) -> dict:
    """链与共识指标：总高度、每纪元块数、休眠分支、提案成功率、矿工产出与投票权重分布。"""
    blocks = [_block_view(b, "blocks[]") for b in data["blocks"]]
    labels = _miner_labels(data.get("miners"))
    branches_raw = data.get("sleeping_branches")
    branches_raw = branches_raw if isinstance(branches_raw, list) else []

    miner_stats: dict[str, dict] = {}
    weight_rows: dict[str, dict] = {}
    for block in blocks:
        key = block["miner_pubkey_b64"] or "unknown"
        label = _label_of(key, labels)
        stats = miner_stats.setdefault(key, {
            "miner": label, "public_key_b64": key, "blocks": 0,
            "standard_total_tokens": 0, "blocks_with_activation": 0,
            "registered_in_archive": key in labels,
            "genesis_blocks": 0,
        })
        stats["blocks"] += 1
        stats["standard_total_tokens"] += block["poi_total_tokens"]
        if block["activation"]:
            stats["blocks_with_activation"] += 1
        if block["height"] == 0:
            stats["genesis_blocks"] += 1
        weights = weight_rows.setdefault(key, {"miner": label, "voting_weight": 0})
        weights["voting_weight"] += block["poi_total_tokens"]

    epoch_records = []
    for epoch_number, group in _group_by_epoch(blocks):
        epoch_records.append({
            "epoch": epoch_number,
            "start_height": epoch_number * EPOCH_BLOCKS,
            "end_height": group[-1]["height"],
            "blocks": len(group),
            "expected_blocks": EPOCH_BLOCKS,
            "is_full": len(group) >= EPOCH_BLOCKS,
            "activations": sum(len(b["activation"]) for b in group),
        })

    branch_records = []
    branch_block_total = 0
    rejection_reasons = data.get("rejection_reasons")
    rejection_reasons = rejection_reasons if isinstance(rejection_reasons, dict) else {}
    for branch in branches_raw:
        if not isinstance(branch, dict):
            continue
        entries = branch.get("blocks")
        entries = entries if isinstance(entries, list) else []
        heights: list[int] = []
        activations: list[str] = []
        for entry in entries:
            view = _block_view(entry, "sleeping_branches[].blocks[]")
            branch_block_total += 1
            heights.append(view["height"])
            activations.extend(view["activation"])
        branch_id = str(branch.get("branch_id") or "")
        branch_records.append({
            "branch_id": branch_id,
            "blocks": len(entries),
            "min_height": min(heights) if heights else None,
            "max_height": max(heights) if heights else None,
            "epochs": sorted({h // EPOCH_BLOCKS for h in heights}),
            "activations": sorted(set(activations)),
            "rejection_reason": str(rejection_reasons.get(branch_id, "")),
        })

    proposals_on_main = max(len(blocks) - 1, 0)  # 创世块由节点初始化产生，不是提案
    rejected_proposals = len(branch_records)  # 每条休眠分支对应一次被否决的提案线
    total_proposals = proposals_on_main + rejected_proposals
    weight_list = sorted(
        (row["voting_weight"] for row in weight_rows.values() if row["voting_weight"] > 0),
        reverse=True,
    )
    total_weight = sum(weight_list)

    miners_sorted = sorted(
        miner_stats.values(),
        key=lambda item: (-item["standard_total_tokens"], item["miner"]),
    )
    for item in miners_sorted:
        item["share_of_total_tokens"] = (
            item["standard_total_tokens"] / total_weight if total_weight > 0 else None
        )
        item["avg_tokens_per_block"] = (
            item["standard_total_tokens"] / item["blocks"] if item["blocks"] else 0
        )
    weights_sorted = sorted(weight_rows.values(), key=lambda row: -row["voting_weight"])
    for row in weights_sorted:
        row["share"] = row["voting_weight"] / total_weight if total_weight > 0 else None

    return {
        "total_height": blocks[-1]["height"] if blocks else 0,
        "main_chain_blocks": len(blocks),
        "epoch_count": len(epoch_records),
        "epochs": epoch_records,
        "sleeping_branch_count": len(branch_records),
        "sleeping_branch_block_total": branch_block_total,
        "sleeping_branches": branch_records,
        "proposal_success_rate": {
            "proposals_submitted": total_proposals,
            "accepted_to_main": proposals_on_main,
            "rejected_to_branch": rejected_proposals,
            "branch_blocks_total": branch_block_total,
            "rate_main": _rate(proposals_on_main, total_proposals),
            "rate_sleeping_branch": _rate(rejected_proposals, total_proposals),
        },
        "miners": {
            "count": len(miners_sorted),
            "by_miner": miners_sorted,
        },
        "voting_weight_distribution": {
            "method": "sum(blocks[].poi.standard_total_tokens) 按 blocks[].miner_pubkey_b64 分组；仅主链计入",
            "total_weight": total_weight,
            "top_miner_share": (weight_list[0] / total_weight) if total_weight > 0 else None,
            "p50": _percentile(sorted(weight_list), 0.5),
            "p90": _percentile(sorted(weight_list), 0.9),
            "max": weight_list[0] if weight_list else 0,
            "min": weight_list[-1] if weight_list else 0,
            "rows": weights_sorted,
        },
        "rejection_reason_counts": _count_values(rejection_reasons),
    }


def analyze_poi(data: dict) -> dict:
    """PoI 工作量指标：词元总量、均值/最大/最小、分位数、分词器标识分布。"""
    blocks = [_block_view(b, "blocks[]") for b in data["blocks"]]
    totals = [block["poi_total_tokens"] for block in blocks]
    sorted_totals = sorted(totals)
    tokenizers: dict[str, int] = {}
    nonempty: dict[str, int] = {}
    for block in blocks:
        name = block["tokenizer"] or "(empty)"
        tokenizers[name] = tokenizers.get(name, 0) + 1
        if block["poi_total_tokens"] > 0:
            nonempty[name] = nonempty.get(name, 0) + 1

    main_only = [block["poi_total_tokens"] for block in blocks if block["height"] > 0]
    empty_blocks = sum(1 for value in totals if value == 0)
    return {
        "blocks": len(totals),
        "total_tokens": sum(totals),
        "mean": mean(totals) if totals else 0.0,
        "median": median(totals) if totals else 0.0,
        "max": max(totals) if totals else 0,
        "min": min(totals) if totals else 0,
        "p25": _percentile(sorted_totals, 0.25),
        "p75": _percentile(sorted_totals, 0.75),
        "p90": _percentile(sorted_totals, 0.9),
        "zero_token_blocks": empty_blocks,
        "main_chain_only": {
            "blocks": len(main_only),
            "total_tokens": sum(main_only),
            "mean": mean(main_only) if main_only else 0.0,
        },
        "input_tokens_total": sum(block["poi_input_tokens"] for block in blocks),
        "output_tokens_total": sum(block["poi_output_tokens"] for block in blocks),
        "tokenizer_usage": {
            name: {
                "blocks": tokenizers[name],
                "blocks_with_tokens": nonempty.get(name, 0),
            }
            for name in sorted(tokenizers)
        },
    }


# ============================================================================
# 5.5) 跨 AI 创造力指标（--by-model）
# ============================================================================
def _branch_views(data: dict) -> list[dict]:
    """收集休眠分支内全部区块的规范化视图（只读，顺序无关紧要）。"""
    views: list[dict] = []
    branches = data.get("sleeping_branches")
    if not isinstance(branches, list):
        return views
    for branch in branches:
        if not isinstance(branch, dict):
            continue
        entries = branch.get("blocks")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            views.append(_block_view(entry, "sleeping_branches[].blocks[]"))
    return views


def _model_id(block: dict) -> str:
    """模型身份归一化：空/缺失 -> "(未标注)"；创世锚点由调用方排除。"""
    return block["model_metadata"] or "(未标注)"


def analyze_by_model(data: dict) -> dict:
    """跨 AI 创造力指标：按 blocks[].poi.model_metadata 分组。

    数据来源纪律（与全文件一致）：
      - 语言类指标（留存率/半衰期/原语偏好/组合新颖度）只扫描主链
        blocks[].activation + height // 100；
      - 接受与产出统计含休眠分支（落选提案 = 休眠分支区块），创世块不计提案；
      - 模型身份来自 blocks[].poi.model_metadata，空值归入 "(未标注)"；
        创世块（model_metadata="genesis"）不构成任何模型身份。

    指标精确定义见 EXPERIMENT_METRICS.md §4.5（含样本量警示）。
    """
    main = [_block_view(block, "blocks[]") for block in data["blocks"]]
    branches = _branch_views(data)
    labels = _miner_labels(data.get("miners"))

    # 创世块不计入任何模型身份；其余主链非创世块 = 被接受的提案。
    main_proposals = [b for b in main if b["height"] > 0]

    model_ids: set[str] = set()
    for block in main_proposals + branches:
        model_ids.add(_model_id(block))

    # ---- 主链单遍扫描：首次激活 / 出现纪元 / 组合首见 / 矿工-模型关联 ----
    first_activation: dict[str, dict] = {}          # 原语 -> {height, epoch, model}
    present_epochs: dict[str, set[int]] = {}        # 原语 -> 出现过的纪元集合
    combo_first_seen: dict[tuple, dict] = {}        # 排序组合 -> {height, epoch, model}
    combo_first_by_model: dict[str, dict] = {}      # 模型 -> 组合 -> 该模型首用高度
    primitive_blocks: dict[str, dict[str, int]] = {}  # 模型 -> 原语 -> 出现块数
    activation_blocks: dict[str, int] = {}          # 模型 -> 含激活的主链块数
    miner_models: dict[str, set[str]] = {}          # 矿工(b64) -> 模型集合
    model_miners: dict[str, set[str]] = {}          # 模型 -> 矿工(b64) 集合

    for block in main:
        if block["height"] == 0:
            continue  # 创世锚点不构成模型身份
        model = _model_id(block)
        miner = block["miner_pubkey_b64"] or "unknown"
        miner_models.setdefault(miner, set()).add(model)
        model_miners.setdefault(model, set()).add(miner)
        names = block["activation"]
        if not names:
            continue
        activation_blocks[model] = activation_blocks.get(model, 0) + 1
        pref = primitive_blocks.setdefault(model, {})
        combo = tuple(sorted(set(names)))
        if combo not in combo_first_seen:
            combo_first_seen[combo] = {
                "height": block["height"], "epoch": block["epoch"], "model": model,
            }
        combo_first_by_model.setdefault(model, {}).setdefault(combo, block["height"])
        for name in sorted(set(names)):
            pref[name] = pref.get(name, 0) + 1
            present_epochs.setdefault(name, set()).add(block["epoch"])
            if name not in first_activation:
                first_activation[name] = {
                    "height": block["height"], "epoch": block["epoch"], "model": model,
                }

    last_epoch = main[-1]["epoch"] if main else 0

    # ---- 接受与产出（含休眠分支）----
    accepted: dict[str, int] = {mid: 0 for mid in model_ids}
    rejected: dict[str, int] = {mid: 0 for mid in model_ids}
    main_chain_blocks: dict[str, int] = {mid: 0 for mid in model_ids}
    for block in main_proposals:
        model = _model_id(block)
        accepted[model] = accepted.get(model, 0) + 1
        main_chain_blocks[model] = main_chain_blocks.get(model, 0) + 1
    for block in branches:
        model = _model_id(block)
        rejected[model] = rejected.get(model, 0) + 1

    # ---- 引种留存率 / 半衰期（仅主链）----
    features_by_model: dict[str, list[dict]] = {mid: [] for mid in model_ids}
    for primitive, info in sorted(first_activation.items()):
        model = info["model"]
        reintro_epochs = sorted(
            epoch for epoch in present_epochs.get(primitive, set()) if epoch > info["epoch"]
        )
        last_reintro = reintro_epochs[-1] if reintro_epochs else None
        span = (last_reintro - info["epoch"]) if reintro_epochs else 0
        epochs_since_first = max(last_epoch - info["epoch"], 0)
        silent = max(epochs_since_first - len(reintro_epochs), 0)
        features_by_model[model].append({
            "primitive": primitive,
            "first_height": info["height"],
            "first_epoch": info["epoch"],
            "reintroduction_count": len(reintro_epochs),
            "last_reintroduction_epoch": last_reintro,
            "span_epochs": span,
            "epochs_since_first": epochs_since_first,
            "silent_epochs_since_first": silent,
        })

    # ---- 组装每个模型的分区 ----
    models = []
    for model in sorted(model_ids):
        features = features_by_model.get(model, [])
        spans = [item["span_epochs"] for item in features]
        retention = {
            "features_first_activated": sorted(item["primitive"] for item in features),
            "feature_count": len(features),
            "reintroduction_events": sum(item["reintroduction_count"] for item in features),
            "half_life_epochs": median(spans) if spans else None,
            "mean_span_epochs": mean(spans) if spans else None,
            "span_epochs_min": min(spans) if spans else None,
            "span_epochs_max": max(spans) if spans else None,
            "features": features,
            "sample_size_warning": len(features) < SAMPLE_SIZE_WARNING_THRESHOLD,
        }
        pref = primitive_blocks.get(model, {})
        combos = combo_first_by_model.get(model, {})
        combo_records = []
        novel_count = 0
        for combo, first_height in sorted(combos.items(), key=lambda item: item[1]):
            first = combo_first_seen[combo]
            novel = first["model"] == model
            novel_count += int(novel)
            combo_records.append({
                "combination": list(combo),
                "first_activated_by_this_model_height": first_height,
                "globally_first_seen": novel,
                "global_first_height": first["height"],
                "global_first_model": first["model"],
            })
        miners_of_model = sorted(model_miners.get(model, set()))
        models.append({
            "model_id": model,
            "miners": [{
                "miner_pubkey_b64": miner,
                "label": _label_of(miner, labels),
            } for miner in miners_of_model],
            "miner_count": len(miners_of_model),
            "acceptance": {
                "proposals": accepted.get(model, 0) + rejected.get(model, 0),
                "accepted_to_main": accepted.get(model, 0),
                "rejected_to_sleeping_branch": rejected.get(model, 0),
                "main_chain_blocks": main_chain_blocks.get(model, 0),
                "sleeping_branch_blocks": rejected.get(model, 0),
                "acceptance_rate": _rate(
                    accepted.get(model, 0),
                    accepted.get(model, 0) + rejected.get(model, 0),
                ),
            },
            "retention": retention,
            "primitive_preference": {
                "activation_blocks": activation_blocks.get(model, 0),
                "primitives": dict(sorted(pref.items())),
                "top_primitives": sorted(pref.items(), key=lambda item: (-item[1], item[0])),
            },
            "combination_novelty": {
                "combinations_first_activated": combo_records,
                "novel_count": novel_count,
                "non_novel_count": len(combo_records) - novel_count,
            },
        })

    # ---- 分工与协作（矿工 <-> 模型 的挂载关系，仅主链）----
    miners_with_multiple_models = sorted(
        ({"miner_pubkey_b64": miner, "label": _label_of(miner, labels),
          "models": sorted(models_set)}
         for miner, models_set in miner_models.items() if len(models_set) > 1),
        key=lambda item: item["miner_pubkey_b64"],
    )
    models_with_multiple_miners = sorted(
        ({"model_id": model, "miners": sorted(miners_set),
          "miner_count": len(miners_set)}
         for model, miners_set in model_miners.items() if len(miners_set) > 1),
        key=lambda item: item["model_id"],
    )

    return {
        "derived_from": [
            "blocks[].poi.model_metadata", "blocks[].activation", "blocks[].height",
            "height // 100", "sleeping_branches[].blocks[].poi.model_metadata",
        ],
        "scope": {
            "language_metrics": "仅主链 blocks[].activation（休眠分支不参与留存/偏好/新颖度）",
            "acceptance": "主链非创世块（接受）+ 休眠分支区块（落选）；创世块不计提案",
            "collaboration": "仅主链矿工-模型挂载关系",
            "genesis_excluded": True,
        },
        "sample_size_warning_threshold": SAMPLE_SIZE_WARNING_THRESHOLD,
        "models": models,
        "collaboration": {
            "miners_with_multiple_models": miners_with_multiple_models,
            "multi_model_miner_count": len(miners_with_multiple_models),
            "models_used_by_multiple_miners": models_with_multiple_miners,
            "multi_miner_model_count": len(models_with_multiple_miners),
        },
    }


# ============================================================================
# 6) 可选完整性校验（逐块哈希 + ECDSA 签名重验）
# ============================================================================
def verify_archive(path: str) -> tuple[bool, str]:
    """用 persistence.load_state 做完整校验（逐块哈希 + ECDSA 签名）。

    验签统一走 crypto_key.verify_block_signature（persistence 已内部调用，同一实现
    来源）；本函数只负责入口选择与结果翻译，不内嵌任何手写 ECDSA。
    返回 (是否通过, 说明)。依赖不可用或校验失败都会返回 False 与中文说明。
    """
    if ECDSA_BACKEND == BACKEND_UNAVAILABLE:
        # 缺依赖是明确的「跳过」，不是「通过」也不是「失败」：绝不冒充真实验签。
        return False, "本机缺少 ecdsa 依赖，跳过签名重验"
    try:
        import persistence
    except Exception as error:  # noqa: BLE001
        return False, f"无法加载项目既有模块 persistence，无法执行完整性校验：{error}"
    try:
        data = persistence.load_state(path)
    except persistence.PersistenceError as error:
        return False, f"存档完整性校验未通过：{error}"
    block_count = len(data.get("blocks", []))
    branch_count = sum(
        len(branch.get("blocks") or [])
        for branch in data.get("sleeping_branches", [])
        if isinstance(branch, dict)
    )
    return True, (
        f"逐块哈希与 ECDSA 签名重验通过：{block_count} 个主链区块 + "
        f"{branch_count} 个休眠分支区块"
    )


# ============================================================================
# 7) 报告组装（控制台人类可读 + JSON 机器可读）
# ============================================================================
def _fmt(items: list[str], limit: int = 8) -> str:
    """紧凑列出原语清单，超出部分折叠为 …(+n)。"""
    if not items:
        return "—"
    shown = ", ".join(items[:limit])
    if len(items) > limit:
        shown += f" …(+{len(items) - limit})"
    return shown


def _fmt_rate(value: float | None) -> str:
    """比率格式化；None 表示无样本。"""
    return "无样本" if value is None else f"{value * 100:.1f}%"


def build_report(data: dict, *, source: str, source_label: str,
                 include_by_model: bool = False) -> tuple[dict, str]:
    """返回 (机器可读报告, 人类可读文本)。

    include_by_model=True 时，控制台文本追加「跨 AI 创造力指标」小节；
    机器可读 JSON 恒含 by_model 分区（键名稳定，供工具链直接消费）。
    """
    language = analyze_language(data)
    consensus = analyze_chain_consensus(data)
    ledger = ledger_metrics(data)
    poi = analyze_poi(data)
    by_model = analyze_by_model(data)
    warnings: list[str] = list(ledger.get("warnings", []))
    if ECDSA_BACKEND == BACKEND_UNAVAILABLE:
        warnings.append("本机缺少 ecdsa 依赖，跳过签名重验（schema.ecdsa_backend=unavailable）")
    if not data.get("blocks"):
        warnings.append("主链为空（无 blocks），所有指标为零值")
    for model in by_model["models"]:
        if model["retention"]["sample_size_warning"]:
            warnings.append(
                f"模型 {model['model_id']} 的首次激活特性样本量 < "
                f"{SAMPLE_SIZE_WARNING_THRESHOLD}，留存率/半衰期仅为估计，需谨慎解读"
            )

    report = {
        "schema": {
            "analyzer": ANALYZER_NAME,
            "schema_version": ANALYZER_SCHEMA_VERSION,
            "epoch_blocks": EPOCH_BLOCKS,
            "format_version": str(data.get("format_version") or ""),
            "ecdsa_backend": ECDSA_BACKEND,
            "signature_verification": (
                VERIFY_ENABLED if ECDSA_BACKEND == BACKEND_PYTHON_ECDSA
                else VERIFY_SKIPPED_NO_ECDSA
            ),
        },
        "source": {"path": source, "label": source_label},
        "chain": {
            "total_height": consensus["total_height"],
            "main_chain_blocks": consensus["main_chain_blocks"],
            "epoch_count": consensus["epoch_count"],
        },
        "language_evolution": language,
        "chain_consensus": consensus,
        "ledger": ledger,
        "poi": poi,
        "by_model": by_model,
        "field_provenance": {
            "derived_from": list(DERIVED_FROM),
            "avoided_fields": list(AVOIDED_FIELDS),
            "epoch_formula": f"epoch = height // {EPOCH_BLOCKS}",
        },
        "warnings": warnings,
    }

    return report, _render_text(report, include_by_model=include_by_model)


def build_metrics(data: dict, *, source: str, source_label: str) -> dict:
    """构造 metrics.json 的公开结构（顶层键名见 PUBLIC_METRICS_KEYS）。

    与 build_report 的关系：metrics.json = 分析器报告 + 少量发布信封字段
    （schema_version / generated_by / readonly / chain_height）。报告本身的键名
    与计算口径不变，因此 report["schema"]["schema_version"] 不因本函数递增——
    两条版本线各司其职。

    chain_height 是便捷冗余键（等价于 chain.total_height），用于让前端一次比对
    「metrics.json 与 chain_state.json 是否来自同一份链」。
    """
    report, _ = build_report(data, source=source, source_label=source_label)
    metrics = {
        "schema_version": METRICS_SCHEMA_VERSION,
        "generated_by": "export_public.py --metrics",
        "readonly": True,
        "chain_height": report["chain"]["total_height"],
    }
    metrics.update(report)
    return metrics


def _render_text(report: dict, *, include_by_model: bool = False) -> str:
    """渲染控制台报告（中文字段名，宽度 78）；--by-model 时追加跨模型小节。"""
    lines: list[str] = []
    bar = "=" * 78
    sub = "-" * 78

    lang = report["language_evolution"]
    cons = report["chain_consensus"]
    ledger = report["ledger"]
    poi = report["poi"]

    lines.append(bar)
    lines.append("StratumGenesis · 离线链分析 / 实验指标报告")
    lines.append(bar)
    lines.append(f"数据来源      : {report['source']['label']} ({report['source']['path']})")
    lines.append(f"格式版本      : {report['schema']['format_version'] or '未知'}"
                 f"  | 纪元粒度 = height // {report['schema']['epoch_blocks']}")
    lines.append(f"主链总高度    : {cons['total_height']}"
                 f"  | 主链区块数 = {cons['main_chain_blocks']}"
                 f"  | 覆盖纪元数 = {cons['epoch_count']}")
    lines.append(f"ECDSA 后端    : {report['schema']['ecdsa_backend']}"
                 f"{'（缺少 ecdsa 依赖，签名重验已跳过）' if report['schema']['ecdsa_backend'] == 'unavailable' else ''}")

    lines.append("")
    lines.append(sub)
    lines.append("① 语言演化指标")
    lines.append(sub)
    lines.append(f"历史层累计激活原语（provenance，只增不减）：{_fmt(lang['cumulative_ever_active'], 20)}")
    lines.append(f"首次激活原语数 = {lang['first_activation_count']}"
                 f"  | 总激活事件 = {lang['activation_events_total']}"
                 f"  | 引种事件 = {lang['total_inoculation_events']}"
                 f"  | 失忆原语数 = {lang['total_lost_memory_features']}")
    lines.append("")
    lines.append("  原语首次激活：")
    if lang["first_activation"]:
        for name, info in lang["first_activation"].items():
            lines.append(f"    {name:<8} height={info['height']:<5} epoch={info['epoch']}"
                         f"  proposer={info['proposer']}")
    else:
        lines.append("    —（无激活事件）")
    lines.append("")
    lines.append("  逐纪元演化（开篇可用 / 新激活 / 引种 / 失忆）：")
    for rec in lang["epochs"]:
        lines.append(f"    纪元 {rec['epoch']}  (height {rec['start_height']}~{rec['end_height']},"
                     f" 区块 {rec['blocks']} 块)")
        lines.append(f"      开篇可用原语 : {_fmt(rec['available_at_open'])}")
        lines.append(f"      新激活       : {_fmt(rec['newly_activated'])}"
                     f"   ({rec['newly_activated_count']} 个)")
        lines.append(f"      引种         : {_fmt(rec['inoculated'])}"
                     f"   ({rec['inoculated_count']} 个)")
        lines.append(f"      失忆集合     : {_fmt(rec['lost_memory'])}"
                     f"   ({rec['lost_memory_count']} 个)")

    lines.append("")
    lines.append(sub)
    lines.append("② 链与共识指标")
    lines.append(sub)
    lines.append("  每纪元区块数：")
    for rec in cons["epochs"]:
        flag = "满" if rec["is_full"] else "未满"
        lines.append(f"    纪元 {rec['epoch']:<4} {rec['blocks']:>4} / {rec['expected_blocks']}"
                     f"  [{flag}]  激活事件 {rec['activations']}")
    lines.append("")
    lines.append(f"  休眠分支数 = {cons['sleeping_branch_count']}"
                 f"  | 休眠分支区块总数 = {cons['sleeping_branch_block_total']}")
    for branch in cons["sleeping_branches"]:
        span = (f"height {branch['min_height']}~{branch['max_height']}"
                if branch["min_height"] is not None else "无区块")
        lines.append(f"    分支 {branch['branch_id'][:16]}…  {branch['blocks']} 块  {span}"
                     f"  激活={_fmt(branch['activations'], 4)}")
        if branch["rejection_reason"]:
            lines.append(f"      拒绝原因：{branch['rejection_reason']}")
    if not cons["sleeping_branches"]:
        lines.append("    —（无休眠分支）")
    lines.append("")
    rate = cons["proposal_success_rate"]
    lines.append(f"  提案成功率：主链 {rate['accepted_to_main']}/{rate['proposals_submitted']}"
                 f" = {_fmt_rate(rate['rate_main'])}"
                 f"  | 休眠分支 {_fmt_rate(rate['rate_sleeping_branch'])}")
    if rate["rejected_to_branch"]:
        lines.append(f"      落选入分支提案 = {rate['rejected_to_branch']} 个")
    lines.append("")
    lines.append(f"  矿工区块数与累计工作量（PoI），共 {cons['miners']['count']} 个矿工：")
    for row in cons["miners"]["by_miner"]:
        share = f"{row['share_of_total_tokens'] * 100:.1f}%" if row["share_of_total_tokens"] is not None else "—"
        tags = []
        if row.get("genesis_blocks"):
            tags.append(f"含创世块 {row['genesis_blocks']}")
        if not row.get("registered_in_archive", True):
            tags.append("不在 miners 注册表")
        tag_text = ("  [" + "、".join(tags) + "]") if tags else ""
        lines.append(f"    {row['miner']:<10} 区块 {row['blocks']:>4} 块"
                     f"  累计 token {row['standard_total_tokens']:>10,}  (占比 {share})"
                     f"  含激活 {row['blocks_with_activation']} 块{tag_text}")
    lines.append("")
    dist = cons["voting_weight_distribution"]
    lines.append(f"  投票权重分布（仅主链计入，总量 {dist['total_weight']:,} token，"
                 f"有产出矿工 {len([r for r in dist['rows'] if r['voting_weight'] > 0])} 个）：")
    lines.append(f"    头名占比 = {_fmt_rate(dist['top_miner_share'])}"
                 f"  | p50 = {dist['p50']:,.0f}"
                 f"  | p90 = {dist['p90']:,.0f}"
                 f"  | max = {dist['max']:,}"
                 f"  | min = {dist['min']:,}")
    if cons["rejection_reason_counts"]:
        lines.append("  拒绝原因分布：")
        for reason, count in cons["rejection_reason_counts"].items():
            lines.append(f"    {count:>4} x {reason}")

    lines.append("")
    lines.append(sub)
    lines.append("③ 账本指标")
    lines.append(sub)
    lines.append(f"  口径：{ledger['method']}")
    lines.append(f"  每块奖励 = {ledger['reward_amount']}"
                 f"  | 已发放奖励 = {ledger.get('rewards_issued', 0):,}"
                 f"  | 交易消费 = {ledger.get('consumed_by_transactions', 0):,}"
                 f"  | 总发行量 = {ledger['total_supply']:,}")
    lines.append(f"  未花费 UTXO 数 = {ledger['unspent_utxos']}"
                 f"  | 交易笔数 = {ledger['transaction_count']}")
    if ledger["balances"]:
        lines.append("  各矿工 UTXO 余额：")
        for row in ledger["balances"]:
            lines.append(f"    {row['miner']:<10} 余额 {row['balance']:>8,}"
                         f"  (未花费 {row['unspent_utxos']} 笔)"
                         f"  公钥 {row['public_key_hex'][:12]}…")
    else:
        lines.append("    —（账本重放失败，余额不可用）")

    lines.append("")
    lines.append(sub)
    lines.append("④ PoI 工作量指标")
    lines.append(sub)
    lines.append(f"  词元总量 = {poi['total_tokens']:,}"
                 f"  | 均值 = {poi['mean']:,.1f}"
                 f"  | 中位数 = {poi['median']:,.0f}"
                 f"  | 最大 = {poi['max']:,}"
                 f"  | 最小 = {poi['min']:,}")
    lines.append(f"  p25 = {poi['p25']:,.0f}  | p75 = {poi['p75']:,.0f}"
                 f"  | p90 = {poi['p90']:,.0f}"
                 f"  | 零词元区块 = {poi['zero_token_blocks']}")
    main_only = poi["main_chain_only"]
    lines.append(f"  仅主链（剔除创世块）：{main_only['blocks']} 块"
                 f"  总量 {main_only['total_tokens']:,}  均值 {main_only['mean']:,.1f}")
    lines.append(f"  输入词元合计 = {poi['input_tokens_total']:,}"
                 f"  | 输出词元合计 = {poi['output_tokens_total']:,}")
    lines.append("  分词器标识分布：")
    for name, info in poi["tokenizer_usage"].items():
        lines.append(f"    {name:<20} {info['blocks']:>4} 块（其中 {info['blocks_with_tokens']} 块含词元）")

    if include_by_model:
        lines.append("")
        lines.append(sub)
        lines.append("⑤ 跨 AI 创造力指标（来源 blocks[].poi.model_metadata；语言口径仅主链）")
        lines.append(sub)
        by_model = report["by_model"]
        if not by_model["models"]:
            lines.append("  模型列表为空（无任何非创世块的模型身份）")
        for model in by_model["models"]:
            accept = model["acceptance"]
            retain = model["retention"]
            pref = model["primitive_preference"]
            novel = model["combination_novelty"]
            miner_text = "、".join(item["label"] for item in model["miners"]) or "—"
            lines.append(f"  模型 {model['model_id']}（矿工 {model['miner_count']} 名：{miner_text}）")
            lines.append(f"    接受与产出 : 提案 {accept['proposals']} | 主链接受 {accept['accepted_to_main']} | "
                         f"落选 {accept['rejected_to_sleeping_branch']} | 接受率 {_fmt_rate(accept['acceptance_rate'])}")
            half_life = "—" if retain["half_life_epochs"] is None else f"{retain['half_life_epochs']:.1f}"
            lines.append(f"    引种留存率 : 首次激活特性 {retain['feature_count']} 个"
                         f"（{_fmt(retain['features_first_activated'], 6)}）"
                         f" | 引种事件 {retain['reintroduction_events']}"
                         f" | 半衰期估计 {half_life} 纪元")
            for feat in retain["features"]:
                last = feat["last_reintroduction_epoch"]
                last_text = "无" if last is None else f"纪元 {last}"
                lines.append(f"      {feat['primitive']:<6} 首激活 纪元{feat['first_epoch']}(H{feat['first_height']})"
                             f" → 最后引种 {last_text} | 跨度 {feat['span_epochs']} 纪元 | "
                             f"未引种纪元 {feat['silent_epochs_since_first']}")
            if retain["sample_size_warning"] and retain["feature_count"] > 0:
                lines.append(f"      [警示] 样本量 < {by_model['sample_size_warning_threshold']}，"
                             "留存率/半衰期仅为估计，需谨慎解读")
            pref_text = "、".join(f"{name}×{count}" for name, count in pref["top_primitives"][:6]) or "—"
            lines.append(f"    原语偏好   : 含激活主链块 {pref['activation_blocks']} 块 | {pref_text}")
            lines.append(f"    组合新颖度 : 首次激活组合 {len(novel['combinations_first_activated'])} 个，"
                         f"全局首次出现 {novel['novel_count']} / 非首次 {novel['non_novel_count']}")
        collab = by_model["collaboration"]
        lines.append("  分工与协作 :")
        if collab["miners_with_multiple_models"]:
            for item in collab["miners_with_multiple_models"]:
                lines.append(f"      {item['label']} 挂多模型：{'、'.join(item['models'])}")
        else:
            lines.append(f"      多模型矿工 = 0 名（无矿工同时挂 ≥2 个模型身份）")
        if collab["models_used_by_multiple_miners"]:
            for item in collab["models_used_by_multiple_miners"]:
                lines.append(f"      模型 {item['model_id']} 被 {item['miner_count']} 名矿工使用")
        else:
            lines.append(f"      多矿工模型 = 0 个（无模型被 ≥2 名矿工共用）")

    if report["warnings"]:
        lines.append("")
        lines.append(sub)
        lines.append("⑥ 注意事项")
        lines.append(sub)
        for warning in report["warnings"]:
            lines.append(f"  [警示] {warning}")
        lines.append("  注：「引种/失忆」为阶段 D 前的临时口径，"
                     "权威语义以纪元作用域 + 引种提案落地为准（见 EXPERIMENT_METRICS.md）。")

    lines.append("")
    lines.append(bar)
    return "\n".join(lines)


# ============================================================================
# 8) CLI 入口
# ============================================================================
def _write_json(report: dict, path: str) -> None:
    """写出机器可读 JSON；父目录不存在时创建，写入失败抛 AnalysisError。"""
    directory = os.path.dirname(os.path.abspath(path))
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as error:
        raise AnalysisError(f"无法创建 JSON 输出目录：{directory}（{error}）") from error
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
    except OSError as error:
        raise AnalysisError(f"无法写入 JSON 输出文件：{path}（{error}）") from error


def main(argv: list[str] | None = None) -> int:
    # 入口统一 stdout/stderr 编码：Windows 默认 GBK 代码页无法编码 U+26A0（⚠）等
    # 装饰字符，reconfigure 为 UTF-8 + errors="replace"，保证任何终端都不因编码崩溃。
    # --json 文件写入在 _write_json 用显式 encoding="utf-8"，不受 stdout 编码影响。
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # 测试注入的 StringIO 替换流或已关闭流没有 reconfigure，保持原状
            pass
    parser = argparse.ArgumentParser(
        description="StratumGenesis 离线链分析器：把链数据变成可复现、可发布的实验指标",
        epilog=(
            "无位置参数时：打印一行中文提示，改用内存合成链（跨 3 个纪元）跑完整指标，"
            "退出码仍为 0。这是已批准的行为，不是「参数被忽略」；"
            "自动化调用方请据 source.label / source.path 区分演示与真实存档。"
            "注意：无参回退与 --synthetic 需要本机 ecdsa 可用才能 exit 0；"
            "缺少 ecdsa 时打印中文提示并以非零码退出（python -m pip install ecdsa）。"
            "\n签名重验：--verify（--verify-hashes 为等价别名）走 "
            "crypto_key.verify_block_signature（与 persistence 同一来源）；"
            "本机缺少 ecdsa 依赖时明确打印跳过提示并在 --json 中标注，不验签、不用手写实现冒充。"
            "\n--by-model：跨 AI 创造力指标（接受与产出 / 引种留存率与半衰期 / 原语偏好 / "
            "组合新颖度 / 分工与协作），全部由 blocks[].poi.model_metadata + "
            "blocks[].activation + height // 100 推导，零后端改动。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("archive", nargs="?", default=None,
                        help="存档或导出 JSON 路径（chain-v2）；省略时打印提示并回退到内存合成链，退出码 0（需 ecdsa 可用）")
    parser.add_argument("--synthetic", action="store_true",
                        help="使用内存合成链（跨 3 个纪元，含 3 个模型身份），不读取任何存档文件；需要 ecdsa 可用")
    parser.add_argument("--json", dest="json_out", metavar="PATH", default=None,
                        help="同时输出机器可读 JSON 到指定路径")
    parser.add_argument("--verify", "--verify-hashes", dest="verify", action="store_true",
                        help="读取存档前先用 persistence.load_state 做逐块哈希 + 签名重验；"
                             "--verify 为正名，--verify-hashes 是等价别名")
    parser.add_argument("--by-model", action="store_true",
                        help="控制台追加输出跨 AI 创造力指标小节（机器可读 JSON 恒含 by_model 分区）")
    parser.add_argument("--compact", action="store_true",
                        help="控制台只输出摘要行（用于 CI/日志）")
    args = parser.parse_args(argv)

    source = "(内存合成链)"
    source_label = "合成链（无存档模式）"
    try:
        if args.synthetic:
            data = build_synthetic_chain()
        elif args.archive:
            if args.verify:
                if ECDSA_BACKEND == BACKEND_UNAVAILABLE:
                    # 缺依赖是「跳过」，不是失败：继续分析，跳过情况已由 schema 与 warnings 标注。
                    print("[跳过] 本机缺少 ecdsa 依赖，跳过签名重验")
                else:
                    passed, detail = verify_archive(args.archive)
                    if not passed:
                        print(f"[错误] {detail}")
                        return 1
                    print(f"[校验] {detail}")
            data = load_archive(args.archive)
            source = args.archive
            source_label = "存档/导出 JSON"
        else:
            print("[提示] 未指定存档路径，回退到内存合成链（不读取任何文件）")
            data = build_synthetic_chain()

        report, text = build_report(data, source=source, source_label=source_label,
                                    include_by_model=args.by_model)

        if args.json_out:
            _write_json(report, args.json_out)
        if not args.compact:
            print(text)
            if args.json_out:
                print(f"\n[已写出] 机器可读 JSON -> {args.json_out}")
        else:
            chain = report["chain"]
            lang = report["language_evolution"]
            line = (
                f"[摘要] 来源={source_label} 高度={chain['total_height']} "
                f"区块={chain['main_chain_blocks']} 纪元={chain['epoch_count']} "
                f"首次激活={lang['first_activation_count']} "
                f"引种={lang['total_inoculation_events']} "
                f"失忆={lang['total_lost_memory_features']} "
                f"分支={report['chain_consensus']['sleeping_branch_count']}"
            )
            if report.get("by_model", {}).get("models"):
                models = report["by_model"]["models"]
                line += (f" 模型={len(models)}("
                         + ",".join(f"{m['model_id']}={m['retention']['reintroduction_events']}"
                                    for m in models) + ")")
            print(line)
            if args.json_out:
                print(f"[已写出] 机器可读 JSON -> {args.json_out}")
    except AnalysisError as error:
        print(f"[错误] {error}")
        return 1
    except Exception as error:  # noqa: BLE001 - CLI 兜底，避免裸堆栈
        print(f"[错误] 分析过程出现未预期异常：{error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
