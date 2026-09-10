"""区块完整合法性校验器，签名校验为第 0 步前置检查。

校验流水线（8 步，9 个检查）：
0. ECDSA 签名校验
1. 结构与父区块/高度检查
2. 创世内核兼容性检查
3. PoI mock token 校验
4. demo/test_cases 解析校验
5. 特性激活校验（纪元作用域：activation 须来自预置池、不得与本纪元已激活
   特性重复；引用更早纪元已激活但本纪元未引种的原语 -> UNIMPORTED_FEATURE）
6. 语言扩展正负测试（证明提案真的改变了语言能力）
7. UTXO 交易校验
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from block_model import Block, calculate_block_hash
from chain_store import ChainStore
from crypto_key import verify_block_signature
from epoch_manager import EPOCH_BLOCKS
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
    普通区块用「候选所在纪元的生效注册表」（纪元作用域）运行。
    """
    checked.append("sandbox")
    if block.activation:
        return None
    registry = _epoch_registry_for(store, block.height)
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
# 第 5 步：特性激活校验（纪元作用域）
# ---------------------------------------------------------------------------
def _epoch_registry_for(store: ChainStore, height: int) -> FeatureRegistry:
    """候选块所在纪元的「已生效注册表」。

    - 候选与当前主链同纪元 -> 直接取纪元层（未到边界，未重置）；
    - 候选为纪元首块（跨纪元边界）-> 空注册表（新纪元从内核起步，失忆）。
    """
    if store.epoch_of_height(height) == store.epoch_of_height(store.height):
        return store.epoch_registry
    return FeatureRegistry()


def _unimported_name(block: Block, store: ChainStore) -> str | None:
    """检测「失忆」违规：demo/test_cases 引用了更早纪元激活过、本纪元尚未
    引种、且不在本块 activation 中的原语名；返回第一个违规名，无则 None。

    判定顺序：内核原语永远可用；非预置池标识符（如绑定名）不构成违规；
    本块 activation 中的名字是正在引种；本纪元已激活的名字可用；
    其余历史曾激活过的名字 -> 未引种（UNIMPORTED_FEATURE）。
    """
    current_epoch = store.epoch_of_height(block.height)
    epoch_active = _epoch_registry_for(store, block.height).snapshot()
    ever_active = store.ever_active_features()
    if not ever_active:
        return None
    sources = [block.proposal.demo_code] + [case.program for case in block.proposal.test_cases]
    for source in sources:
        for name in _code_tokens(source):
            if name in KERNEL_PRIMITIVES:
                continue
            if spec_of(name) is None:
                continue  # 非预置池标识符：可能是绑定名，交由沙箱阶段处理
            if name in block.activation:
                continue  # 本块正在激活/引种
            if name in epoch_active:
                continue  # 本纪元已可用
            if name in ever_active:
                return name  # 曾激活过但本纪元未引种 -> 失忆
    return None


def _check_activation(block: Block, store: ChainStore, checked: list[str]) -> ValidationResult | None:
    """activation 校验（纪元作用域）。

    - 名字须来自预置池、不得与创世内核冲突（不变）；
    - 同纪元重复激活 -> DUPLICATE_FEATURE（跨纪元重新激活为合法引种，不再拒绝）；
    - demo/test_cases 引用了「更早纪元激活过、本纪元未引种、且不在本块
      activation」的原语 -> UNIMPORTED_FEATURE（失忆语义，语义化报错）；
    - 普通区块（无 activation）同样执行上述未引种检查。
    """
    checked.append("activation")
    unimported = _unimported_name(block, store)
    if unimported is not None:
        first_epoch = store.first_activation_epoch(unimported)
        current_epoch = store.epoch_of_height(block.height)
        origin = f"epoch {first_epoch}" if first_epoch is not None else "an earlier epoch"
        return _fail(
            "activation", "UNIMPORTED_FEATURE",
            f"feature {unimported!r} belongs to {origin} and has not been inoculated "
            f"in the current epoch (epoch {current_epoch}); add it to activation to inoculate",
            checked,
        )
    if not block.activation:
        return None  # 普通区块：不改变语言能力，跳过后续特性校验
    active = _epoch_registry_for(store, block.height).snapshot()
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
                f"feature {name!r} is already active in the current epoch", checked,
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
    """构造「候选纪元已生效 + 本块 activation」的临时注册表；异常返回 None。

    基准 = 纪元作用域（同纪元取纪元层；跨纪元首块为空），
    叠加本块 activation 后用于正测试。
    """
    specs = list(_epoch_registry_for(store, block.height).all_specs())
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

    正测试：用（候选纪元已生效 + 本块 activation）的快照运行 demo 与全部 test_cases，
            必须全部通过；
    负测试：用（候选纪元已生效、不含本块 activation）的快照运行同一 demo，必须失败；
    附加检查：demo 词法必须包含本块 activation 中的至少一个原语名，
            防止用与提案无关的代码糊弄负测试。
    作用域为纪元内：跨纪元默认失忆，引种提案的负测试基准 = 新纪元基线（空）。
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

    # 负测试：不含本块 activation 的【候选纪元生效】注册表，同一 demo 必须失败。
    negative = run_sandbox(demo, limits=limits, registry=_epoch_registry_for(store, block.height))
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


# ---------------------------------------------------------------------------
# 阶段 E：promote 结构资格判定（E1–E6；stage="promotion"，不进常规流水线）
# ---------------------------------------------------------------------------
def check_promotion_eligibility(
    chain: list[Block] | tuple[Block, ...],
    fork_height: int,
    store: ChainStore,
) -> ValidationResult:
    """休眠分支升级的结构资格判定（设计文档 §2.2，E1–E6）。

    chain 为 walk 产出的休眠链 (b_1 … b_k)，fork_height = 分叉父在主链的高度。
    E7（重放语义有效性）不在此函数执行——由 chain_store.promote_branch 在
    scratch 重放时逐块完整校验（纯函数：不修改 store，仅返回判定结果）。
    """
    checked = ["promotion"]
    e_star = store.epoch_of_height(store.height)
    epoch_start = e_star * EPOCH_BLOCKS
    if not chain:
        return _fail("promotion", "PROMOTION_NOT_FOUND", "empty branch chain", checked)
    # E2 链线性完整：父链接 + 高度连续 + 首块高度 == f + 1。
    for index in range(1, len(chain)):
        if chain[index].parent_hash != chain[index - 1].block_hash:
            return _fail(
                "promotion", "PROMOTION_CHAIN_BROKEN",
                f"branch chain link broken at index {index}", checked,
            )
        if chain[index].height != chain[index - 1].height + 1:
            return _fail(
                "promotion", "PROMOTION_CHAIN_BROKEN",
                f"branch height non-linear at index {index}", checked,
            )
    if chain[0].height != fork_height + 1:
        return _fail(
            "promotion", "PROMOTION_CHAIN_BROKEN",
            "branch head does not connect to fork parent", checked,
        )
    # E3 分叉父锚定主链（walk 已保证，此处防御复查）。
    main = store.main_chain()
    if fork_height > len(main) - 1 or main[fork_height].block_hash != chain[0].parent_hash:
        return _fail(
            "promotion", "PROMOTION_PARENT_MISSING",
            "branch does not anchor to current main chain", checked,
        )
    # E4 旧后缀纪元局部：被替换后缀整体位于当前纪元（f + 1 >= s）。
    if fork_height + 1 < epoch_start:
        return _fail(
            "promotion", "PROMOTION_ARCHIVED_EPOCH",
            f"reorg would touch archived epoch blocks (fork height {fork_height} < epoch start {epoch_start})",
            checked,
        )
    # E5 分支纪元局部（v1 从严版）：分支整链位于当前纪元（含未来纪元块即拒）。
    for block in chain:
        if block.epoch != e_star:
            return _fail(
                "promotion", "PROMOTION_EPOCH_SPAN",
                f"branch block height={block.height} epoch={block.epoch} escapes current epoch {e_star}",
                checked,
            )
    # E6 唯一性（防御复查）：C 内互异、C ∩ M = ∅。
    hashes = [block.block_hash for block in chain]
    if len(set(hashes)) != len(hashes):
        return _fail("promotion", "PROMOTION_NOT_ELIGIBLE", "branch contains duplicate block hashes", checked)
    main_hashes = {block.block_hash for block in main}
    if any(block.block_hash in main_hashes for block in chain):
        return _fail("promotion", "PROMOTION_NOT_ELIGIBLE", "branch intersects main chain", checked)
    return ValidationResult(
        True, "promotion", checked_stages=tuple(checked), message="branch is structurally eligible"
    )
