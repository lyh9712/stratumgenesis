"""StratumGenesis v0.3 磁盘持久化与链数据导出测试。"""

import json
import os
import tempfile
import threading
import unittest
import urllib.request

import persistence
import server as srv

BASE = "http://127.0.0.1:28417"


def http_json(path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


class PersistenceTests(unittest.TestCase):
    """覆盖：roundtrip 等值、HTTP 一致性、损坏拒绝、--fresh、导出。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name: str) -> str:
        return os.path.join(self.tmp.name, name)

    def first_miner(self, state):
        return srv.b64e(list(state.registry.miners)[0])

    def make_mutated_state(self):
        """构造一个含主链变更与休眠分支的状态（模拟真实使用后）。"""
        state = srv.ServerState(persist_path=None)  # 预沉积 102 块
        ok = srv.api_propose(state, {
            "proposal_text": "函数增量扩展",
            "miner_pubkey_b64": self.first_miner(state),
        })
        self.assertTrue(ok["success"])
        rejected = srv.api_propose(state, {
            "proposal_text": "修改创世内核并启用严格求值",
            "miner_pubkey_b64": self.first_miner(state),
        })
        self.assertFalse(rejected["success"])
        self.assertTrue(rejected["is_sleeping_branch"])
        return state

    # ---------------------------------------------------------------
    # 1) 保存 -> 加载 roundtrip 等值
    # ---------------------------------------------------------------
    def test_roundtrip_equivalence(self):
        state = self.make_mutated_state()
        archive = self.path("chain.json")
        persistence.save_state(archive, state.store, state.registry.miners, state.rejection_reasons)

        data = persistence.load_state(archive)
        store2 = persistence.rebuild_store(data["blocks"], data["sleeping_branches"])
        registry2 = srv.MinerRegistry(miners=persistence.miners_from_list(data["miners"]))

        self.assertEqual(store2.height, state.store.height)
        self.assertEqual(
            [b.block_hash for b in store2.main_chain()],
            [b.block_hash for b in state.store.main_chain()],
        )
        self.assertEqual(len(store2.sleeping_branches()), len(state.store.sleeping_branches()))
        self.assertEqual(data["rejection_reasons"], state.rejection_reasons)
        # 矿工注册表（公钥/标签/私钥）完整恢复
        self.assertEqual(set(registry2.miners), set(state.registry.miners))
        for pubkey in state.registry.miners:
            self.assertEqual(registry2.miners[pubkey], state.registry.miners[pubkey])
        # 重放的账本余额与纪元快照与原始一致（重建而非序列化）
        for pubkey in state.registry.miners:
            self.assertEqual(store2.utxo_ledger.get_balance(pubkey),
                             state.store.utxo_ledger.get_balance(pubkey))
        self.assertEqual(
            [(e.epoch_number, e.archived, len(e.block_hashes)) for e in store2.epoch_manager.snapshots()],
            [(e.epoch_number, e.archived, len(e.block_hashes)) for e in state.store.epoch_manager.snapshots()],
        )

    # ---------------------------------------------------------------
    # 2) 加载后 GET /chain-state 与保存前一致（HTTP 级验证）
    # ---------------------------------------------------------------
    def test_chain_state_identical_after_load(self):
        archive = self.path("chain.json")
        state_a = srv.build_server_state(fresh=True, persist_path=archive)  # 预沉积 + 立即落盘
        srv.api_propose(state_a, {"proposal_text": "绑定聚合", "miner_pubkey_b64": self.first_miner(state_a)})
        httpd_a = srv.create_server(state_a)
        thread_a = threading.Thread(target=httpd_a.serve_forever, daemon=True)
        thread_a.start()
        try:
            before = http_json("/chain-state")
        finally:
            httpd_a.shutdown()
            httpd_a.server_close()
            thread_a.join(timeout=5)

        state_b = srv.build_server_state(fresh=False, persist_path=archive)
        httpd_b = srv.create_server(state_b)
        thread_b = threading.Thread(target=httpd_b.serve_forever, daemon=True)
        thread_b.start()
        try:
            after = http_json("/chain-state")
        finally:
            httpd_b.shutdown()
            httpd_b.server_close()
            thread_b.join(timeout=5)
        self.assertEqual(after, before)

    # ---------------------------------------------------------------
    # 3) 损坏 / 版本不匹配 / 哈希篡改：拒绝加载
    # ---------------------------------------------------------------
    def test_corrupt_file_refused(self):
        archive = self.path("corrupt.json")
        with open(archive, "w", encoding="utf-8") as handle:
            handle.write("{ not valid json ")
        with self.assertRaises(persistence.PersistenceError) as cm:
            persistence.load_state(archive)
        self.assertIn("损坏", str(cm.exception))

    def test_format_version_mismatch_refused(self):
        archive = self.path("version.json")
        with open(archive, "w", encoding="utf-8") as handle:
            json.dump({"format_version": "chain-v99"}, handle)
        with self.assertRaises(persistence.PersistenceError) as cm:
            persistence.load_state(archive)
        self.assertIn("版本不匹配", str(cm.exception))

    def test_tampered_block_hash_refused(self):
        archive = self.path("tampered.json")
        state = self.make_mutated_state()
        persistence.save_state(archive, state.store, state.registry.miners, state.rejection_reasons)
        with open(archive, encoding="utf-8") as handle:
            data = json.load(handle)
        data["blocks"][5]["block_hash"] = "0" * 64
        with open(archive, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        with self.assertRaises(persistence.PersistenceError) as cm:
            persistence.load_state(archive)
        self.assertIn("哈希校验失败", str(cm.exception))

    def test_missing_file_creates_fresh_and_saves(self):
        archive = self.path("missing.json")
        state = srv.build_server_state(fresh=False, persist_path=archive)
        self.assertEqual(state.store.height, 102)
        self.assertTrue(os.path.exists(archive))

    # ---------------------------------------------------------------
    # 4) --fresh：忽略存档回到预沉积 102 块初始态
    # ---------------------------------------------------------------
    def test_fresh_ignores_archive_and_resets_to_102(self):
        archive = self.path("chain.json")
        state = srv.build_server_state(fresh=True, persist_path=archive)
        self.assertEqual(state.store.height, 102)
        srv.api_propose(state, {"proposal_text": "函数增量扩展", "miner_pubkey_b64": self.first_miner(state)})
        self.assertEqual(state.store.height, 103)
        # 非 fresh 应加载 103
        loaded = srv.build_server_state(fresh=False, persist_path=archive)
        self.assertEqual(loaded.store.height, 103)
        # fresh 应回到 102 且覆盖存档
        reset = srv.build_server_state(fresh=True, persist_path=archive)
        self.assertEqual(reset.store.height, 102)
        again = srv.build_server_state(fresh=False, persist_path=archive)
        self.assertEqual(again.store.height, 102)

    # ---------------------------------------------------------------
    # 5) 导出与存档同格式
    # ---------------------------------------------------------------
    def test_export_chain_equals_archive(self):
        archive = self.path("chain.json")
        exported = self.path("export.json")
        state = self.make_mutated_state()
        persistence.save_state(archive, state.store, state.registry.miners, state.rejection_reasons)
        persistence.export_chain(exported, state.store, state.registry.miners, state.rejection_reasons)
        with open(archive, encoding="utf-8") as handle:
            archived = json.load(handle)
        with open(exported, encoding="utf-8") as handle:
            exported_data = json.load(handle)
        self.assertEqual(exported_data, archived)
        # CLI 导出路径（直接调用模块函数）
        persistence.write_export(exported, persistence.load_state(archive))
        with open(exported, encoding="utf-8") as handle:
            exported_data = json.load(handle)
        self.assertEqual(exported_data["format_version"], persistence.FORMAT_VERSION)


if __name__ == "__main__":
    unittest.main()
