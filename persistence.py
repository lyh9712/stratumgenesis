"""StratumGenesis v0.3 · 磁盘持久化与链数据导出模块。

设计目标（见 ARCHIVE_v0_2_README.md §6「磁盘持久化」与白皮书 §14.5「定期导出完整链数据」）：

1. 落盘的最小权威状态：
   - 主链全部区块（含创世块）；
   - 休眠分支（分支标识 + 区块序列），拒绝原因单独保存；
   - 矿工注册表（公钥 + 标签 + 私钥，私钥用于重启后继续为 /propose 签名）。

2. UTXO 账本与纪元快照【不直接序列化内部缓存】：
   加载时从主链按既有规则确定性重建（重放挖矿奖励与交易得到账本、按纪元规则重扫得到快照），
   可防状态漂移并天然校验一致性。

3. 保存格式为 JSON，含 format_version 字段预留演进；默认路径 data/chain_v1.json；
   写入采用「临时文件 + 原子替换」（写 .tmp 再 os.replace），避免中断损坏。

4. 矿工私钥为原型本地演示密钥，仅本机实验用：无生产安全承诺，不用于任何真实资产。

⚠️ 已知局限（与全局项目一致）：本模块是实验级 JSON 存档，不是生产级存储；
服务仍为单机仿真，无 P2P、无公网、无鉴权、无加密，私钥明文保存在本机存档中。
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Iterable

from block_model import Block, PoiRecord, Proposal, TestCase
from chain_store import ChainStore
from crypto_key import verify_block_signature
from utxo_model import Transaction, UTXO

# 存档格式版本：后续演进时递增，旧版本存档将被拒绝加载（需 --fresh 重建）。
FORMAT_VERSION = "chain-v1"

# 存档文件默认名（相对项目根目录）。
DEFAULT_ARCHIVE_NAME = "chain_v1.json"

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ARCHIVE_PATH = os.path.join(_BASE_DIR, "data", DEFAULT_ARCHIVE_NAME)


class PersistenceError(Exception):
    """存档读写/校验失败；错误信息为中文，供启动时直接展示。"""


# ---------------------------------------------------------------------------
# 序列化辅助（bytes -> b64；确定性 JSON）
# ---------------------------------------------------------------------------
def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text)


def _atomic_write(path: str, obj: Any) -> None:
    """临时文件 + 原子替换写入，避免进程中断产生半截存档。"""
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(obj, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    os.replace(tmp_path, path)


# ---------------------------------------------------------------------------
# Block / Proposal / Poi / Transaction / UTXO 双向转换
# ---------------------------------------------------------------------------
def _utxo_to_dict(utxo: UTXO) -> dict:
    return {
        "tx_hash_b64": _b64e(utxo.tx_hash),
        "output_index": utxo.output_index,
        "pubkey_b64": _b64e(utxo.pubkey),
        "amount": utxo.amount,
    }


def _utxo_from_dict(data: dict) -> UTXO:
    return UTXO(
        tx_hash=_b64d(data["tx_hash_b64"]),
        output_index=int(data["output_index"]),
        pubkey=_b64d(data["pubkey_b64"]),
        amount=int(data["amount"]),
    )


def _transaction_to_dict(tx: Transaction) -> dict:
    return {
        "inputs": [_utxo_to_dict(item) for item in tx.inputs],
        "outputs": [_utxo_to_dict(item) for item in tx.outputs],
        "tx_signature_b64": _b64e(tx.tx_signature),
    }


def _transaction_from_dict(data: dict) -> Transaction:
    return Transaction(
        inputs=[_utxo_from_dict(item) for item in data["inputs"]],
        outputs=[_utxo_from_dict(item) for item in data["outputs"]],
        tx_signature=_b64d(data["tx_signature_b64"]),
    )


def _block_to_dict(block: Block) -> dict:
    return {
        "height": block.height,
        "parent_hash": block.parent_hash,
        "proposer": block.proposer,
        "prototype_version": block.prototype_version,
        "miner_pubkey_b64": _b64e(block.miner_pubkey),
        "signature_bytes_b64": _b64e(block.signature_bytes),
        "epoch": block.epoch,
        "block_hash": block.block_hash,
        "proposal": {
            "kind": block.proposal.kind,
            "feature_id": block.proposal.feature_id,
            "specification": block.proposal.specification,
            "demo_code": block.proposal.demo_code,
            "test_cases": [
                {"program": case.program, "expected": case.expected}
                for case in block.proposal.test_cases
            ],
        },
        "poi": {
            "model_metadata": block.poi.model_metadata,
            "prompt": block.poi.prompt,
            "output": block.poi.output,
            "standard_tokenizer": block.poi.standard_tokenizer,
            "standard_input_tokens": block.poi.standard_input_tokens,
            "standard_output_tokens": block.poi.standard_output_tokens,
            "standard_total_tokens": block.poi.standard_total_tokens,
        },
        "transactions": [_transaction_to_dict(tx) for tx in block.transactions],
    }


def _verify_block_signature(block: Block) -> None:
    """验签存档区块（创世块无签名，跳过）。

    block_hash 按设计排除 signature_bytes，因此仅篡改签名的存档能通过哈希校验；
    这里用既有 crypto_key.verify_block_signature 对每块补验 ECDSA 签名，
    签名不符即判定存档损坏并拒绝加载（阶段 A 遗留小修）。
    """
    if block.height == 0 or not block.miner_pubkey or not block.signature_bytes:
        return
    if not verify_block_signature(block.miner_pubkey, block.canonical_bytes(), block.signature_bytes):
        raise PersistenceError(
            f"存档区块签名校验失败（height={block.height}）：ECDSA 签名与区块内容不符，存档已损坏或被篡改"
        )


def _block_from_dict(data: dict) -> Block:
    """从 JSON 重建 Block 并校验区块哈希；失败抛 PersistenceError。"""
    try:
        proposal = Proposal(
            kind=str(data["proposal"]["kind"]),
            feature_id=str(data["proposal"]["feature_id"]),
            specification=str(data["proposal"]["specification"]),
            demo_code=str(data["proposal"]["demo_code"]),
            test_cases=tuple(
                TestCase(str(case["program"]), case["expected"])
                for case in data["proposal"]["test_cases"]
            ),
        )
        poi = PoiRecord(
            model_metadata=str(data["poi"]["model_metadata"]),
            prompt=str(data["poi"]["prompt"]),
            output=str(data["poi"]["output"]),
            standard_tokenizer=str(data["poi"]["standard_tokenizer"]),
            standard_input_tokens=int(data["poi"]["standard_input_tokens"]),
            standard_output_tokens=int(data["poi"]["standard_output_tokens"]),
            standard_total_tokens=int(data["poi"]["standard_total_tokens"]),
        )
        transactions = tuple(
            _transaction_from_dict(item) for item in data["transactions"]
        )
        block = Block(
            height=int(data["height"]),
            parent_hash=data["parent_hash"],
            proposer=str(data["proposer"]),
            proposal=proposal,
            poi=poi,
            prototype_version=str(data["prototype_version"]),
            miner_pubkey=_b64d(data["miner_pubkey_b64"]),
            signature_bytes=_b64d(data["signature_bytes_b64"]),
            transactions=transactions,
            epoch=int(data["epoch"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PersistenceError(f"存档区块数据无法解析（height={data.get('height')}）：{error}") from error
    if block.block_hash != data.get("block_hash"):
        raise PersistenceError(
            f"存档区块哈希校验失败（height={block.height}）：存储哈希与重算不一致，存档已损坏"
        )
    return block


# ---------------------------------------------------------------------------
# 矿工注册表序列化（公钥/私钥均为 bytes -> b64）
# ---------------------------------------------------------------------------
def miners_to_list(miners: dict[bytes, tuple[str, bytes]]) -> list[dict]:
    """miners: {public_key: (label, private_key)} -> 确定性排序列表。"""
    items = []
    for public_key, (label, private_key) in miners.items():
        items.append({
            "label": label,
            "public_key_b64": _b64e(public_key),
            "private_key_b64": _b64e(private_key),
        })
    items.sort(key=lambda item: item["public_key_b64"])
    return items


def miners_from_list(items: Iterable[dict]) -> dict[bytes, tuple[str, bytes]]:
    restored: dict[bytes, tuple[str, bytes]] = {}
    for item in items:
        public_key = _b64d(item["public_key_b64"])
        restored[public_key] = (str(item["label"]), _b64d(item["private_key_b64"]))
    return restored


# ---------------------------------------------------------------------------
# 主状态序列化 / 保存 / 加载 / 重建
# ---------------------------------------------------------------------------
def serialize_state(
    store: ChainStore,
    miners: dict[bytes, tuple[str, bytes]],
    rejection_reasons: dict[str, str],
) -> dict:
    """把内存权威状态序列化为确定性 JSON 字典（账本与纪元快照不在此序列化）。"""
    branches = []
    for branch_id, blocks in store.sleeping_branches().items():
        branches.append({
            "branch_id": branch_id,
            "blocks": [_block_to_dict(block) for block in blocks],
        })
    return {
        "format_version": FORMAT_VERSION,
        "blocks": [_block_to_dict(block) for block in store.main_chain()],
        "sleeping_branches": branches,
        "miners": miners_to_list(miners),
        "rejection_reasons": dict(sorted(rejection_reasons.items())),
    }


def save_state(
    path: str,
    store: ChainStore,
    miners: dict[bytes, tuple[str, bytes]],
    rejection_reasons: dict[str, str],
) -> None:
    """原子写入完整存档（临时文件 + os.replace）。"""
    _atomic_write(path, serialize_state(store, miners, rejection_reasons))


def export_chain(
    path: str,
    store: ChainStore,
    miners: dict[bytes, tuple[str, bytes]],
    rejection_reasons: dict[str, str],
) -> None:
    """导出与存档完全相同的完整链数据到指定路径（供存档/研究使用）。

    与 save_state 使用同一确定性格式；区别仅在语义上标注为「导出」。
    """
    save_state(path, store, miners, rejection_reasons)


def write_export(path: str, data: dict) -> None:
    """把已校验的存档数据原样写入导出文件（供 persistence CLI 使用）。"""
    if data.get("format_version") != FORMAT_VERSION:
        raise PersistenceError(f"导出数据格式版本不匹配：{data.get('format_version')}")
    _atomic_write(path, data)


def load_state(path: str) -> dict:
    """读取并校验存档；损坏/版本不匹配/哈希不一致一律抛 PersistenceError。"""
    if not os.path.exists(path):
        raise PersistenceError(f"存档文件不存在：{path}")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise PersistenceError(f"存档文件无法读取或 JSON 已损坏：{path}（{error}）") from error
    if not isinstance(data, dict) or data.get("format_version") != FORMAT_VERSION:
        actual = data.get("format_version") if isinstance(data, dict) else "未知"
        raise PersistenceError(
            f"存档格式版本不匹配：期望 {FORMAT_VERSION}，实际 {actual}。"
            f"如需忽略存档重建演示链，请使用 python server.py --fresh"
        )
    required = ("blocks", "sleeping_branches", "miners", "rejection_reasons")
    if any(key not in data for key in required):
        raise PersistenceError(f"存档缺少必要字段：{required}，文件已损坏")
    # 逐区块重建并校验哈希（含创世块与休眠分支区块）。
    for entry in data["blocks"]:
        block = _block_from_dict(entry)
        _verify_block_signature(block)
    for branch in data["sleeping_branches"]:
        for entry in branch.get("blocks", []):
            block = _block_from_dict(entry)
            _verify_block_signature(block)
    return data


def rebuild_store(
    blocks: Iterable[dict],
    branches: Iterable[dict],
) -> ChainStore:
    """从存档 JSON 条目重建 ChainStore。

    条目为 dict 时先经 _block_from_dict 转换并校验哈希；账本与纪元快照不直接
    序列化，而是通过 append_main 重放主链（挖矿奖励 + 交易应用 + 纪元扫描）
    确定性重建；休眠分支只回填区块，不触碰账本/纪元。
    """
    store = ChainStore()
    for entry in blocks:
        block = _block_from_dict(entry)
        if block.height == 0:
            continue  # 创世块已由 ChainStore 初始化，仅校验哈希即可
        try:
            store.append_main(block)
        except ValueError as error:
            raise PersistenceError(f"主链重放失败（height={block.height}）：{error}") from error
    for branch in branches:
        branch_id = branch.get("branch_id")
        for entry in branch.get("blocks", []):
            block = _block_from_dict(entry)
            try:
                actual_id = store.add_sleeping_branch(block)
            except ValueError as error:
                raise PersistenceError(
                    f"休眠分支回填失败（height={block.height}）：{error}"
                ) from error
            if branch_id is not None and actual_id != branch_id:
                raise PersistenceError(
                    f"休眠分支标识校验失败：期望 {branch_id}，实际 {actual_id}"
                )
    return store


# ---------------------------------------------------------------------------
# CLI：python persistence.py export [输出路径]
# ---------------------------------------------------------------------------
def _cli(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="StratumGenesis 持久化工具")
    subparsers = parser.add_subparsers(dest="command")
    export_parser = subparsers.add_parser("export", help="校验并导出当前存档到指定路径")
    export_parser.add_argument("out", help="导出目标路径（与存档相同格式）")
    export_parser.add_argument("--src", default=DEFAULT_ARCHIVE_PATH, help="源存档路径")
    args = parser.parse_args(argv)

    if args.command == "export":
        try:
            data = load_state(args.src)
        except PersistenceError as error:
            print(f"[错误] {error}")
            return 1
        write_export(args.out, data)
        print(f"[导出完成] {args.src} -> {args.out}（format_version={FORMAT_VERSION}）")
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
