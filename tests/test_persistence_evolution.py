"""持久化 × 语言演化耦合测试（v0.3 阶段 C 收尾 · 监督验收 F）。

语言快照与激活集不单独序列化进存档，全靠主链 activation 字段重放重建；
这是整个系统最容易漂移的接缝：save → load + rebuild 后，语言注册表、
逐高度语言快照与「激活后能力可用 / 未激活高度不可用」必须逐项一致。
"""

import os
import tempfile
import unittest

import persistence
import server as srv
from novscript import run_sandbox
from novscript.language import LanguageSnapshot


class PersistenceEvolutionTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name: str) -> str:
        return os.path.join(self.tmp.name, name)

    def first_miner(self, state) -> str:
        return srv.b64e(list(state.registry.miners)[0])

    def build_evolved_chain(self, archive: str):
        """预沉积 102 块后，先后激活 `-`（height=103）与 `list/head`（height=104）。"""
        state = srv.build_server_state(fresh=True, persist_path=archive)
        ok1 = srv.api_propose(state, {"proposal_text": "减法扩展",
                                      "miner_pubkey_b64": self.first_miner(state)})
        self.assertTrue(ok1["success"], ok1)
        ok2 = srv.api_propose(state, {"proposal_text": "列表扩展",
                                      "miner_pubkey_b64": self.first_miner(state)})
        self.assertTrue(ok2["success"], ok2)
        return state

    def test_save_load_rebuild_keeps_language_evolution(self):
        archive = self.path("chain.json")
        state = self.build_evolved_chain(archive)
        # 原始链的语言状态符合预期（- 与 list/head 已激活）。
        self.assertEqual(state.store.language_snapshot_at(103).active_features,
                         frozenset({"-"}))
        self.assertEqual(state.store.language_snapshot_at(104).active_features,
                         frozenset({"-", "head", "list"}))

        # save（已由 build_server_state 与 api_propose 自动落盘）→ load → rebuild。
        data = persistence.load_state(archive)
        store2 = persistence.rebuild_store(data["blocks"], data["sleeping_branches"])
        registry2 = srv.MinerRegistry(miners=persistence.miners_from_list(data["miners"]))

        # ① 高度与全部区块哈希一致。
        self.assertEqual(store2.height, state.store.height)
        self.assertEqual(
            [b.block_hash for b in store2.main_chain()],
            [b.block_hash for b in state.store.main_chain()],
        )

        # ② 各高度语言快照一致（含未激活高度与两次激活高度）。
        snap_before = {
            b.height: state.store.language_snapshot_at(b.height).active_features
            for b in state.store.main_chain()
        }
        snap_after = {
            b.height: store2.language_snapshot_at(b.height).active_features
            for b in store2.main_chain()
        }
        self.assertEqual(snap_after, snap_before)
        self.assertEqual(len(snap_after), store2.height + 1)  # 每个主链高度都有快照
        # 边界抽查：未激活高度为空集，激活高度逐层累积。
        self.assertEqual(store2.language_snapshot_at(0).active_features, frozenset())
        self.assertEqual(store2.language_snapshot_at(102).active_features, frozenset())
        self.assertEqual(store2.language_snapshot_at(103).active_features, frozenset({"-"}))
        self.assertEqual(store2.language_snapshot_at(104).active_features,
                         frozenset({"-", "head", "list"}))

        # ③ 激活后的原语在重建后仍可用：链级注册表直接执行 (- 10 3) -> 7。
        result = run_sandbox("(- 10 3)", registry=store2.language_registry)
        self.assertTrue(result.ok, result)
        self.assertEqual(result.value, 7)

        # ④ 未激活高度（height=1 的语言快照）同一 demo 仍报 NameError。
        early_snapshot = store2.language_snapshot_at(1)
        early_registry = LanguageSnapshot.build_registry(early_snapshot)
        early_result = run_sandbox("(- 10 3)", registry=early_registry)
        self.assertFalse(early_result.ok)
        self.assertEqual(early_result.error_type, "NameError")


if __name__ == "__main__":
    unittest.main()
