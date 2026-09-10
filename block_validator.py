"""区块完整合法性校验器，签名校验为第 0 步前置检查。

校验流水线（8 步）：
0. ECDSA 签名校验
1. 结构与父区块/高度检查
2. 创世内核兼容性检查
3. PoI mock token 校验
4. demo/test_cases 解析校验
5. 特性激活校验（activation 必须来自预置池、不得与已激活特性重复）
6. 语言扩展正负测试（证明提案真的改变了语言能力）
7. UTXO 交易校验
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from block_model import Block, calculate_block_hash
from chain_store import ChainStore
from crypto_key import verify_block_signature
from mock_tokenizer import MOCK_TOKENIZER_ID, count_poi_tokens
from novscript import SandboxLimits, parse, run_sandbox
from novscript.lexer import tokenize
from novscript.registry import FeatureRegistry, KERNEL_PRIMITIVES, spec_of
from utxo_ledger import UTXOValidationError

MIN_POI_TOKENS = 10
_FORBIDDEN_KERNEL_MARKERS = (
    "修改创世内核", "修改内核", "strict evaluation", "严格求值", "可变绑定",
    "mutable binding", "修改bind", "修改 bind", "外部io", "外部 io", "文件读写",
    "网络访问", "系统调用",
)

# 提案文本 -> 语言特性关键词（server.py 用于从提案文本映射 activation 原语名）。
PROPOSAL_FEATURE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("减法", "-"),
    ("减去", "-"),
    ("列表", "list"),
    ("加法扩展", "+"),  # 保留：+ 是内核原语，不允许作为激活特性（校验会拒绝）
)


@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    stage: str
    error_code: str | None = None
    message: str = ""
    checked_stages: tuple[str, ...] = ()


def _fail(stage: str, code: str, message: str, checked: list[str]) -> ValidationResult:
    return ValidationResult(False, stage, code, message, tuple(checked))


def _check_signature(block: Block, checked: list[str]) -> ValidationResult | None:
    checked.append("signature")
    if not block.miner_pubkey or not block.signature_bytes:
        return _fail("signature", "SIGNATURE_INVALID", "missing public key or signature bytes", checked)
    if not verify_block_signature(block.miner_pubkey, block.canonical_bytes(), block.signature_bytes):
        return _fail("signature", "SIGNATURE_INVALID", "ECDSA signature verification failed", checked)
    return None


def _check_structure(block: Block, store: ChainStore, checked: list[str]) -> ValidationResult | None:
    checked.append("structure")
    if not isinstance(block.height, int) or block.height < 1:
        return _fail("structure", "INVALID_HEIGHT", "non-genesis candidate height must be positive", checked)
    if block.parent_hash is None:
        return _fail("structure", "MISSING_PARENT", "candidate block must have a parent", checked)
    parent = store.get_block(block.parent_hash)
    if parent is None:
        return _fail("structure", "PARENT_NOT_FOUND", "parent block is not present in memory store", checked)
    if block.height != parent.height + 1:
        return _fail("structure", "HEIGHT_MISMATCH", "block height must equal parent height + 1", checked)
    if block.epoch != block.height // 100:
        return _fail("structure", "EPOCH_MISMATCH", "block epoch must equal height // 100", checked)
    if block.block_hash != calculate_block_hash(block):
        return _fail("structure", "HASH_MISMATCH", "block hash does not match canonical payload", checked)
    if store.contains(block.block_hash):
        return _fail("structure", "DUPLICATE_BLOCK", "block already exists", checked)
    return None


def _check_kernel_compatibility(block: Block, checked: list[str]) -> ValidationResult | None:
    checked.append("kernel_compatibility")
    text = " ".join((block.proposal.specification, block.proposal.demo_code)).lower()
    if any(marker.lower() in text for marker in _FORBIDDEN_KERNEL_MARKERS):
        return _fail("kernel_compatibility", "GENESIS_KERNEL_CONFLICT", "proposal conflicts with immutable NovScript kernel constraints", checked)
    if block.proposal.kind not in {"extension"}:
        return _fail("kernel_compatibility", "UNSUPPORTED_PROPOSAL_KIND", "only extension proposals are supported", checked)
    return None


def _check_poi(block: Block, checked: list[str]) -> ValidationResult | None:
    checked.append("poi")
    counts = count_poi_tokens(block.poi.prompt, block.poi.output)
    if block.poi.standard_tokenizer != MOCK_TOKENIZER_ID:
        return _fail("poi", "TOKENIZER_MISMATCH", "prototype requires mock-tokenizer-v1", checked)
    if (block.poi.standard_input_tokens, block.poi.standard_output_tokens, block.poi.standard_total_tokens) != (counts.standard_input_tokens, counts.standard_output_tokens, counts.standard_total_tokens):
        return _fail("poi", "TOKEN_COUNT_MISMATCH", "declared PoI counts differ from mock recount", checked)
    if counts.standard_total_tokens < MIN_POI_TOKENS:
        return _fail("poi", "POI_BELOW_THRESHOLD", f"mock total tokens below threshold {MIN_POI_TOKENS}", checked)
    return None


def _check_parse(block: Block, checked: list[str]) -> ValidationResult | None:
    checked.append("parse")
    try:
        parse(block.proposal.demo_code)
    except Exception as error:
        return _fail("parse", "DEMO_PARSE_FAILED", str(error), checked)
    for index, case in enumerate(block.proposal.test_cases):
        try:
            parse(case.program)
        except Exception as error:
            return _fail("parse", "TEST_PARSE_FAILED", f"test case {index}: {error}", checked)
    return None


def _check_sandbox(block: Block, store: ChainStore, checked: list[str], limits: SandboxLimits) -> ValidationResult | None:
    """沙箱运行校验（普通区块基础检查）。

    带 activation 的扩展区块跳过本步：其 demo/test_cases 的沙箱运行由
    第 7 步「语言扩展正负测试」用升级后的语言快照承担（负测试还证明
    旧语言下必然失败），这里若再用旧语言运行会误拒。
    """
    checked.append("sandbox")
    if block.activation:
        return None
    registry = store.language_registry
    demo = run_sandbox(block.proposal.demo_code, limits=limits, registry=registry)
    if not demo.ok:
        return _fail("sandbox", "DEMO_RUNTIME_FAILED", demo.error_message or "demo runtime failed", checked)
    for index, case in enumerate(block.proposal.test_cases):
        result = run_sandbox(case.program, limits=limits, registry=registry)
        if not result.ok:
            return _fail("sandbox", "TEST_RUNTIME_FAILED", f"test case {index} runtime failed", checked)
        if result.value != case.expected:
            return _fail("sandbox", "TEST_EXPECTATION_MISMATCH", f"test case {index} expected {case.expected!r}, got {result.value!r}", checked)
    return None


def _check_utxo(block: Block, store: ChainStore, checked: list[str]) -> ValidationResult | None:
    """第 7 步：只验证交易，不在候选校验阶段修改账本。"""
    checked.append("utxo")
    try:
        store.utxo_ledger.validate_transactions(block.transactions)
    except UTXOValidationError as error:
        return _fail("utxo", "UTXO_INVALID", str(error), checked)
    return None


# ---------------------------------------------------------------------------
# 第 5 步：特性激活校验
# ---------------------------------------------------------------------------
def _check_activation(block: Block, store: ChainStore, checked: list[str]) -> ValidationResult | None:
    """activation 中的每个原语名必须来自预置池，且不得与当前链已激活特性重复。"""
    checked.append("activation")
    if not block.activation:
        return None  # 普通区块：不改变语言能力，跳过后续特性校验
    active = store.language_registry.snapshot()
    for name in block.activation:
        if name in KERNEL_PRIMITIVES:
            return _fail(
                "activation", "KERNEL_FEATURE_CONFLICT",
                f"feature {name!r} conflicts with NovScript kernel primitive", checked,
            )
        if spec_of(name) is None:
            return _fail(
                "activation", "UNKNOWN_FEATURE",
                f"feature {name!r} not in BUILTIN_POOL", checked,
            )
        if name in active:
            return _fail(
                "activation", "DUPLICATE_FEATURE",
                f"feature {name!r} is already active on the main chain", checked,
            )
    return None


# ---------------------------------------------------------------------------
# 第 6 步：语言扩展正负测试（核心：证明提案真的改变了语言能力）
# ---------------------------------------------------------------------------
def _code_tokens(source: str) -> set[str]:
    """提取源码中的标识符 token（与词法器一致），用于“demo 确实引用新特性”检查。

    第 4 步已保证 demo_code 可解析，因此这里 tokenize 不会失败；防御性兜底。
    """
    try:
        return {token.lexeme for token in tokenize(source) if token.kind == "IDENTIFIER"}
    except Exception:
        return set()


def _registry_with(store: ChainStore, block: Block) -> FeatureRegistry | None:
    """构造「链级已激活 + 本块 activation」的临时注册表；异常返回 None。"""
    specs = list(store.language_registry.all_specs())
    for name in block.activation:
        spec = spec_of(name)
        if spec is None:
            return None
        specs.append(spec)
    return FeatureRegistry.from_specs(specs)


def _check_language_evolution(
    block: Block, store: ChainStore, checked: list[str], limits: SandboxLimits
) -> ValidationResult | None:
    """正负双重测试：证明激活这些原语后 demo/test_cases 才可能通过。

    正测试：用（链级已激活 + 本块 activation）的快照运行 demo 与全部 test_cases，
            必须全部通过；
    负测试：用（链级已激活、不含本块 activation）的快照运行同一 demo，必须失败；
    附加检查：demo 词法必须包含本块 activation 中的至少一个原语名，
            防止用与提案无关的代码糊弄负测试。
    """
    checked.append("language_evolution")
    if not block.activation:
        return None
    demo = block.proposal.demo_code

    used = _code_tokens(demo) & set(block.activation)
    if not used:
        return _fail(
            "language_evolution", "FEATURE_NOT_USED",
            "demo_code must reference at least one activated primitive name", checked,
        )

    # 正测试：含本块 activation 的语言快照。
    positive = _registry_with(store, block)
    if positive is None:
        return _fail("language_evolution", "UNKNOWN_FEATURE", "cannot build positive registry", checked)
    demo_result = run_sandbox(demo, limits=limits, registry=positive)
    if not demo_result.ok:
        return _fail(
            "language_evolution", "POSITIVE_DEMO_FAILED",
            f"demo fails under upgraded language: {demo_result.error_message}", checked,
        )
    for index, case in enumerate(block.proposal.test_cases):
        result = run_sandbox(case.program, limits=limits, registry=positive)
        if not result.ok:
            return _fail(
                "language_evolution", "POSITIVE_TEST_FAILED",
                f"test case {index} runtime failed: {result.error_message}", checked,
            )
        if result.value != case.expected:
            return _fail(
                "language_evolution", "POSITIVE_TEST_MISMATCH",
                f"test case {index} expected {case.expected!r}, got {result.value!r}", checked,
            )

    # 负测试：不含本块 activation 的语言快照，同一 demo 必须失败。
    negative = run_sandbox(demo, limits=limits, registry=store.language_registry)
    if negative.ok:
        return _fail(
            "language_evolution", "NEGATIVE_TEST_PASSED",
            "demo runs even without the proposed feature; this proposal does not change the language", checked,
        )
    return None


def validate_block(block: Block, store: ChainStore, *, limits: SandboxLimits | None = None) -> ValidationResult:
    """按第 0 步签名、再 1~7 步完整校验区块。

    流水线（9 个检查，文档按 8 步分组）：
    0. ECDSA 签名 -> 1. 结构 -> 2. 内核兼容 -> 3. PoI -> 4. 解析
    -> 5. 特性激活（新） -> 6. 沙箱运行（普通区块） -> 7. 语言扩展正负测试（新） -> 8. UTXO
    """
    checked: list[str] = []
    effective_limits = limits or SandboxLimits()
    checks = (
        lambda: _check_signature(block, checked),
        lambda: _check_structure(block, store, checked),
        lambda: _check_kernel_compatibility(block, checked),
        lambda: _check_poi(block, checked),
        lambda: _check_parse(block, checked),
        lambda: _check_activation(block, store, checked),
        lambda: _check_sandbox(block, store, checked, effective_limits),
        lambda: _check_language_evolution(block, store, checked, effective_limits),
        lambda: _check_utxo(block, store, checked),
    )
    for check in checks:
        failure = check()
        if failure is not None:
            return failure
    return ValidationResult(True, "accepted", checked_stages=tuple(checked), message="block is a valid candidate")
