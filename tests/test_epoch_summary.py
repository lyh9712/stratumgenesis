"""StratumGenesis v0.3 阶段 B：mock 纪元摘要模块测试。

覆盖：边界触发时机、确定性、历史权重生效、平票确定性回退、finalized 后不可变、
休眠分支不产生摘要、/chain-state 追加字段、save->load 摘要逐字段一致，
以及阶段 A 遗留小修（存档加载时验签拒绝篡改签名）。
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.request
from dataclasses import replace

import persistence
import server as srv

from block_model import Block, PoiRecord, Proposal, TestCase
from block_validator import MIN_POI_TOKENS, validate_block
from chain_store import ChainStore
from crypto_key import generate_miner_keypair, sign_block_payload
from epoch_summary import EpochSummary
from mock_tokenizer import MOCK_TOKENIZER_ID, count_poi_tokens

BASE = "http://127.0.0.1:28417"

FEATURES = [
    "绑定聚合原语", "增量函数原语", "多参数求和原语",
    "负整数支持原语", "闭包捕获原语", "行注释原语",
]
LABELS = ["矿工甲", "矿工乙", "矿工丙"]


def http_json(path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def summary_fields(snapshot) -> tuple | None:
    """把快照摘要压成可比较元组（None 表示未封口）。"""
    if snapshot.summary is None:
        return None
    return (
        snapshot.summary_status,
        snapshot.summary.method_label,
        snapshot.summary.winner_candidate_id,
        snapshot.summary.winner_producer_label,
        snapshot.summary.final_text,
        snapshot.summary.tie_occurred,
        tuple(
            (c.candidate_id, c.text, c.producer_label, c.weight)
            for c in snapshot.summary.candidates
        ),
    )


class EpochSummaryUnitTests(unittest.TestCase):
    """不依赖 HTTP 的核心行为测试。"""

    def setUp(self):
        self.store = ChainStore()
        self.keypairs = [generate_miner_keypair() for _ in range(3)]

    def make_block(self, miner_index: int = 0, height: int | None = None, epoch: int = -1):
        target = self.store.height + 1 if height is None else height
        private, public = self.keypairs[miner_index]
        feature = FEATURES[target % len(FEATURES)]
        prompt = "design a deterministic epoch summary extension with sandbox tests"
        output = "reasoning token " * (MIN_POI_TOKENS + 2)
        counts = count_poi_tokens(prompt, output)
        proposal = Proposal(f"feature-{target}", feature, "(+ 1 2)", (TestCase("(+ 1 2)", 3),))
        poi = PoiRecord("manual", prompt, output, MOCK_TOKENIZER_ID,
                        counts.standard_input_tokens, counts.standard_output_tokens,
                        counts.standard_total_tokens)
        unsigned = Block(target, self.store.tip.block_hash, LABELS[miner_index], proposal, poi,
                         miner_pubkey=public, epoch=epoch)
        return replace(unsigned, signature_bytes=sign_block_payload(private, unsigned.canonical_bytes()))

    def append(self, block):
        self.assertTrue(validate_block(block, self.store).accepted)
        self.store.append_main(block)

    def append_n(self, count: int, pattern: list[int] | None = None):
        for index in range(count):
            miner_index = pattern[index % len(pattern)] if pattern else 0
            self.append(self.make_block(miner_index))

    # ---------------------------------------------------------------
    # 1) 边界触发时机：height=99 未封口，height=100 封口并确定摘要
    # ---------------------------------------------------------------
    def test_boundary_trigger_timing(self):
        self.append_n(99)
        epoch0 = self.store.epoch_manager.get_epoch_snapshot(0)
        self.assertIsNotNone(epoch0)
        self.assertFalse(epoch0.archived)
        self.assertIsNone(epoch0.summary)
        self.assertEqual(epoch0.summary_status, "pending")
        self.assertEqual(len(self.store.epoch_manager.summary_chain()), 0)
        self.append(self.make_block())
        epoch0 = self.store.epoch_manager.get_epoch_snapshot(0)
        self.assertTrue(epoch0.archived)
        self.assertIsNotNone(epoch0.summary)
        self.assertEqual(epoch0.summary_status, "finalized")
        self.assertEqual(epoch0.summary.epoch_number, 0)
        self.assertEqual(len(epoch0.summary.candidates), 3)
        self.assertEqual(len(self.store.epoch_manager.summary_chain()), 1)

    # ---------------------------------------------------------------
    # 2) 确定性：同参数两次构建 → 候选与结果逐字段一致
    # ---------------------------------------------------------------
    def test_deterministic_generation(self):
        def build():
            store = ChainStore()
            old = self.store
            self.store = store
            try:
                self.append_n(200, pattern=[0, 1, 2])
            finally:
                self.store = old
            return store

        store_a = build()
        store_b = build()
        for epoch_number in (0, 1):
            snap_a = store_a.epoch_manager.get_epoch_snapshot(epoch_number)
            snap_b = store_b.epoch_manager.get_epoch_snapshot(epoch_number)
            self.assertEqual(summary_fields(snap_a), summary_fields(snap_b))
        self.assertEqual(store_a.epoch_manager.summary_chain(), store_b.epoch_manager.summary_chain())
        # 同一状态下重复扫描也应得到相同结果
        again = store_a.epoch_manager.scan_chain(store_a.main_chain())
        self.assertEqual([summary_fields(item) for item in again],
                         [summary_fields(item) for item in store_a.epoch_manager.snapshots()])

    # ---------------------------------------------------------------
    # 3) 历史权重生效：贡献最多的矿工成为摘要胜者
    # ---------------------------------------------------------------
    def test_historical_weights_take_effect(self):
        # 矿工乙(1) 挖 3/5 的区块，历史贡献权重最高；甲/丙也各占一份
        self.append_n(99, pattern=[1, 1, 1, 0, 2])
        self.append(self.make_block(1))
        summary = self.store.epoch_manager.get_epoch_snapshot(0).summary
        self.assertEqual(summary.winner_producer_label, "矿工乙")
        weights = {candidate.producer_label: candidate.weight for candidate in summary.candidates}
        self.assertGreater(weights["矿工乙"], weights["矿工甲"])
        self.assertGreater(weights["矿工乙"], weights["矿工丙"])

    # ---------------------------------------------------------------
    # 4) 平票确定性回退：单矿工链全部等权 → 按候选 id 取首并记录
    # ---------------------------------------------------------------
    def test_tie_deterministic_fallback(self):
        self.append_n(100)
        summary = self.store.epoch_manager.get_epoch_snapshot(0).summary
        self.assertTrue(summary.tie_occurred)
        self.assertEqual(summary.winner_candidate_id, "mock-rule-v1:contributor-distribution")
        self.assertEqual(summary.status, "finalized")
        self.assertIsNotNone(summary.final_text)

    # ---------------------------------------------------------------
    # 5) finalized 后不再变化：继续追加 50 块摘要不变，新纪元未封口
    # ---------------------------------------------------------------
    def test_finalized_immutable(self):
        self.append_n(100)
        frozen = summary_fields(self.store.epoch_manager.get_epoch_snapshot(0))
        self.append_n(50)
        self.assertEqual(summary_fields(self.store.epoch_manager.get_epoch_snapshot(0)), frozen)
        epoch1 = self.store.epoch_manager.get_epoch_snapshot(1)
        self.assertIsNone(epoch1.summary)
        self.assertEqual(epoch1.summary_status, "pending")
        self.assertEqual(len(self.store.epoch_manager.summary_chain()), 1)

    # ---------------------------------------------------------------
    # 6) 休眠分支不产生摘要：边界候选进分支不影响快照与摘要链
    # ---------------------------------------------------------------
    def test_sleeping_branch_does_not_finalize_summary(self):
        self.append_n(100)
        before = self.store.epoch_manager.snapshots()
        chain_before = self.store.epoch_manager.summary_chain()
        for height in (101, 102, 103):
            branch = self.make_block(height=height)
            self.assertEqual(branch.epoch, 1)
            self.store.add_sleeping_branch(branch)
        self.assertEqual(self.store.epoch_manager.snapshots(), before)
        self.assertEqual(self.store.epoch_manager.summary_chain(), chain_before)
        self.assertEqual(self.store.height, 100)

    # ---------------------------------------------------------------
    # 7) 摘要链：按纪元顺序排列，为「大断层事件」留钩子
    # ---------------------------------------------------------------
    def test_summary_chain_ordered(self):
        self.append_n(250)
        chain = self.store.epoch_manager.summary_chain()
        self.assertEqual([item.epoch_number for item in chain], [0, 1])
        self.assertTrue(all(isinstance(item, EpochSummary) for item in chain))


class EpochSummaryPersistenceTests(unittest.TestCase):
    """save->load 摘要逐字段一致 + 阶段 A 遗留小修（验签）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name: str) -> str:
        return os.path.join(self.tmp.name, name)

    def first_miner(self, state):
        return srv.b64e(list(state.registry.miners)[0])

    # ---------------------------------------------------------------
    # 8) save->load 后摘要（候选/得票/胜者/状态/方法标签）逐字段一致
    # ---------------------------------------------------------------
    def test_summary_fields_identical_after_load(self):
        archive = self.path("chain.json")
        state = srv.build_server_state(fresh=True, persist_path=archive)  # 102 块，纪元 0 已封口
        srv.api_propose(state, {"proposal_text": "函数增量扩展", "miner_pubkey_b64": self.first_miner(state)})

        data = persistence.load_state(archive)
        store2 = persistence.rebuild_store(data["blocks"], data["sleeping_branches"])
        self.assertEqual(
            [summary_fields(item) for item in store2.epoch_manager.snapshots()],
            [summary_fields(item) for item in state.store.epoch_manager.snapshots()],
        )
        self.assertEqual(store2.epoch_manager.summary_chain(), state.store.epoch_manager.summary_chain())
        loaded = store2.epoch_manager.get_epoch_snapshot(0)
        self.assertEqual(loaded.summary_status, "finalized")
        self.assertEqual(loaded.summary.method_label, "mock-rule-v1")

    # ---------------------------------------------------------------
    # 阶段 A 遗留小修：存档中仅篡改签名（哈希不受影响）也会被拒绝加载
    # ---------------------------------------------------------------
    def test_tampered_signature_refused_on_load(self):
        archive = self.path("tampered-sig.json")
        state = srv.build_server_state(fresh=True, persist_path=archive)
        with open(archive, encoding="utf-8") as handle:
            data = json.load(handle)
        block = data["blocks"][50]
        raw = persistence._b64d(block["signature_bytes_b64"])
        block["signature_bytes_b64"] = persistence._b64e(bytes((raw[0] ^ 0xFF,)) + raw[1:])
        with open(archive, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        with self.assertRaises(persistence.PersistenceError) as cm:
            persistence.load_state(archive)
        self.assertIn("签名校验失败", str(cm.exception))


class EpochSummaryHttpTests(unittest.TestCase):
    """/chain-state epochs[] 追加摘要字段（不删旧字段）。"""

    def setUp(self):
        self.state = srv.ServerState(persist_path=None)  # 预沉积 102 块
        self.httpd = srv.create_server(self.state)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def test_chain_state_has_summary_fields(self):
        state = http_json("/chain-state")
        epochs = {item["epoch_number"]: item for item in state["epochs"]}
        self.assertIn(0, epochs)
        # 已归档纪元：返回 finalized 摘要与候选/得票/胜者
        epoch0 = epochs[0]
        self.assertTrue(epoch0["archived"])
        self.assertEqual(epoch0["summary_status"], "finalized")
        summary = epoch0["summary"]
        self.assertIsNotNone(summary)
        self.assertEqual(summary["status"], "finalized")
        self.assertEqual(summary["method_label"], "mock-rule-v1")
        self.assertIsNotNone(summary["final_text"])
        self.assertIsNotNone(summary["winner_candidate_id"])
        self.assertIsNotNone(summary["winner_producer_label"])
        self.assertIn("tie_occurred", summary)
        self.assertEqual(len(summary["candidates"]), 3)
        for candidate in summary["candidates"]:
            for field in ("candidate_id", "text", "producer_label", "weight"):
                self.assertIn(field, candidate)
        # 未封口纪元：summary 为空、状态 pending
        epoch1 = epochs[1]
        self.assertFalse(epoch1["archived"])
        self.assertEqual(epoch1["summary_status"], "pending")
        self.assertIsNone(epoch1["summary"])
        # 追加的摘要链字段存在且只含已确定摘要
        self.assertEqual(len(state["summary_chain"]), 1)
        self.assertEqual(state["summary_chain"][0]["status"], "finalized")
        # 既有字段不缺失（契约不破坏）
        self.assertIn("chain_height", state)
        self.assertTrue(state["blocks"][1]["height"] == 1)


if __name__ == "__main__":
    unittest.main()
