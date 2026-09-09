"""区块完整合法性校验器，签名校验为第 0 步前置检查。"""

from __future__ import annotations

from dataclasses import dataclass

from block_model import Block, calculate_block_hash
from chain_store import ChainStore
from crypto_key import verify_block_signature
from mock_tokenizer import MOCK_TOKENIZER_ID, count_poi_tokens
from novscript import SandboxLimits, parse, run_sandbox
from utxo_ledger import UTXOValidationError

MIN_POI_TOKENS = 10
_FORBIDDEN_KERNEL_MARKERS = (
    "修改创世内核", "修改内核", "strict evaluation", "严格求值", "可变绑定",
    "mutable binding", "修改bind", "修改 bind", "外部io", "外部 io", "文件读写",
    "网络访问", "系统调用",
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


def _check_sandbox(block: Block, checked: list[str], limits: SandboxLimits) -> ValidationResult | None:
    checked.append("sandbox")
    demo = run_sandbox(block.proposal.demo_code, limits=limits)
    if not demo.ok:
        return _fail("sandbox", "DEMO_RUNTIME_FAILED", demo.error_message or "demo runtime failed", checked)
    for index, case in enumerate(block.proposal.test_cases):
        result = run_sandbox(case.program, limits=limits)
        if not result.ok:
            return _fail("sandbox", "TEST_RUNTIME_FAILED", f"test case {index} runtime failed", checked)
        if result.value != case.expected:
            return _fail("sandbox", "TEST_EXPECTATION_MISMATCH", f"test case {index} expected {case.expected!r}, got {result.value!r}", checked)
    return None


def _check_utxo(block: Block, store: ChainStore, checked: list[str]) -> ValidationResult | None:
    """第 6 步：只验证交易，不在候选校验阶段修改账本。"""
    checked.append("utxo")
    try:
        store.utxo_ledger.validate_transactions(block.transactions)
    except UTXOValidationError as error:
        return _fail("utxo", "UTXO_INVALID", str(error), checked)
    return None


def validate_block(block: Block, store: ChainStore, *, limits: SandboxLimits | None = None) -> ValidationResult:
    """按第 0 步签名、再 1~5 步完整校验区块。"""
    checked: list[str] = []
    effective_limits = limits or SandboxLimits()
    checks = (
        lambda: _check_signature(block, checked),
        lambda: _check_structure(block, store, checked),
        lambda: _check_kernel_compatibility(block, checked),
        lambda: _check_poi(block, checked),
        lambda: _check_parse(block, checked),
        lambda: _check_sandbox(block, checked, effective_limits),
        lambda: _check_utxo(block, store, checked),
    )
    for check in checks:
        failure = check()
        if failure is not None:
            return failure
    return ValidationResult(True, "accepted", checked_stages=tuple(checked), message="block is a valid candidate")
