"""StratumGenesis 语言真实演化（特性注册表 + 求值器派发 + 版本化重放）测试。"""

import unittest

from block_model import TestCase
from block_validator import validate_block
from chain_store import ChainStore
from crypto_key import generate_miner_keypair
from demo_evolution import make_extension_block
from novscript import run_sandbox
from novscript.language import LanguageSnapshot
from novscript.registry import FeatureRegistry, spec_of


class EvolutionRegistryTests(unittest.TestCase):
    """特性注册表与求值器派发。"""

    def test_registered_primitive_is_callable(self):
        registry = FeatureRegistry.from_specs([spec_of("-")])
        result = run_sandbox("(- 10 3)", registry=registry)
        self.assertTrue(result.ok, result)
        self.assertEqual(result.value, 7)

    def test_unregistered_primitive_raises_name_error(self):
        registry = FeatureRegistry.from_specs([])  # 空注册表：仅创世内核
        result = run_sandbox("(- 10 3)", registry=registry)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "NameError")

    def test_registry_snapshot_and_duplicate_guard(self):
        registry = FeatureRegistry.from_specs([spec_of("-")])
        self.assertEqual(registry.snapshot(), frozenset({"-"}))
        with self.assertRaises(NameError):
            registry.register(spec_of("-"))  # 同名重复注册被拒

    def test_kernel_primitive_cannot_be_registered(self):
        # 内核原语 + 不在预置池（不能通过注册表激活），激活时会被拒绝。
        self.assertIsNone(spec_of("+"))


class EvolutionBlockTests(unittest.TestCase):
    """区块级：8 步流水线中的特性激活与正负测试。"""

    def setUp(self) -> None:
        self.store = ChainStore()
        self.private_key, self.public_key = generate_miner_keypair()

    def submit(self, *, activation, demo, tests, description="扩展提案"):
        block = make_extension_block(
            self.store, self.private_key, self.public_key,
            feature_name=activation[0] if activation else "普通扩展",
            description=description,
            activation=activation,
            demo=demo,
            tests=tests,
        )
        return validate_block(block, self.store), block

    def test_activation_block_really_changes_language(self):
        # 正测试：(- 10 3) -> 7；负测试：旧语言下失败。
        result, block = self.submit(
            activation=("-",), demo="(- 10 3)", tests=(TestCase("(- 10 3)", 7),),
        )
        self.assertTrue(result.accepted, result)
        self.assertEqual(result.checked_stages[-2], "language_evolution")
        self.store.append_main(block)
        # 语言真的升级了：链级注册表包含 -，解释器可直接调用。
        self.assertIn("-", self.store.language_registry.snapshot())
        self.assertTrue(run_sandbox("(- 10 3)", registry=self.store.language_registry).ok)

    def test_unknown_activation_rejected(self):
        result, _ = self.submit(
            activation=("not-a-primitive",),
            demo="(not-a-primitive 1 2)",
            tests=(TestCase("(not-a-primitive 1 2)", 3),),
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.stage, "activation")
        self.assertEqual(result.error_code, "UNKNOWN_FEATURE")

    def test_duplicate_activation_rejected(self):
        result, block = self.submit(
            activation=("-",), demo="(- 10 3)", tests=(TestCase("(- 10 3)", 7),),
        )
        self.assertTrue(result.accepted, result)
        self.store.append_main(block)
        # 链上已有 -，再次激活被第 5 步拒绝。
        result, _ = self.submit(
            activation=("-",), demo="(- 5 2)", tests=(TestCase("(- 5 2)", 3),),
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.stage, "activation")
        self.assertEqual(result.error_code, "DUPLICATE_FEATURE")

    def test_demo_not_referencing_feature_rejected(self):
        # demo 词法不含激活原语名：附加检查拒绝（防止用无关代码糊弄负测试）。
        result, _ = self.submit(
            activation=("-",), demo="(+ 1 2)", tests=(TestCase("(+ 1 2)", 3),),
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.stage, "language_evolution")
        self.assertEqual(result.error_code, "FEATURE_NOT_USED")

    def test_demo_that_passes_without_feature_rejected(self):
        # 负测试失败场景：demo 在新旧语言下都能跑 -> 提案不改变语言 -> 拒绝。
        result, _ = self.submit(
            activation=("-",), demo="(+ 1 2)", tests=(TestCase("(+ 1 2)", 3),),
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.error_code, "FEATURE_NOT_USED")

    def test_versioned_replay_consistency(self):
        # 上链后的语言快照能重建注册表，重放历史块 demo 结果与当年一致。
        result, block = self.submit(
            activation=("-",), demo="(- 10 3)", tests=(TestCase("(- 10 3)", 7),),
        )
        self.assertTrue(result.accepted, result)
        self.store.append_main(block)
        snapshot = self.store.language_snapshot_at(block.height)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.active_features, frozenset({"-"}))
        replay_registry = LanguageSnapshot.build_registry(snapshot)
        replay = run_sandbox(block.proposal.demo_code, registry=replay_registry)
        self.assertTrue(replay.ok, replay)
        self.assertEqual(replay.value, 7)

    def test_sleeping_branch_does_not_touch_chain_registry(self):
        result, _ = self.submit(
            activation=("-",), demo="(- 10 3)", tests=(TestCase("(- 10 3)", 7),),
        )
        self.assertTrue(result.accepted, result)
        # 构造一个合法但落选的候选（直接放休眠分支，不走主链）。
        block = make_extension_block(
            self.store, self.private_key, self.public_key,
            feature_name="列表原语",
            description="合法提案但进入休眠分支",
            activation=("list", "head"),
            demo="(head (list 1 2 3))",
            tests=(TestCase("(head (list 1 2 3))", 1),),
        )
        self.assertTrue(validate_block(block, self.store).accepted)
        self.store.add_sleeping_branch(block)
        # 链级注册表未因休眠分支变化；分支自身激活集单独记录。
        self.assertEqual(self.store.language_registry.snapshot(), frozenset())
        branch_id = block.parent_hash or "orphan"
        self.assertEqual(self.store.branch_active_features(branch_id), frozenset({"list", "head"}))

    def test_activation_included_in_block_hash_and_signature(self):
        # activation 纳入 canonical 序列化：改激活集会改变哈希与签名。
        block_a = make_extension_block(
            self.store, self.private_key, self.public_key,
            feature_name="减法原语", description="激活 -",
            activation=("-",), demo="(- 10 3)", tests=(TestCase("(- 10 3)", 7),),
        )
        block_b = make_extension_block(
            self.store, self.private_key, self.public_key,
            feature_name="乘法原语", description="激活 *",
            activation=("*",), demo="(* 3 4)", tests=(TestCase("(* 3 4)", 12),),
        )
        self.assertNotEqual(block_a.block_hash, block_b.block_hash)
        self.assertNotEqual(block_a.canonical_bytes(), block_b.canonical_bytes())


if __name__ == "__main__":
    unittest.main()
