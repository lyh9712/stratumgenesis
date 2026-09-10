"""StratumGenesis 极简本地 HTTP 服务。

只使用 Python 标准库 http.server，不引入 flask/fastapi 等第三方 Web 框架
（ecdsa 为项目既有依赖）。监听 127.0.0.1:28417，仅限本机访问，不支持公网。

本服务加载全部 StratumGenesis 单机模块，启动时初始化创世链并预沉积一段
演示地层；状态默认持久化到 data/chain_v1.json（实验级 JSON 存档，非生产级
存储）：若存档存在则加载继续，否则重建演示链并立即落盘；每次链状态变更后
自动保存；--fresh 可忽略存档从创世重建。

已知局限（与全局项目一致）：
1. LLM 摘要未来会有信息衰减与幻觉风险；当前为 mock-rule-v1 规则模板确定性摘要
   （非真实 LLM），摘要链仅线性低速增长。
2. 共识仅适配小规模仿真网络；这里只是单进程串行处理，无真实网络。
3. 沙箱是教学级纯计算隔离，不是生产安全容器。
4. 纯非金融激励存在参与者流失风险。
5. 存档为实验级 JSON 持久化：无加密、私钥明文落盘、无校验和校验之外的恢复保障；
   无 P2P、无公网部署、无身份鉴权、无可交易代币。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import threading
from dataclasses import dataclass, field, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import persistence

from block_model import Block, PoiRecord, Proposal, TestCase
from block_validator import MIN_POI_TOKENS, validate_block
from candidate_pool import CandidatePool
from chain_store import ChainStore
from conflict_voter import resolve_conflict
from crypto_key import generate_miner_keypair, sign_block_payload
from epoch_manager import EPOCH_BLOCKS
from mock_tokenizer import MOCK_TOKENIZER_ID, count_poi_tokens
from novscript import run_sandbox
from weight_calculator import calculate_historical_weights

HOST = "127.0.0.1"
PORT = 28417

# 以 server.py 所在目录定位 index.html，避免因启动时工作目录不同而 404。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(BASE_DIR, "index.html")
# 默认存档路径（data/chain_v1.json，已在 .gitignore 中排除）。
DEFAULT_PERSIST_PATH = os.path.join(BASE_DIR, "data", persistence.DEFAULT_ARCHIVE_NAME)
# 自动保存的串行锁：ThreadingHTTPServer 多线程下避免并发写同一 tmp 文件。
_SAVE_LOCK = threading.Lock()

# 真实沙箱错误类型 -> 中文分类（前端直接展示）
ERROR_LABELS = {
    "LexError": "词法错误",
    "ParseError": "语法错误",
    "NameError": "未绑定名称",
    "TypeError": "类型错误",
    "ArityError": "参数数量错误",
    "RecursionError": "递归超限",
    "ResourceLimitError": "资源限制",
    "SandboxError": "沙箱错误",
}

MINER_LABELS = ["沉积者·阿砚", "地层匠·沧石", "化石刻工·临渊"]


def b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def b64d(text: str) -> bytes:
    return base64.b64decode(text)


# ---------------------------------------------------------------------------
# 矿工注册表：服务端持有全部密钥，区块签名在服务端完成。
# 前端只发送 miner_pubkey_b64 作为身份选择。
# ---------------------------------------------------------------------------
@dataclass
class MinerRegistry:
    """pubkey(raw) -> (label, private_key) 的内存矿工表。"""

    miners: dict[bytes, tuple[str, bytes]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.miners:
            for label in MINER_LABELS:
                private_key, public_key = generate_miner_keypair()
                self.miners[public_key] = (label, private_key)

    def private_of(self, public_key: bytes) -> bytes | None:
        entry = self.miners.get(public_key)
        return entry[1] if entry else None

    def label_of(self, public_key: bytes) -> str:
        entry = self.miners.get(public_key)
        return entry[0] if entry else "未知矿工"


# ---------------------------------------------------------------------------
# 提案文本 -> 演示代码/测试用例 的简化映射。
# 真实 NovScript 内核只支持整数、函数与 + 加法，因此生成的代码必须在内核
# 语法范围内，否则会被第 4/5 阶段校验真实拒绝。
# 语言演化：命中「扩展原语关键词」的提案返回非空 activation（本块要激活的
# 新原语名），并经第 5/6 阶段校验确认后真正注册进链级语言注册表。
# ---------------------------------------------------------------------------
# 扩展原语关键词表：提案文本命中任意关键词 -> (原语名元组, demo, tests)。
# 每个 demo 都依赖其 activation 原语（demo 用到的每个原语都必须包含在
# activation 中），保证正负测试语义成立。
_FEATURE_PRESETS: tuple[tuple[tuple[str, ...], tuple[str, ...], str, tuple[TestCase, ...]], ...] = (
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


def generate_proposal(text: str) -> tuple[str, str, tuple[TestCase, ...], tuple[str, ...]]:
    lowered = text.lower()
    # 扩展原语关键词优先匹配：命中则激活对应原语（语言真实演化）。
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


def make_poi(feature_name: str, demo: str, tests: tuple[TestCase, ...], prompt_text: str) -> PoiRecord:
    """生成能通过 mock PoI 校验的 PoI 记录（附带足够的填充词元）。"""
    prompt = f"design a NovScript extension named {feature_name}: {prompt_text}"
    output = demo + " " + " ".join(t.program for t in tests) + " " + "reasoning token " * (MIN_POI_TOKENS + 3)
    counts = count_poi_tokens(prompt, output)
    return PoiRecord(
        "manual-mock", prompt, output, MOCK_TOKENIZER_ID,
        counts.standard_input_tokens, counts.standard_output_tokens,
        counts.standard_total_tokens,
    )


# ---------------------------------------------------------------------------
# 演示地层预沉积：启动时用真实校验流水线写入 102 个合法区块，
# 让前端一打开就有完整剖面与纪元抬升可展示。全部走真实 append_main，
# 因此会真实发放 UTXO 奖励并生成纪元快照。
# ---------------------------------------------------------------------------
SEED_POOL = [
    ("绑定聚合原语", "(bind a 1)\n(bind b 2)\n(+ a b)", (TestCase("(+ 1 2)", 3),)),
    ("增量函数原语", "(bind inc (lambda (x) (+ x 1)))\n(inc 41)", (TestCase("((lambda (x) (+ x 1)) 41)", 42),)),
    ("多参数求和原语", "(+ 3 4)", (TestCase("(+ 3 4)", 7),)),
    ("负整数支持原语", "(+ -3 10)", (TestCase("(+ -3 10)", 7),)),
    ("闭包捕获原语", "((lambda (x) (+ x 5)) 3)", (TestCase("((lambda (x) (+ x 5)) 3)", 8),)),
    ("行注释原语", ";; 沉积层注释\n(+ 2 3)", (TestCase("(+ 2 3)", 5),)),
]


def seed_demo_chain(store: ChainStore, registry: MinerRegistry, count: int = 102) -> None:
    """按序构造、签名、校验并追加 count 个演示区块。"""
    pubkeys = list(registry.miners.keys())
    for height in range(1, count + 1):
        feature_name, demo, tests = SEED_POOL[(height - 1) % len(SEED_POOL)]
        public_key = pubkeys[height % len(pubkeys)]
        private_key = registry.private_of(public_key)
        description = f"预沉积演示特性 {feature_name}（高度 {height}）"
        proposal = Proposal(f"seed-{height}", description, demo, tests)
        poi = make_poi(feature_name, demo, tests, description)
        unsigned = Block(height, store.tip.block_hash, registry.label_of(public_key), proposal, poi,
                         miner_pubkey=public_key)
        block = replace(unsigned, signature_bytes=sign_block_payload(private_key, unsigned.canonical_bytes()))
        result = validate_block(block, store)
        if not result.accepted:
            raise RuntimeError(f"seed block {height} rejected: {result}")
        store.append_main(block)


# ---------------------------------------------------------------------------
# 服务状态（每次 create_server 重建，测试与正式运行互不干扰）
# ---------------------------------------------------------------------------
@dataclass
class ServerState:
    store: ChainStore = field(default_factory=ChainStore)
    pool: CandidatePool = field(default_factory=CandidatePool)
    registry: MinerRegistry = field(default_factory=MinerRegistry)
    rejection_reasons: dict[str, str] = field(default_factory=dict)
    seed_count: int = 102
    # 存档路径；为 None 时禁用自动保存（测试/独立构造默认禁用，避免污染 data/）。
    persist_path: str | None = None

    def __post_init__(self) -> None:
        # 仅当主链只有创世块（height==0）时才预沉积演示地层；
        # 从存档恢复的状态（height>0）不再重复预沉积。
        if self.store.height == 0:
            seed_demo_chain(self.store, self.registry, self.seed_count)


def _auto_save(state: ServerState) -> None:
    """链状态变更后自动落盘；保存失败只打印中文警告，不影响本次内存操作。"""
    if not state.persist_path:
        return
    try:
        with _SAVE_LOCK:
            persistence.save_state(
                state.persist_path, state.store, state.registry.miners, state.rejection_reasons
            )
    except Exception as error:  # 保存失败不得影响 API 结果
        print(f"[警告] 自动保存存档失败（不影响本次操作结果）：{error}")


def build_server_state(
    *,
    fresh: bool = False,
    persist_path: str = DEFAULT_PERSIST_PATH,
) -> ServerState:
    """按启动策略构建服务状态。

    - fresh=True：忽略存档，从创世重建演示链（预沉积 102 块）并立即落盘；
    - 存档不存在：维持 v0.2 行为（创世 + 预沉积 102 块）并立即落盘；
    - 存档存在：加载并校验后继续（不再预沉积）；损坏/版本不匹配抛 PersistenceError。
    """
    if fresh or not os.path.exists(persist_path):
        if fresh:
            # 旧存档非破坏处置：重建前先保留为 .bak-<旧format_version>，不删除。
            persistence.backup_old_archive(persist_path)
        state = ServerState(persist_path=persist_path)
        _auto_save(state)
        return state
    data = persistence.load_state(persist_path)
    store = persistence.rebuild_store(data["blocks"], data["sleeping_branches"])
    registry = MinerRegistry(miners=persistence.miners_from_list(data["miners"]))
    return ServerState(
        store=store,
        pool=CandidatePool(),
        registry=registry,
        rejection_reasons=dict(data["rejection_reasons"]),
        seed_count=0,
        persist_path=persist_path,
    )


# ---------------------------------------------------------------------------
# 三个 API 的实现
# ---------------------------------------------------------------------------
def api_chain_state(state: ServerState) -> dict:
    store = state.store
    blocks = []
    for block in store.main_chain():
        snapshot = store.language_snapshot_at(block.height)
        blocks.append({
            "height": block.height,
            "epoch": block.epoch,
            "miner_label": "创世者" if block.height == 0 else state.registry.label_of(block.miner_pubkey),
            "miner_pubkey_b64": b64e(block.miner_pubkey),
            "feature_name": block.proposal.feature_id if block.height == 0 else _seed_name(block),
            "description": block.proposal.specification,
            "demo_code": block.proposal.demo_code,
            "test_cases": [{"program": t.program, "expected": t.expected} for t in block.proposal.test_cases],
            "block_hash_b64": b64e(bytes.fromhex(block.block_hash)),
            # 语言演化：本块激活的原语名 + 上链后语言可见特性数（语言快照）。
            "activation": list(block.activation),
            "language_features": sorted(snapshot.active_features) if snapshot else [],
        })
    epochs = []
    for snapshot in store.epoch_manager.snapshots():
        epochs.append({
            "epoch_number": snapshot.epoch_number,
            "start_height": snapshot.start_height,
            "end_height": snapshot.end_height,
            "block_count": len(snapshot.block_hashes),
            "archived": snapshot.archived,
            # v0.3 阶段 B 追加：已归档纪元返回 finalized 摘要；未封口纪元为空。
            "summary": _summary_to_dict(snapshot.summary) if snapshot.summary else None,
            "summary_status": snapshot.summary_status,
            # v0.3 阶段 C 追加：该纪元结束时链级已激活的语言特性。
            "active_features": sorted(snapshot.active_features),
        })
    sleeping = []
    for branch in store.sleeping_branches().values():
        for block in branch:
            sleeping.append({
                "height": block.height,
                "epoch": block.epoch,
                "miner_label": state.registry.label_of(block.miner_pubkey),
                "feature_name": block.proposal.feature_id,
                "description": block.proposal.specification,
                "demo_code": block.proposal.demo_code,
                "test_cases": [{"program": t.program, "expected": t.expected} for t in block.proposal.test_cases],
                "block_hash_b64": b64e(bytes.fromhex(block.block_hash)),
                "reason": state.rejection_reasons.get(block.block_hash, "休眠/落选区块"),
            })
    miners = []
    # 按公钥字节稳定排序输出，保证「保存前/加载后」chain-state 完全一致；
    # 排序只影响数组顺序，不影响任何字段内容（前端按序轮换矿工，无副作用）。
    for public_key in sorted(state.registry.miners, key=lambda key: key):
        label, _ = state.registry.miners[public_key]
        miners.append({
            "label": label,
            "miner_pubkey_b64": b64e(public_key),
            "balance": store.utxo_ledger.get_balance(public_key),
        })
    return {
        "chain_height": store.height,
        "blocks": blocks,
        "epochs": epochs,
        "sleeping_branches": sleeping,
        "miners": miners,
        "epoch_blocks": EPOCH_BLOCKS,
        # v0.3 阶段 C 追加：当前链级已激活的语言特性（语言演化状态）。
        "current_active_features": sorted(store.language_registry.snapshot()),
        # v0.3 阶段 B 追加：按纪元顺序的已确定摘要链（为「大断层事件」留钩子）。
        "summary_chain": [_summary_to_dict(item) for item in store.epoch_manager.summary_chain()],
    }


def _summary_to_dict(summary) -> dict:
    """将已确定摘要转成前端可展示 JSON（追加字段，不改变既有响应结构）。"""
    return {
        "status": summary.status,
        "method_label": summary.method_label,
        "final_text": summary.final_text,
        "winner_candidate_id": summary.winner_candidate_id,
        "winner_producer_label": summary.winner_producer_label,
        "tie_occurred": summary.tie_occurred,
        "candidates": [
            {
                "candidate_id": candidate.candidate_id,
                "text": candidate.text,
                "producer_label": candidate.producer_label,
                "weight": candidate.weight,
            }
            for candidate in summary.candidates
        ],
    }


def _seed_name(block: Block) -> str:
    """种子区块显示特性名（去掉编号与描述包装）。"""
    description = block.proposal.specification
    if description.startswith("预沉积演示特性"):
        return description.replace("预沉积演示特性 ", "").split("（")[0]
    return block.proposal.feature_id


def api_propose(state: ServerState, body: dict) -> dict:
    store = state.store
    text = str(body.get("proposal_text", "")).strip()
    try:
        public_key = b64d(str(body.get("miner_pubkey_b64", "")))
    except Exception:
        public_key = b""
    if not text:
        return {"success": False, "reason": "提案文本不能为空", "block_hash_b64": None,
                "is_sleeping_branch": False, "chain_height": store.height}
    private_key = state.registry.private_of(public_key)
    if private_key is None:
        return {"success": False, "reason": "未知矿工身份，请先从 /chain-state 选择矿工", "block_hash_b64": None,
                "is_sleeping_branch": False, "chain_height": store.height}

    feature_name, demo, tests, activation = generate_proposal(text)
    proposal = Proposal(feature_name, text, demo, tests)
    poi = make_poi(feature_name, demo, tests, text)
    unsigned = Block(store.height + 1, store.tip.block_hash, state.registry.label_of(public_key), proposal, poi,
                     miner_pubkey=public_key, activation=activation)
    block = replace(unsigned, signature_bytes=sign_block_payload(private_key, unsigned.canonical_bytes()))

    # 完整 8 阶段校验（第 0 步 ECDSA 签名由服务端真实完成）
    result = validate_block(block, store)
    if not result.accepted:
        # 校验不通过：存入休眠分支，不修改账本与纪元快照。
        try:
            store.add_sleeping_branch(block)
        except ValueError:
            pass
        state.rejection_reasons[block.block_hash] = f"{result.stage}: {result.error_code}"
        _auto_save(state)
        return {"success": False, "reason": f"校验未通过（{result.stage}）", "block_hash_b64": b64e(bytes.fromhex(block.block_hash)),
                "is_sleeping_branch": True, "chain_height": store.height}

    # 送入候选池，按 (父哈希, 高度) 分组；取回本组执行加权投票。
    state.pool.validate_and_submit(block, store)
    key = next((k for k, v in state.pool.groups().items() if block in v), None)
    if key is None:
        return {"success": False, "reason": "候选池分组异常", "block_hash_b64": None,
                "is_sleeping_branch": False, "chain_height": store.height}
    candidates = state.pool.remove_group(key)
    weights = calculate_historical_weights(store.main_chain())
    vote = resolve_conflict(candidates, weights)
    store.apply_vote_result(vote)
    # 链状态已变更（胜者上链 / 落选或平票入休眠分支），立即自动保存。
    _auto_save(state)

    if vote.status == "vote_tie":
        return {"success": False, "reason": "同高度冲突且权重平票，全部进入休眠分支", "block_hash_b64": b64e(bytes.fromhex(block.block_hash)),
                "is_sleeping_branch": True, "chain_height": store.height}
    if store.tip.block_hash != block.block_hash:
        return {"success": False, "reason": "同高度冲突中该候选落选，已进入休眠分支", "block_hash_b64": b64e(bytes.fromhex(block.block_hash)),
                "is_sleeping_branch": True, "chain_height": store.height}
    return {"success": True, "reason": "校验通过，已写入主链", "block_hash_b64": b64e(bytes.fromhex(block.block_hash)),
            "is_sleeping_branch": False, "chain_height": store.height}


def api_eval_novscript(state: ServerState, body: dict) -> dict:
    code = str(body.get("code", ""))
    # 默认按「创世内核 + 当前链级已激活原语」执行：提案激活的新原语立即可用。
    result = run_sandbox(code, registry=state.store.language_registry)
    return {
        "ok": result.ok,
        "value": result.value,
        "error_type": ERROR_LABELS.get(result.error_type, result.error_type),
        "error_message": result.error_message,
        "steps": result.steps,
        "output": result.output,
    }


# ---------------------------------------------------------------------------
# HTTP handler 与服务器工厂
# ---------------------------------------------------------------------------
def build_handler(state: ServerState):
    class StratumHandler(BaseHTTPRequestHandler):
        server_version = "StratumGenesis/0.1"

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                data = json.loads(raw.decode("utf-8"))
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}

        def _send_json(self, status: int, obj) -> None:
            payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _serve_index(self) -> None:
            try:
                with open(INDEX_PATH, "rb") as fh:
                    payload = fh.read()
            except OSError:
                self.send_error(404, "index.html not found")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self._serve_index()
                return
            if self.path == "/chain-state":
                self._send_json(200, api_chain_state(state))
                return
            self.send_error(404, "not found")

        def do_POST(self) -> None:
            body = self._read_json()
            if self.path == "/propose":
                self._send_json(200, api_propose(state, body))
            elif self.path == "/eval-novscript":
                self._send_json(200, api_eval_novscript(state, body))
            else:
                self.send_error(404, "not found")

        def log_message(self, fmt, *args) -> None:
            print(f"[stratum] {self.address_string()} {fmt % args}")

    return StratumHandler


def create_server(state: ServerState | None = None) -> ThreadingHTTPServer:
    """创建绑定 127.0.0.1:28417 的服务器。

    测试与独立构造默认传 None：ServerState() 的 persist_path=None 禁用自动保存，
    避免测试污染 data/ 存档；正式启动由 main() 传入带存档路径的状态。
    """
    state = state or ServerState()
    handler = build_handler(state)
    httpd = ThreadingHTTPServer((HOST, PORT), handler)
    httpd.state = state  # type: ignore[attr-defined]
    return httpd


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="StratumGenesis 本地服务")
    parser.add_argument("--fresh", action="store_true",
                        help="忽略存档，从创世重建并重新预沉积演示地层（演示复位用）")
    parser.add_argument("--archive", metavar="PATH", default=DEFAULT_PERSIST_PATH,
                        help=f"存档文件路径（默认 {DEFAULT_PERSIST_PATH}）")
    parser.add_argument("--export", metavar="PATH", default=None,
                        help="校验当前存档并导出到指定路径后退出（与存档相同格式）")
    args = parser.parse_args(argv)

    # 导出模式：不启动服务，校验源存档后原样写入目标路径。
    if args.export is not None:
        try:
            data = persistence.load_state(args.archive)
            persistence.write_export(args.export, data)
        except persistence.PersistenceError as error:
            print(f"[错误] 导出失败：{error}")
            sys.exit(1)
        print(f"[导出完成] {args.archive} -> {args.export}（format_version={persistence.FORMAT_VERSION}）")
        return

    try:
        state = build_server_state(fresh=args.fresh, persist_path=args.archive)
    except persistence.PersistenceError as error:
        print(f"[错误] 存档加载失败：{error}")
        print("提示：如想保留旧存档并在别处重建演示链，请改用 python server.py --archive <新存档路径>；")
        print("      如需忽略旧存档重建（旧档会保留为 .bak），请使用 python server.py --fresh")
        sys.exit(1)

    httpd = create_server(state)
    print("StratumGenesis 本地服务已启动")
    print(f"  访问地址：http://{HOST}:{PORT}/index.html")
    print(f"  当前主链高度：{state.store.height}")
    print(f"  存档路径：{args.archive}（每次链状态变更自动保存）")
    print("  提示：--fresh 可忽略存档重建演示链；--export 可导出链数据")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
