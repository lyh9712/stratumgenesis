"""StratumGenesis v0.3 · Pyodide 浏览器内核沙箱（纯 Python 侧）。

本模块在浏览器内的 Pyodide 运行时加载，复用项目真实的链核心模块
（block_model / chain_store / block_validator / crypto_key / novscript /
mock_tokenizer / persistence）。它是「浏览器内核」模式的唯一业务逻辑入口：

- 所有区块构造、ECDSA 签名、9 项校验、上链、语言演化、跨纪元失忆/引种、
  存档导出/导入，全部走与 server.py 完全相同的真实代码路径；
- **绝不**在 JS 侧重新实现 canonical_bytes() / 签名 —— 序列化与签名一律在
  Python 侧完成，避免逐字节不一致导致哈希/签名不符；
- 会话矿工密钥在浏览器内存中生成（不落盘、不进导出存档），导出存档只含
  区块与休眠分支，绝不含任何私钥（与 export_public 的剥离红线一致）。

本文件由 web/bridge.js 通过 Pyodide globals 调用；所有函数入参/返回值均为
JSON 字符串，便于跨越 JS↔Python 边界。

注意：本文件只导入项目核心模块，绝不导入 server.py（避免把 HTTP / 密钥托管
语义带进浏览器）。server.py 里的 seed/poi/提案映射逻辑在此处独立复刻，以保持
与后端「同一套 9 项校验」的一致性。
"""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from typing import Any

from block_model import Block, PoiRecord, Proposal, TestCase
from block_validator import MIN_POI_TOKENS, validate_block
from chain_store import ChainStore
from crypto_key import generate_miner_keypair, sign_block_payload
from mock_tokenizer import MOCK_TOKENIZER_ID, count_poi_tokens
from novscript import SandboxLimits, run_sandbox
from novscript.registry import BUILTIN_POOL, KERNEL_PRIMITIVES, spec_of
from persistence import FORMAT_VERSION, _block_to_dict, rebuild_store

# ---------------------------------------------------------------------------
# 复刻 server.py 的演示地层预沉积与提案映射（仅用真实核心模块，不导入 server）。
# ---------------------------------------------------------------------------
MINER_LABELS = ["沉积者·阿砚", "地层匠·沧石", "化石刻工·临渊"]

SEED_POOL = [
    ("绑定聚合原语", "(bind a 1)\n(bind b 2)\n(+ a b)", (TestCase("(+ 1 2)", 3),)),
    ("增量函数原语", "(bind inc (lambda (x) (+ x 1)))\n(inc 41)", (TestCase("((lambda (x) (+ x 1)) 41)", 42),)),
    ("多参数求和原语", "(+ 3 4)", (TestCase("(+ 3 4)", 7),)),
    ("负整数支持原语", "(+ -3 10)", (TestCase("(+ -3 10)", 7),)),
    ("闭包捕获原语", "((lambda (x) (+ x 5)) 3)", (TestCase("((lambda (x) (+ x 5)) 3)", 8),)),
    ("行注释原语", ";; 沉积层注释\n(+ 2 3)", (TestCase("(+ 2 3)", 5),)),
]

# 与 server.py _FEATURE_PRESETS 同口径（仅扩展原语关键词命中才返回非空 activation）。
_FEATURE_PRESETS = (
    (("减法", "减"), ("-",), "(- 10 3)", (TestCase("(- 10 3)", 7),)),
    (("乘法", "乘"), ("*",), "(* 3 4)", (TestCase("(* 3 4)", 12),)),
    (("整除",), ("//",), "(// 7 2)", (TestCase("(// 7 2)", 3),)),
    (("取模", "求余"), ("%",), "(% 7 3)", (TestCase("(% 7 3)", 1),)),
    (("列表",), ("list", "head"), "(head (list 1 2 3))", (TestCase("(head (list 1 2 3))", 1),)),
    (("cons",), ("cons", "list", "head"), "(head (cons 9 (list 1 2)))", (TestCase("(head (cons 9 (list 1 2)))", 9),)),
    (("取头", "head"), ("head", "list"), "(head (list 5 6))", (TestCase("(head (list 5 6))", 5),)),
    (("取尾", "tail"), ("tail", "list", "head"), "(head (tail (list 1 2 3)))", (TestCase("(head (tail (list 1 2 3)))", 2),)),
    (("长度", "length"), ("length", "list"), "(length (list 1 2 3))", (TestCase("(length (list 1 2 3))", 3),)),
    (("输出", "echo"), ("echo",), "(echo 1 2 3)", (TestCase("(echo 1 2)", {"type": "InternalNil"}),)),
    (("条件", "if"), ("if", "lt"), "(if (lt 1 2) 7 8)", (TestCase("(if (lt 1 2) 7 8)", 7),)),
)

SESSION_LABEL = "浏览器玩家"

# 会话级单例：store + 会话密钥 + 种子矿工标签映射。
_SESSION: dict[str, Any] = {
    "store": None,
    "seed_miners": {},          # pubkey(bytes) -> label
    "session_priv": None,       # bytes
    "session_pub": None,        # bytes
}


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text)


# ---------------------------------------------------------------------------
# PoI 记录生成（复刻 server.make_poi，保证通过 mock PoI 校验）。
# ---------------------------------------------------------------------------
def make_poi(feature_name: str, demo: str, tests, prompt_text: str,
             model_metadata: str = "manual-mock") -> PoiRecord:
    prompt = f"design a NovScript extension named {feature_name}: {prompt_text}"
    output = demo + " " + " ".join(getattr(t, "program", str(t)) for t in tests) + " " + "reasoning token " * (MIN_POI_TOKENS + 3)
    counts = count_poi_tokens(prompt, output)
    return PoiRecord(
        model_metadata, prompt, output, MOCK_TOKENIZER_ID,
        counts.standard_input_tokens, counts.standard_output_tokens,
        counts.standard_total_tokens,
    )


# ---------------------------------------------------------------------------
# 演示地层预沉积（复刻 server.seed_demo_chain，密钥仅存内存、不落盘、不导出）。
# ---------------------------------------------------------------------------
def _seed_demo_chain(store: ChainStore, seed_count: int = 102) -> None:
    pubkeys = list(_SESSION["seed_miners"].keys())
    for height in range(1, seed_count + 1):
        feature_name, demo, tests = SEED_POOL[(height - 1) % len(SEED_POOL)]
        public_key = pubkeys[height % len(pubkeys)]
        private_key = _seed_private_of(public_key)
        description = f"预沉积演示特性 {feature_name}（高度 {height}）"
        proposal = Proposal(f"seed-{height}", description, demo, tests)
        # 种子演示块沿用与后端 server.py 一致的 manual-mock 模型身份；
        # 仅用户后续提交的提案才使用 browser-kernel / 显式 model_metadata。
        poi = make_poi(feature_name, demo, tests, description, model_metadata="manual-mock")
        unsigned = Block(height, store.tip.block_hash,
                        _SESSION["seed_miners"][public_key], proposal, poi,
                        miner_pubkey=public_key)
        block = replace(unsigned, signature_bytes=sign_block_payload(private_key, unsigned.canonical_bytes()))
        result = validate_block(block, store)
        if not result.accepted:
            raise RuntimeError(f"seed block {height} rejected: {result.error_code}: {result.message}")
        store.append_main(block)


def _seed_private_of(public_key: bytes) -> bytes:
    """种子矿工私钥：与公钥配对、派生自会话确定性生成（仅内存）。"""
    # 在浏览器内核中，密钥本就在内存里；这里直接从会话密钥表取配对私钥。
    return _SESSION["seed_priv"].get(public_key)


# ---------------------------------------------------------------------------
# 提案文本 -> 结构化提案（复刻 server.generate_proposal）。
# ---------------------------------------------------------------------------
def generate_proposal(text: str):
    lowered = text.lower()
    for keywords, activation, demo, tests in _FEATURE_PRESETS:
        if any(keyword in lowered for keyword in keywords):
            return f"扩展原语 {activation[0]}", demo, tests, activation
    if any(k in lowered for k in ("函数", "lambda", "增量")):
        demo = "(bind inc (lambda (x) (+ x 1)))\n(inc 41)"
        tests = (TestCase("((lambda (x) (+ x 1)) 41)", 42),)
        return "增量函数扩展", demo, tests, ()
    if any(k in lowered for k in ("绑定", "bind", "变量")):
        demo = "(bind a 1)\n(bind b 2)\n(+ a b)"
        tests = (TestCase("(+ 1 2)", 3),)
        return "绑定聚合扩展", demo, tests, ()
    if "+" in text or "求和" in text or "加法" in text:
        demo = "(+ 1 2)"
        tests = (TestCase("(+ 1 2)", 3),)
        return "多参数求和扩展", demo, tests, ()
    if "注释" in text:
        demo = ";; " + text + "\n(+ 2 3)"
        tests = (TestCase("(+ 2 3)", 5),)
        return "行注释扩展", demo, tests, ()
    demo = "(bind x (+ 1 2))\nx"
    tests = (TestCase("(+ 1 2)", 3),)
    return "内核算术扩展", demo, tests, ()


# ---------------------------------------------------------------------------
# 会话初始化：构造浏览器内核链（创世 + 预沉积 + 会话矿工密钥）。
# ---------------------------------------------------------------------------
def py_init(seed_count: int = 102) -> str:
    if _SESSION["store"] is None:
        _build_session(seed_count)
    store = _SESSION["store"]
    return json.dumps({"chain_height": store.height, "mode": "browser-kernel"})


def py_reset(seed_count: int = 102) -> str:
    """重置会话（测试用）：清空链与密钥，重新预沉积。"""
    _SESSION["store"] = None
    _SESSION["seed_miners"] = {}
    _SESSION["seed_priv"] = {}
    _SESSION["session_priv"] = None
    _SESSION["session_pub"] = None
    return py_init(seed_count)


def _build_session(seed_count: int = 102) -> None:
        # 生成种子矿工密钥对（仅内存）。
    _SESSION["seed_miners"] = {}
    _SESSION["seed_priv"] = {}
    for label in MINER_LABELS:
        priv, pub = generate_miner_keypair()
        _SESSION["seed_miners"][pub] = label
        _SESSION["seed_priv"][pub] = priv
    # 生成会话矿工密钥（用于提交「浏览器玩家」自己的提案）。
    sess_priv, sess_pub = generate_miner_keypair()
    _SESSION["session_priv"] = sess_priv
    _SESSION["session_pub"] = sess_pub
    store = ChainStore()
    _seed_demo_chain(store, seed_count)
    _SESSION["store"] = store


# ---------------------------------------------------------------------------
# 链状态视图（与 server.api_chain_state 同形状，供既有前端渲染管线直接使用）。
# ---------------------------------------------------------------------------
def _label_of(pubkey: bytes) -> str:
    if pubkey == _SESSION.get("session_pub"):
        return SESSION_LABEL
    return _SESSION["seed_miners"].get(pubkey, "矿工-" + pubkey.hex()[:8])


def _block_view(block: Block, store: ChainStore) -> dict:
    snapshot = store.language_snapshot_at(block.height)
    return {
        "height": block.height,
        "epoch": block.epoch,
        "miner_label": "创世者" if block.height == 0 else _label_of(block.miner_pubkey),
        "miner_pubkey_b64": _b64e(block.miner_pubkey),
        "feature_name": _seed_name(block),
        "description": block.proposal.specification,
        "demo_code": block.proposal.demo_code,
        "test_cases": [{"program": t.program, "expected": t.expected} for t in block.proposal.test_cases],
        "block_hash_b64": _b64e(bytes.fromhex(block.block_hash)),
        "model_metadata": block.poi.model_metadata,
        "activation": list(block.activation),
        "language_features": sorted(snapshot.active_features) if snapshot else [],
    }


def _seed_name(block: Block) -> str:
    description = block.proposal.specification
    if description.startswith("预沉积演示特性"):
        return description.replace("预沉积演示特性 ", "").split("（")[0]
    return block.proposal.feature_id


def _epoch_view(store: ChainStore) -> list:
    out = []
    for snap in store.epoch_manager.snapshots():
        out.append({
            "epoch_number": snap.epoch_number,
            "start_height": snap.start_height,
            "end_height": snap.end_height,
            "block_count": len(snap.block_hashes),
            "archived": snap.archived,
            "active_features": sorted(snap.active_features),
            "epoch_base_features": sorted(snap.epoch_base_features),
            "epoch_new_features": sorted(snap.epoch_new_features),
            "cumulative_active_features": sorted(snap.cumulative_active_features),
            "summary": _summary_to_dict(snap.summary) if snap.summary else None,
            "summary_status": snap.summary_status,
        })
    return out


def _summary_to_dict(summary) -> dict:
    if summary is None:
        return None
    return {
        "status": summary.status,
        "method_label": summary.method_label,
        "final_text": summary.final_text,
        "winner_candidate_id": summary.winner_candidate_id,
        "winner_producer_label": summary.winner_producer_label,
        "tie_occurred": summary.tie_occurred,
        "candidates": [
            {
                "candidate_id": c.candidate_id,
                "text": c.text,
                "producer_label": c.producer_label,
                "weight": c.weight,
            }
            for c in summary.candidates
        ],
    }


def _miners_view(store: ChainStore) -> list:
    out = []
    for pubkey, label in sorted(_SESSION["seed_miners"].items(), key=lambda kv: kv[0]):
        out.append({"label": label, "miner_pubkey_b64": _b64e(pubkey),
                   "balance": store.utxo_ledger.get_balance(pubkey)})
    # 会话矿工
    if _SESSION.get("session_pub") is not None:
        out.append({"label": SESSION_LABEL, "miner_pubkey_b64": _b64e(_SESSION["session_pub"]),
                   "balance": store.utxo_ledger.get_balance(_SESSION["session_pub"])})
    return out


def _sleeping_view(store: ChainStore) -> list:
    out = []
    for branch_id, branch in store.sleeping_branches().items():
        items = []
        for block in branch:
            items.append({
                "height": block.height,
                "epoch": block.epoch,
                "miner_label": _label_of(block.miner_pubkey),
                "feature_name": block.proposal.feature_id,
                "description": block.proposal.specification,
                "demo_code": block.proposal.demo_code,
                "test_cases": [{"program": t.program, "expected": t.expected} for t in block.proposal.test_cases],
                "block_hash_b64": _b64e(bytes.fromhex(block.block_hash)),
                "model_metadata": block.poi.model_metadata,
                "reason": "休眠/落选区块",
            })
        out.append({"branch_id": branch_id, "blocks": items})
    return out


def py_chain_state() -> str:
    store = _SESSION["store"]
    if store is None:
        return json.dumps({"error": "kernel_not_initialized"})
    return json.dumps({
        "chain_height": store.height,
        "blocks": [_block_view(b, store) for b in store.main_chain()],
        "epochs": _epoch_view(store),
        "sleeping_branches": _sleeping_view(store),
        "miners": _miners_view(store),
        "epoch_blocks": 100,
        "current_active_features": sorted(store.epoch_active_features()),
        "current_epoch_base_features": sorted(_current_epoch_base(store)),
        "cumulative_active_features": sorted(store.ever_active_features()),
        "summary_chain": [_summary_to_dict(s) for s in store.epoch_manager.summary_chain()],
    })


def _current_epoch_base(store: ChainStore):
    current_epoch = store.epoch_of_height(store.height)
    first_height = current_epoch * 100
    first_block = next((b for b in store.main_chain() if b.height == first_height), None)
    return frozenset(first_block.activation) if first_block is not None else frozenset()


# ---------------------------------------------------------------------------
# 结构化提案（与 server.api_propose_structured 同口径，但签名用会话私钥）。
# 返回与 /propose-structured 一致的响应字典（JSON 字符串）。
# ---------------------------------------------------------------------------
_MAX_FEATURE_ID_LEN = 64
_MAX_SPECIFICATION_LEN = 2048
_MAX_CODE_LEN = 2048
_MAX_TEST_CASES = 16
_MAX_MODEL_METADATA_LEN = 64
_MODEL_METADATA_PATTERN = __import__("re").compile(r"^[A-Za-z0-9._-]+$")
_DEFAULT_MODEL_METADATA = "unspecified"


def _normalize_model_metadata(value):
    if value is None or value == "":
        return _DEFAULT_MODEL_METADATA
    if not isinstance(value, str):
        return None
    if len(value) > _MAX_MODEL_METADATA_LEN or not _MODEL_METADATA_PATTERN.match(value):
        return None
    return value


def _parse_structured_proposal(body: dict):
    feature_id = body.get("feature_id")
    if not isinstance(feature_id, str) or not feature_id:
        return None, "MISSING_FIELD", "feature_id 缺失或不是非空字符串"
    if len(feature_id) > _MAX_FEATURE_ID_LEN:
        return None, "PAYLOAD_TOO_LARGE", f"feature_id 超长：上限 {_MAX_FEATURE_ID_LEN}"
    specification = body.get("specification")
    if not isinstance(specification, str) or not specification:
        return None, "MISSING_FIELD", "specification 缺失或不是非空字符串"
    if len(specification) > _MAX_SPECIFICATION_LEN:
        return None, "PAYLOAD_TOO_LARGE", "specification 超长"
    demo_code = body.get("demo_code")
    if not isinstance(demo_code, str) or not demo_code:
        return None, "MISSING_FIELD", "demo_code 缺失或不是非空字符串"
    if len(demo_code) > _MAX_CODE_LEN:
        return None, "PAYLOAD_TOO_LARGE", "demo_code 超长"
    raw_cases = body.get("test_cases")
    if not isinstance(raw_cases, list):
        return None, "MISSING_FIELD", "test_cases 缺失或不是数组"
    if len(raw_cases) > _MAX_TEST_CASES:
        return None, "PAYLOAD_TOO_LARGE", f"test_cases 条数超限：上限 {_MAX_TEST_CASES}"
    cases = []
    for i, item in enumerate(raw_cases):
        if not isinstance(item, dict) or "expected" not in item:
            return None, "MISSING_FIELD", f"test_cases[{i}] 缺少 expected"
        program = item.get("program")
        if not isinstance(program, str) or not program:
            return None, "MISSING_FIELD", f"test_cases[{i}].program 缺失"
        if len(program) > _MAX_CODE_LEN:
            return None, "PAYLOAD_TOO_LARGE", f"test_cases[{i}].program 超长"
        cases.append(TestCase(program, item["expected"]))
    raw_activation = body.get("activation") or []
    if not isinstance(raw_activation, list):
        return None, "INVALID_FIELD_TYPE", "activation 必须是字符串数组"
    activation = []
    for name in raw_activation:
        if not isinstance(name, str):
            return None, "INVALID_FIELD_TYPE", "activation 内必须全是字符串"
        if name not in BUILTIN_POOL:
            return None, "UNKNOWN_FEATURE", f"activation 含未知原语 {name!r}"
        if name in activation:
            return None, "DUPLICATE_ACTIVATION", f"activation 含重复原语 {name!r}"
        activation.append(name)
    model_metadata = _normalize_model_metadata(body.get("model_metadata"))
    if model_metadata is None:
        return None, "INVALID_MODEL_METADATA", "model_metadata 非法"
    return {
        "feature_id": feature_id,
        "specification": specification,
        "demo_code": demo_code,
        "test_cases": tuple(cases),
        "activation": tuple(activation),
        "model_metadata": model_metadata,
    }, None, None


def py_propose_structured(payload_json: str) -> str:
    store = _SESSION["store"]
    if store is None:
        return json.dumps({"success": False, "reason": "内核未初始化", "error_code": "KERNEL_NOT_READY"})
    try:
        body = json.loads(payload_json)
    except Exception as err:
        return json.dumps({"success": False, "reason": f"请求体不是合法 JSON：{err}", "error_code": "BAD_JSON"})
    payload, code, reason = _parse_structured_proposal(body)
    if payload is None:
        return json.dumps({"success": False, "reason": reason, "error_code": code, "chain_height": store.height})

    priv = _SESSION["session_priv"]
    pub = _SESSION["session_pub"]
    proposal = Proposal(payload["feature_id"], payload["specification"], payload["demo_code"], payload["test_cases"])
    poi = make_poi(payload["feature_id"], payload["demo_code"], payload["test_cases"],
                   payload["specification"], model_metadata=payload["model_metadata"])
    unsigned = Block(store.height + 1, store.tip.block_hash, SESSION_LABEL, proposal, poi,
                     miner_pubkey=pub, activation=payload["activation"])
    block = replace(unsigned, signature_bytes=sign_block_payload(priv, unsigned.canonical_bytes()))

    result = validate_block(block, store)
    if not result.accepted:
        try:
            store.add_sleeping_branch(block)
        except ValueError:
            pass
        return json.dumps({
            "success": False,
            "reason": f"校验未通过（{result.stage}）",
            "error_code": result.error_code,
            "block_hash_b64": _b64e(bytes.fromhex(block.block_hash)),
            "is_sleeping_branch": True,
            "chain_height": store.height,
            "model_metadata": payload["model_metadata"],
        })
    store.append_main(block)
    return json.dumps({
        "success": True,
        "reason": "校验通过，已写入主链",
        "error_code": None,
        "block_hash_b64": _b64e(bytes.fromhex(block.block_hash)),
        "is_sleeping_branch": False,
        "chain_height": store.height,
        "model_metadata": payload["model_metadata"],
    })


# ---------------------------------------------------------------------------
# 提案文本入口（复刻 server.api_propose 的「关键词映射 + 真实校验」语义）。
# ---------------------------------------------------------------------------
def py_propose_text(text_json: str) -> str:
    store = _SESSION["store"]
    if store is None:
        return json.dumps({"success": False, "reason": "内核未初始化", "error_code": "KERNEL_NOT_READY"})
    try:
        body = json.loads(text_json)
    except Exception as err:
        return json.dumps({"success": False, "reason": f"请求体不是合法 JSON：{err}", "error_code": "BAD_JSON"})
    text = str(body.get("text", "")).strip()
    model_metadata = _normalize_model_metadata(body.get("model_metadata")) or _DEFAULT_MODEL_METADATA
    if not text:
        return json.dumps({"success": False, "reason": "提案文本不能为空", "error_code": "MISSING_FIELD"})
    feature_name, demo, tests, activation = generate_proposal(text)
    payload = {
        "feature_id": feature_name,
        "specification": text,
        "demo_code": demo,
        "test_cases": [{"program": t.program, "expected": t.expected} for t in tests],
        "activation": list(activation),
        "model_metadata": model_metadata,
    }
    return py_propose_structured(json.dumps(payload))


# ---------------------------------------------------------------------------
# NovScript 沙箱执行（复刻 server.api_eval_novscript）。
# ---------------------------------------------------------------------------
_ERROR_LABELS = {
    "LexError": "词法错误", "ParseError": "语法错误", "NameError": "未绑定名称",
    "TypeError": "类型错误", "ArityError": "参数数量错误", "RecursionError": "递归超限",
    "ResourceLimitError": "资源限制", "SandboxError": "沙箱错误",
}


def py_eval(code_json: str) -> str:
    store = _SESSION["store"]
    if store is None:
        return json.dumps({"ok": False, "error_type": "KernelError", "error_message": "内核未初始化"})
    try:
        body = json.loads(code_json)
        code = str(body.get("code", ""))
    except Exception:
        code = ""
    # 默认按「创世内核 + 链级已激活原语」执行（与后端 api_eval_novscript 同口径）。
    result = run_sandbox(code, registry=store.language_registry)
    return json.dumps({
        "ok": result.ok,
        "value": result.value,
        "error_type": _ERROR_LABELS.get(result.error_type, result.error_type),
        "error_message": result.error_message,
        "steps": result.steps,
        "output": result.output,
    })


# ---------------------------------------------------------------------------
# 存档导出 / 导入（chain-v2 格式，但**绝不**包含矿工私钥）。
# ---------------------------------------------------------------------------
def py_export_archive() -> str:
    store = _SESSION["store"]
    if store is None:
        return json.dumps({"error": "kernel_not_initialized"})
    branches = []
    for branch_id, blocks in store.sleeping_branches().items():
        branches.append({
            "branch_id": branch_id,
            "blocks": [_block_to_dict(b) for b in blocks],
        })
    data = {
        "format_version": FORMAT_VERSION,
        "blocks": [_block_to_dict(b) for b in store.main_chain()],
        "sleeping_branches": branches,
    }
    return json.dumps(data, ensure_ascii=False)


def py_import_archive(data_json: str) -> str:
    try:
        data = json.loads(data_json)
    except Exception as err:
        return json.dumps({"success": False, "reason": f"存档不是合法 JSON：{err}"})
    if not isinstance(data, dict) or data.get("format_version") != FORMAT_VERSION:
        actual = data.get("format_version") if isinstance(data, dict) else "未知"
        return json.dumps({"success": False,
                           "reason": f"存档格式版本不匹配：期望 {FORMAT_VERSION}，实际 {actual}"})
    try:
        store = rebuild_store(data["blocks"], data.get("sleeping_branches", []))
    except Exception as err:
        return json.dumps({"success": False, "reason": f"存档重放失败：{err}"})
    _SESSION["store"] = store
    return json.dumps({"success": True, "chain_height": store.height})


# ---------------------------------------------------------------------------
# 休眠分支升级（阶段 E）：本卡时间所限，先留桩并在 README 标注。
# 复刻 server.api_branches / chain_store.promote_branch 的完整逻辑可在后续迭代接入。
# ---------------------------------------------------------------------------
def py_promote(head_hash_json: str) -> str:
    store = _SESSION["store"]
    if store is None:
        return json.dumps({"status": "rejected", "error_code": "KERNEL_NOT_READY"})
    try:
        body = json.loads(head_hash_json)
        head_hash = body.get("head_hash") or body.get("headHash")
    except Exception:
        head_hash = None
    # 留桩：返回未实现，由前端降级提示「此能力需后续迭代」。
    return json.dumps({
        "status": "not_implemented",
        "error_code": "PROMOTE_NOT_IMPLEMENTED",
        "message": "浏览器内核当前版本暂未实现休眠分支升级（reorg）；该能力在后续迭代接入。",
        "requested_head": head_hash,
    })
