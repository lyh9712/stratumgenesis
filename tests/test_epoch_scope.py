"""纪元作用域语言（失忆）+ 引种提案（Inoculation Proposal）测试（v0.3 阶段 D）。

核心语义：语言作用域从「链级只增不减」改为「纪元内有效」——
跨纪元默认失忆，需在本纪元通过 activation 引种；历史层（provenance）
只增不减，用于判定「引种 vs 新特性」与对外累计口径。
"""

import os
import tempfile
import unittest

import persistence
import server as srv
from block_model import TestCase
from block_validator import validate_block
from chain_store import ChainStore
from crypto_key import generate_miner_keypair
from demo_evolution import make_extension_block
from novscript import run_sandbox
from novscript.language import LanguageSnapshot


class EpochScopeTests(unittest.TestCase):

    def setUp(self) -> None:
        self.store = ChainStore()
        self.private_key, self.public_key = generate_miner_keypair()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name: str) -> str:
        return os.path.join(self.tmp.name, name)

    def ext(self, *, activation, demo, tests, height=None, description="扩展提案"):
        """构造激活指定原语的候选区块（height 默认 = 当前链高 + 1）。"""
        return make_extension_block(
            self.store, self.private_key, self.public_key,
            feature_name=activation[0] if activation else "普通扩展",
            description=description,
            activation=activation,
            demo=demo,
            tests=tests,
        )

    def plain(self, demo="(+ 1 2)", tests=None, description="普通内核块"):
        """构造无 activation 的普通内核块。"""
        return self.ext(activation=(), demo=demo,
                        tests=tests or (TestCase("(+ 1 2)", 3),),
                        description=description)

    def append(self, block) -> None:
        result = validate_block(block, self.store)
        self.assertTrue(result.accepted, result)
        self.store.append_main(block)

    def fill_to(self, target_height: int) -> None:
        """用无 activation 的内核块填充主链直到指定高度（含）。"""
        while self.store.height < target_height:
            self.append(self.plain())

    def submit_extension(self, *, activation, demo, tests):
        """提交扩展提案（不 append，返回校验结果）。"""
        return validate_block(self.ext(activation=activation, demo=demo, tests=tests), self.store)

    # ---------------------------------------------------------------
    # 1) 跨纪元失忆
    # ---------------------------------------------------------------
    def test_cross_epoch_amnesia(self):
        # 纪元 0 内激活 -；纪元 1 首块（height 100）不带 activation、demo 用 - -> 失忆拒绝。
        self.append(self.ext(activation=("-",), demo="(- 10 3)",
                             tests=(TestCase("(- 10 3)", 7),)))
        self.fill_to(99)
        result = validate_block(
            self.ext(activation=(), demo="(- 10 3)", tests=(TestCase("(- 10 3)", 7),),
                     description="纪元1首块使用旧特性"),
            self.store,
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.stage, "activation")
        self.assertEqual(result.error_code, "UNIMPORTED_FEATURE")
        # 纪元 1 首块用内核块上链后，纪元作用域快照已重置为空集。
        self.append(self.plain())
        self.assertEqual(self.store.language_snapshot_at(100).active_features, frozenset())
        self.assertEqual(self.store.epoch_active_features(), frozenset())

    # ---------------------------------------------------------------
    # 2) 引种成功：本纪元 activation 重新激活历史原语
    # ---------------------------------------------------------------
    def test_inoculation_succeeds(self):
        self.append(self.ext(activation=("-",), demo="(- 10 3)",
                             tests=(TestCase("(- 10 3)", 7),)))
        self.fill_to(99)
        # height=100 引种 -（activation 含 -，历史层已有 -> 引种而非新特性）。
        inoc = self.ext(activation=("-",), demo="(- 10 3)",
                        tests=(TestCase("(- 10 3)", 7),))
        self.assertTrue(validate_block(inoc, self.store).accepted)
        self.store.append_main(inoc)
        self.assertEqual(self.store.language_snapshot_at(100).active_features, frozenset({"-"}))
        # 同纪元普通块可直接使用已引种的 -。
        use = self.plain(demo="(- 5 2)", tests=(TestCase("(- 5 2)", 3),))
        self.assertTrue(validate_block(use, self.store).accepted)
        self.store.append_main(use)
        self.assertEqual(self.store.language_snapshot_at(101).active_features, frozenset({"-"}))

    # ---------------------------------------------------------------
    # 3) 同纪元重复激活仍拒绝
    # ---------------------------------------------------------------
    def test_duplicate_within_epoch_rejected(self):
        self.append(self.ext(activation=("-",), demo="(- 10 3)",
                             tests=(TestCase("(- 10 3)", 7),)))
        result = self.submit_extension(activation=("-",), demo="(- 5 2)",
                                       tests=(TestCase("(- 5 2)", 3),))
        self.assertFalse(result.accepted)
        self.assertEqual(result.stage, "activation")
        self.assertEqual(result.error_code, "DUPLICATE_FEATURE")

    # ---------------------------------------------------------------
    # 4) 跨纪元再次引种合法（纪元内唯一 + 历史只增不减）
    # ---------------------------------------------------------------
    def test_cross_epoch_reinoculation_allowed(self):
        self.append(self.ext(activation=("-",), demo="(- 10 3)",
                             tests=(TestCase("(- 10 3)", 7),)))
        self.fill_to(99)
        self.append(self.ext(activation=("-",), demo="(- 10 3)",
                             tests=(TestCase("(- 10 3)", 7),)))  # 纪元1首块引种
        self.fill_to(199)
        reinoc = self.ext(activation=("-",), demo="(- 10 3)",
                          tests=(TestCase("(- 10 3)", 7),))  # 纪元2首块再引种
        self.assertTrue(validate_block(reinoc, self.store).accepted, validate_block(reinoc, self.store))
        self.store.append_main(reinoc)
        self.assertEqual(self.store.ever_active_features(), frozenset({"-"}))  # 历史层只增不减一次
        self.assertEqual(self.store.language_snapshot_at(200).active_features, frozenset({"-"}))

    # ---------------------------------------------------------------
    # 5) 重放一致性：save -> load + rebuild 后纪元作用域快照逐项一致
    # ---------------------------------------------------------------
    def test_replay_consistency_after_save_load(self):
        archive = self.path("chain.json")
        self.append(self.ext(activation=("-",), demo="(- 10 3)",
                             tests=(TestCase("(- 10 3)", 7),)))
        self.fill_to(99)
        self.append(self.ext(activation=("-",), demo="(- 10 3)",
                             tests=(TestCase("(- 10 3)", 7),)))  # height 100 引种
        self.append(self.plain(demo="(- 5 2)", tests=(TestCase("(- 5 2)", 3),)))  # height 101 用 -
        miners = {self.public_key: ("测试矿工", self.private_key)}
        persistence.save_state(archive, self.store, miners, {})

        data = persistence.load_state(archive)
        store2 = persistence.rebuild_store(data["blocks"], data["sleeping_branches"])
        # ① 高度与全部区块哈希一致
        self.assertEqual(store2.height, self.store.height)
        self.assertEqual([b.block_hash for b in store2.main_chain()],
                         [b.block_hash for b in self.store.main_chain()])
        # ② 各高度纪元作用域快照一致
        snap_before = {b.height: self.store.language_snapshot_at(b.height).active_features
                       for b in self.store.main_chain()}
        snap_after = {b.height: store2.language_snapshot_at(b.height).active_features
                      for b in store2.main_chain()}
        self.assertEqual(snap_after, snap_before)
        # ③ 激活后可用性一致（重建后纪元层跑 (- 10 3) = 7）
        result = run_sandbox("(- 10 3)", registry=store2.epoch_registry)
        self.assertTrue(result.ok, result)
        self.assertEqual(result.value, 7)
        # ④ 未引种高度（创世快照）同一 demo 仍 NameError
        genesis_registry = LanguageSnapshot.build_registry(store2.language_snapshot_at(0))
        early = run_sandbox("(- 10 3)", registry=genesis_registry)
        self.assertFalse(early.ok)
        self.assertEqual(early.error_type, "NameError")

    # ---------------------------------------------------------------
    # 6) 引种 vs 新特性分类正确
    # ---------------------------------------------------------------
    def test_feature_classification(self):
        self.append(self.ext(activation=("-",), demo="(- 10 3)",
                             tests=(TestCase("(- 10 3)", 7),)))  # 纪元0：新特性 -
        self.fill_to(99)
        self.append(self.ext(activation=("-",), demo="(- 10 3)",
                             tests=(TestCase("(- 10 3)", 7),)))  # 纪元1首块：引种 -
        self.append(self.ext(activation=("list", "head"), demo="(head (list 1 2 3))",
                             tests=(TestCase("(head (list 1 2 3))", 1),)))  # 纪元1：新特性 list/head
        self.fill_to(199)
        self.append(self.ext(activation=("-",), demo="(- 10 3)",
                             tests=(TestCase("(- 10 3)", 7),)))  # 纪元2首块：再引种 -

        snap0 = self.store.epoch_manager.get_epoch_snapshot(0)
        self.assertEqual(snap0.epoch_base_features, frozenset())          # 创世块无引种
        self.assertEqual(snap0.epoch_new_features, frozenset({"-"}))
        self.assertEqual(snap0.active_features, frozenset({"-"}))
        self.assertEqual(snap0.cumulative_active_features, frozenset({"-"}))

        snap1 = self.store.epoch_manager.get_epoch_snapshot(1)
        self.assertEqual(snap1.epoch_base_features, frozenset({"-"}))     # 首块引种 -
        self.assertEqual(snap1.epoch_new_features, frozenset({"list", "head"}))
        self.assertEqual(snap1.active_features, frozenset({"-", "list", "head"}))
        self.assertEqual(snap1.cumulative_active_features, frozenset({"-", "list", "head"}))

        snap2 = self.store.epoch_manager.get_epoch_snapshot(2)
        self.assertEqual(snap2.epoch_base_features, frozenset({"-"}))     # 再引种 -
        self.assertEqual(snap2.epoch_new_features, frozenset())
        self.assertEqual(snap2.active_features, frozenset({"-"}))
        self.assertEqual(snap2.cumulative_active_features, frozenset({"-", "list", "head"}))

    # ---------------------------------------------------------------
    # 7) 语义化报错：UNIMPORTED_FEATURE 含旧纪元号与特性名
    # ---------------------------------------------------------------
    def test_semantic_error_message(self):
        self.append(self.ext(activation=("-",), demo="(- 10 3)",
                             tests=(TestCase("(- 10 3)", 7),)))
        self.fill_to(99)
        result = validate_block(
            self.ext(activation=(), demo="(- 10 3)", tests=(TestCase("(- 10 3)", 7),)),
            self.store,
        )
        self.assertEqual(result.error_code, "UNIMPORTED_FEATURE")
        self.assertIn("'-'", result.message)
        self.assertIn("epoch 0", result.message)
        self.assertIn("epoch 1", result.message)
        self.assertIn("inoculate", result.message)

    # ---------------------------------------------------------------
    # 8) API 契约：追加字段齐全、旧字段新语义、累计字段保旧语义
    # ---------------------------------------------------------------
    def test_api_contract_fields(self):
        archive = self.path("api_chain.json")
        state = srv.build_server_state(fresh=True, persist_path=archive)  # 预沉积 102 块
        miner = srv.b64e(list(state.registry.miners)[0])
        prop = srv.api_propose(state, {"proposal_text": "减法扩展", "miner_pubkey_b64": miner})
        self.assertTrue(prop["success"], prop)
        cs = srv.api_chain_state(state)
        # 顶层：current_active_features 为纪元作用域（新语义）；累计字段为旧语义。
        self.assertEqual(cs["current_active_features"], ["-"])
        self.assertEqual(cs["cumulative_active_features"], ["-"])
        # 纪元 1 首块（height 100，预沉积无 activation）-> 当前纪元基线为空。
        self.assertEqual(cs["current_epoch_base_features"], [])
        # epochs[1]：纪元内有效 + 四元组齐全。
        epoch1 = next(e for e in cs["epochs"] if e["epoch_number"] == 1)
        self.assertEqual(epoch1["active_features"], ["-"])
        self.assertEqual(epoch1["epoch_base_features"], [])
        self.assertEqual(epoch1["epoch_new_features"], ["-"])
        self.assertEqual(epoch1["cumulative_active_features"], ["-"])
        # epochs[0]：预沉积无激活，全空。
        epoch0 = next(e for e in cs["epochs"] if e["epoch_number"] == 0)
        self.assertEqual(epoch0["active_features"], [])
        self.assertEqual(epoch0["epoch_base_features"], [])
        self.assertEqual(epoch0["epoch_new_features"], [])
        self.assertEqual(epoch0["cumulative_active_features"], [])
        # blocks[].language_features = 该高度当时可用语言集（纪元作用域）。
        block103 = next(b for b in cs["blocks"] if b["height"] == 103)
        self.assertEqual(block103["language_features"], ["-"])

    # ---------------------------------------------------------------
    # 9) 边界：99 / 100 / 101 三个高度的快照语义
    # ---------------------------------------------------------------
    def test_boundary_heights_99_100_101(self):
        self.append(self.ext(activation=("-",), demo="(- 10 3)",
                             tests=(TestCase("(- 10 3)", 7),)))
        self.fill_to(99)
        # 99：纪元 0 内（含 -）
        self.assertEqual(self.store.language_snapshot_at(99).active_features, frozenset({"-"}))
        # 100：纪元 1 首块引种 -（重置后累积）
        self.append(self.ext(activation=("-",), demo="(- 10 3)",
                             tests=(TestCase("(- 10 3)", 7),)))
        self.assertEqual(self.store.language_snapshot_at(100).active_features, frozenset({"-"}))
        # 101：纪元 1 内继续可用
        self.append(self.plain(demo="(- 5 2)", tests=(TestCase("(- 5 2)", 3),)))
        self.assertEqual(self.store.language_snapshot_at(101).active_features, frozenset({"-"}))

    # ---------------------------------------------------------------
    # 10) 回归：预沉积链普通区块（无 activation、仅内核语法）全部通过
    # ---------------------------------------------------------------
    def test_seed_chain_regression(self):
        archive = self.path("seed_chain.json")
        state = srv.build_server_state(fresh=True, persist_path=archive)  # 102 块不误拒
        self.assertEqual(state.store.height, 102)
        cs = srv.api_chain_state(state)
        self.assertEqual(cs["epochs"][0]["active_features"], [])
        self.assertEqual(cs["epochs"][1]["active_features"], [])
        # 预沉积链上普通内核块在纪元 1 仍可直接执行。
        ev = srv.api_eval_novscript(state, {"code": "(+ 1 2)"})
        self.assertTrue(ev["ok"], ev)


if __name__ == "__main__":
    unittest.main()
