"""休眠分支升级 / 主链重组（Branch Promotion / Reorg）测试（v0.3 阶段 E）。

对应 BRANCH_PROMOTION_DESIGN.md §8 测试计划 T-01…T-16：
- T-01 纯接续（平票双分支） / T-02 落选者翻身 / T-03 多级分支深重组
- T-04 收缩重组 / T-05 延伸重组 / T-06 资格拒绝（头不存在/孤儿链）
- T-07 结构断裂 / T-08 后缀含已归档纪元块 / T-09 分支越出当前纪元
- T-10 UTXO 失效 / T-11 语言失效 / T-12 语言重建正确性（ever_active 收缩）
- T-13 纪元摘要不变 + pending 重算 / T-14 对合性 / T-15 持久化 round-trip
- T-16 原子性总检 + API 契约

每项失败用例都带 I-11 原子性断言（状态摘要前后相等）。
"""

import os
import tempfile
import unittest
from dataclasses import replace

import persistence
import server as srv
from block_model import Block, PoiRecord, Proposal, TestCase
from block_validator import MIN_POI_TOKENS, validate_block
from chain_store import ChainStore
from crypto_key import generate_miner_keypair, sign_block_payload
from mock_tokenizer import MOCK_TOKENIZER_ID, count_poi_tokens
from utxo_model import UTXO, make_signed_transaction


def _state_digest(store: ChainStore) -> tuple:
    """全量可观测状态摘要（主链/休眠/账本/语言快照/纪元快照），用于 I-11 原子性断言。"""
    main = tuple(block.block_hash for block in store.main_chain())
    sleeping = tuple(
        (branch_id, tuple(block.block_hash for block in blocks))
        for branch_id, blocks in store.sleeping_branches().items()
    )
    pubkeys = sorted({block.miner_pubkey for block in store.main_chain() if block.height > 0})
    balances = tuple((key.hex(), store.utxo_ledger.get_balance(key)) for key in pubkeys)
    snapshots = tuple(
        (height, tuple(sorted(store.language_snapshot_at(height).active_features)))
        for height in range(store.height + 1)
    )
    epochs = tuple(
        (item.epoch_number, item.start_height, item.end_height, item.archived,
         tuple(h.hex() for h in item.block_hashes))
        for item in store.epoch_manager.snapshots()
    )
    return main, sleeping, balances, snapshots, epochs


class BranchPromotionTests(unittest.TestCase):

    def setUp(self) -> None:
        self.store = ChainStore()
        self.private_key, self.public_key = generate_miner_keypair()
        self.private_key_b, self.public_key_b = generate_miner_keypair()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name: str) -> str:
        return os.path.join(self.tmp.name, name)

    def make_candidate(
        self,
        *,
        height: int,
        parent_hash: str | None,
        activation: tuple[str, ...] = (),
        demo: str = "(+ 1 2)",
        tests: tuple[TestCase, ...] | None = None,
        private_key: bytes | None = None,
        public_key: bytes | None = None,
        transactions: tuple = (),
        proposer: str = "矿工·测试者",
        feature_name: str = "扩展提案",
        description: str = "扩展提案",
    ) -> Block:
        """构造指定高度/父区块的候选块（含合法 PoI 与真实 ECDSA 签名）。"""
        private_key = private_key or self.private_key
        public_key = public_key or self.public_key
        tests = tests if tests is not None else (TestCase("(+ 1 2)", 3),)
        prompt = f"design a NovScript extension named {feature_name}: {description}"
        output = demo + " " + " ".join(t.program for t in tests) + " " + "reasoning token " * (MIN_POI_TOKENS + 3)
        counts = count_poi_tokens(prompt, output)
        proposal = Proposal(feature_name, description, demo, tests)
        poi = PoiRecord(
            "manual-mock", prompt, output, MOCK_TOKENIZER_ID,
            counts.standard_input_tokens, counts.standard_output_tokens, counts.standard_total_tokens,
        )
        unsigned = Block(height, parent_hash, proposer, proposal, poi,
                         miner_pubkey=public_key, activation=activation, transactions=transactions)
        return replace(unsigned, signature_bytes=sign_block_payload(private_key, unsigned.canonical_bytes()))

    def append(self, block: Block) -> None:
        result = validate_block(block, self.store)
        self.assertTrue(result.accepted, result)
        self.store.append_main(block)

    def append_plain(self) -> Block:
        block = self.make_candidate(height=self.store.height + 1, parent_hash=self.store.tip.block_hash)
        self.append(block)
        return block

    def fill_to(self, target_height: int) -> None:
        """用无 activation 的内核块填充主链直到指定高度（含）。"""
        while self.store.height < target_height:
            self.append_plain()

    def submit_and_sleep(self, block: Block) -> None:
        """构造休眠块：校验通过才入休眠（语义资格由 promote 重放再判）。"""
        result = validate_block(block, self.store)
        self.assertTrue(result.accepted, result)
        self.store.add_sleeping_branch(block)

    def assert_unchanged(self, before) -> None:
        """I-11：promote 失败后全量可观测状态与调用前逐项相同。"""
        self.assertEqual(_state_digest(self.store), before)

    # ---------------------------------------------------------------
    # T-01 纯接续（监督者验收场景）：平票双分支，主链停滞于 H，promote 其中一支
    # ---------------------------------------------------------------
    def test_t01_pure_continuation(self):
        self.append_plain()
        self.append_plain()  # H=2
        b_a = self.make_candidate(height=3, parent_hash=self.store.tip.block_hash,
                                  private_key=self.private_key, public_key=self.public_key,
                                  proposer="矿工A")
        b_b = self.make_candidate(height=3, parent_hash=self.store.tip.block_hash,
                                  private_key=self.private_key_b, public_key=self.public_key_b,
                                  proposer="矿工B")
        self.submit_and_sleep(b_a)
        self.submit_and_sleep(b_b)

        result = self.store.promote_branch(b_a.block_hash)
        self.assertEqual(result.status, "promoted", result)
        self.assertEqual(result.new_tip_height, 3)
        self.assertEqual([b.block_hash for b in self.store.main_chain()[-1:]],
                         [b_a.block_hash])
        # 另一支保留休眠。
        sleeping = {b.block_hash for blocks in self.store.sleeping_branches().values() for b in blocks}
        self.assertIn(b_b.block_hash, sleeping)
        self.assertNotIn(b_a.block_hash, sleeping)
        # 账本含被提升块的奖励 UTXO（I-7：账本 ≡ 重放）。
        # 主链 2 个普通块（A）+ 被提升块（A）共 3 份奖励。
        self.assertEqual(self.store.utxo_ledger.get_balance(self.public_key), 300)

    # ---------------------------------------------------------------
    # T-02 落选者翻身（经典 reorg）：胜者上链、败者休眠，promote 败者
    # ---------------------------------------------------------------
    def test_t02_loser_promoted(self):
        self.append_plain()
        self.append_plain()  # H=2
        b_win = self.make_candidate(height=3, parent_hash=self.store.tip.block_hash,
                                    private_key=self.private_key, public_key=self.public_key,
                                    proposer="矿工A")
        b_lose = self.make_candidate(height=3, parent_hash=self.store.tip.block_hash,
                                     private_key=self.private_key_b, public_key=self.public_key_b,
                                     proposer="矿工B")
        self.append(b_win)
        self.store.add_sleeping_branch(b_lose)
        self.assertEqual(self.store.utxo_ledger.get_balance(self.public_key), 300)  # 2 普通块 + b_win

        result = self.store.promote_branch(b_lose.block_hash)
        self.assertEqual(result.status, "promoted", result)
        # M' = M[0..H] + [败者]；胜者降级入休眠（I-3）。
        self.assertEqual(self.store.main_chain()[-1].block_hash, b_lose.block_hash)
        sleeping = {b.block_hash for blocks in self.store.sleeping_branches().values() for b in blocks}
        self.assertIn(b_win.block_hash, sleeping)
        self.assertNotIn(b_lose.block_hash, sleeping)
        # 两矿工余额互换（I-7）：A 回到 2 份奖励、B 获得被提升块的奖励。
        self.assertEqual(self.store.utxo_ledger.get_balance(self.public_key), 200)
        self.assertEqual(self.store.utxo_ledger.get_balance(self.public_key_b), 100)
        # 胜者块全字段不变（I-2/I-3：对象原样搬运）。
        self.assertEqual(self.store.get_block(b_win.block_hash), b_win)

    # ---------------------------------------------------------------
    # T-03 多级分支深重组：分支链深度 >= 2，promote 头
    # ---------------------------------------------------------------
    def test_t03_multi_level_deep_reorg(self):
        self.append_plain()
        self.append_plain()  # H=2
        b1 = self.make_candidate(height=3, parent_hash=self.store.tip.block_hash)
        b2 = self.make_candidate(height=4, parent_hash=b1.block_hash)
        b3 = self.make_candidate(height=5, parent_hash=b2.block_hash)
        for block in (b1, b2, b3):
            self.submit_and_sleep(block)

        result = self.store.promote_branch(b3.block_hash)
        self.assertEqual(result.status, "promoted", result)
        self.assertEqual([b.block_hash for b in self.store.main_chain()[-3:]],
                         [b1.block_hash, b2.block_hash, b3.block_hash])
        self.assertEqual(self.store.height, 5)
        # I-1 主链连续父链。
        for index in range(1, self.store.height + 1):
            self.assertEqual(self.store.main_chain()[index].height, index)
            self.assertEqual(self.store.main_chain()[index].parent_hash,
                             self.store.main_chain()[index - 1].block_hash)
        # I-8 语言快照全覆盖。
        for height in range(self.store.height + 1):
            self.assertIsNotNone(self.store.language_snapshot_at(height))

    # ---------------------------------------------------------------
    # T-04 收缩重组：新链比原主链短（f + k < H）
    # ---------------------------------------------------------------
    def test_t04_shrinking_reorg(self):
        for _ in range(5):
            self.append_plain()  # H=5
        b = self.make_candidate(height=3, parent_hash=self.store.main_chain()[2].block_hash,
                                proposer="矿工·分支")
        self.submit_and_sleep(b)
        before_total = len(self.store.all_blocks())  # 6 主链 + 1 休眠 = 7

        result = self.store.promote_branch(b.block_hash)
        self.assertEqual(result.status, "promoted", result)
        self.assertEqual(self.store.height, 3)  # 新 tip = f + k = 2 + 1
        # 原主链 3..5 号块（被移除后缀）现在都在休眠；I-2 全店区块守恒。
        sleeping = {blk.block_hash for blocks in self.store.sleeping_branches().values() for blk in blocks}
        self.assertNotIn(b.block_hash, sleeping)
        self.assertEqual({blk.block_hash for blk in self.store.main_chain()} & sleeping, set())
        self.assertEqual(len(self.store.all_blocks()), before_total)

    # ---------------------------------------------------------------
    # T-05 延伸重组：新 tip 超原高度但仍在本纪元（H < f + k <= t）
    # ---------------------------------------------------------------
    def test_t05_extending_reorg(self):
        self.append_plain()
        self.append_plain()  # H=2
        b1 = self.make_candidate(height=3, parent_hash=self.store.tip.block_hash)
        b2 = self.make_candidate(height=4, parent_hash=b1.block_hash)
        b3 = self.make_candidate(height=5, parent_hash=b2.block_hash)
        for block in (b1, b2, b3):
            self.submit_and_sleep(block)

        result = self.store.promote_branch(b3.block_hash)
        self.assertEqual(result.status, "promoted", result)
        self.assertEqual(self.store.height, 5)
        # 后续 /propose 等价路径可正常接续新 tip。
        follow = self.make_candidate(height=6, parent_hash=self.store.tip.block_hash)
        result = validate_block(follow, self.store)
        self.assertTrue(result.accepted, result)

    # ---------------------------------------------------------------
    # T-06 资格拒绝：头不存在 / 孤儿链（父缺失）
    # ---------------------------------------------------------------
    def test_t06_head_missing_or_orphan(self):
        before = _state_digest(self.store)
        # 头不存在。
        result = self.store.promote_branch("0" * 64)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "PROMOTION_NOT_FOUND")
        self.assert_unchanged(before)
        # 头是主链块（不可提升）。
        self.append_plain()
        before = _state_digest(self.store)
        result = self.store.promote_branch(self.store.main_chain()[1].block_hash)
        self.assertEqual(result.error_code, "PROMOTION_NOT_FOUND")
        self.assert_unchanged(before)
        # 孤儿链：父哈希在全店不存在。
        orphan = self.make_candidate(height=3, parent_hash="a" * 64)
        self.store.add_sleeping_branch(orphan)
        before = _state_digest(self.store)
        result = self.store.promote_branch(orphan.block_hash)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "PROMOTION_PARENT_MISSING")
        self.assert_unchanged(before)

    # ---------------------------------------------------------------
    # T-07 资格拒绝：结构断裂（休眠废块高度非线性）
    # ---------------------------------------------------------------
    def test_t07_broken_chain(self):
        self.append_plain()
        self.append_plain()  # H=2
        b1 = self.make_candidate(height=3, parent_hash=self.store.tip.block_hash)
        self.store.add_sleeping_branch(b1)
        # b2 高度非线性：父为 b1（高度 3），自身高度 5。
        b2 = self.make_candidate(height=5, parent_hash=b1.block_hash)
        self.store.add_sleeping_branch(b2)
        before = _state_digest(self.store)

        result = self.store.promote_branch(b2.block_hash)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "PROMOTION_CHAIN_BROKEN")
        self.assert_unchanged(before)

    # ---------------------------------------------------------------
    # T-08 资格拒绝：后缀含已归档纪元块（跨纪元主链，fork < s - 1）
    # ---------------------------------------------------------------
    def test_t08_archived_epoch_suffix(self):
        self.fill_to(150)  # 纪元 0 已归档，纪元 1 活跃（e*=1, s=100）
        # 分支锚定在纪元 0 深处（高度 50），与主链同高度块内容不同避免哈希冲突。
        b = self.make_candidate(height=50, parent_hash=self.store.main_chain()[49].block_hash,
                                proposer="矿工·分支")
        self.submit_and_sleep(b)
        before = _state_digest(self.store)
        summary_before = [srv._summary_to_dict(item) for item in self.store.epoch_manager.summary_chain()]
        epoch0_before = self.store.epoch_manager.get_epoch_snapshot(0)

        result = self.store.promote_branch(b.block_hash)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "PROMOTION_ARCHIVED_EPOCH")
        # I-5：已归档摘要字节不变。
        summary_after = [srv._summary_to_dict(item) for item in self.store.epoch_manager.summary_chain()]
        self.assertEqual(summary_after, summary_before)
        epoch0_after = self.store.epoch_manager.get_epoch_snapshot(0)
        self.assertEqual(epoch0_after, epoch0_before)
        self.assert_unchanged(before)

    # ---------------------------------------------------------------
    # T-09 资格拒绝：分支越出当前纪元（含未来纪元块）
    # ---------------------------------------------------------------
    def test_t09_epoch_span(self):
        self.fill_to(199)  # e*=1, t=199（纪元 1 末块 = 高度 199）
        # 线性分支链跨入未来纪元：b1 为纪元 1 末块（高度 199），b2 为纪元 2 首块（高度 200）。
        b1 = self.make_candidate(height=199, parent_hash=self.store.main_chain()[198].block_hash,
                                 proposer="矿工·分支")
        self.submit_and_sleep(b1)
        b2 = self.make_candidate(height=200, parent_hash=b1.block_hash, proposer="矿工·分支")
        self.store.add_sleeping_branch(b2)
        before = _state_digest(self.store)

        result = self.store.promote_branch(b2.block_hash)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "PROMOTION_EPOCH_SPAN")
        self.assert_unchanged(before)

    # ---------------------------------------------------------------
    # T-10 语义拒绝：UTXO 失效（分支块花旧后缀创造的 UTXO）
    # ---------------------------------------------------------------
    def test_t10_utxo_invalid(self):
        self.append_plain()
        self.append_plain()
        self.append_plain()  # H=3；三个普通块均归 A（各 100 奖励）
        # m4：A 的奖励块（旧后缀首块，挖矿奖励 100 给 A）。
        m4 = self.make_candidate(height=4, parent_hash=self.store.tip.block_hash,
                                 private_key=self.private_key, public_key=self.public_key,
                                 proposer="矿工A")
        self.append(m4)
        self.assertEqual(self.store.utxo_ledger.get_balance(self.public_key), 400)
        # 分支块 b（高度 4，父 M[3]）花费 m4 的奖励 UTXO 转给 B。
        utxo = UTXO(bytes.fromhex(m4.block_hash), 0, self.public_key, 100)
        tx = make_signed_transaction(self.private_key, (utxo,), ((self.public_key_b, 100),))
        b = self.make_candidate(height=4, parent_hash=self.store.main_chain()[3].block_hash,
                                transactions=(tx,), private_key=self.private_key,
                                public_key=self.public_key, proposer="矿工A")
        self.submit_and_sleep(b)  # 旧世界合法（UTXO 存在）。
        before = _state_digest(self.store)

        result = self.store.promote_branch(b.block_hash)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "UTXO_INVALID")
        self.assertIn("height=4", result.message)
        self.assert_unchanged(before)

    # ---------------------------------------------------------------
    # T-11 语义拒绝：语言失效（重复激活 / 未引种）
    # ---------------------------------------------------------------
    def test_t11_language_invalid_duplicate(self):
        self.append_plain()
        self.append_plain()  # H=2
        m3 = self.make_candidate(height=3, parent_hash=self.store.tip.block_hash,
                                 activation=("-",), demo="(- 10 3)",
                                 tests=(TestCase("(- 10 3)", 7),))
        self.append(m3)
        # 分支块重复激活保留前缀已激活的 - -> 旧世界即 DUPLICATE，入休眠。
        b = self.make_candidate(height=4, parent_hash=self.store.tip.block_hash,
                                activation=("-",), demo="(- 5 2)",
                                tests=(TestCase("(- 5 2)", 3),))
        result = validate_block(b, self.store)
        self.assertEqual(result.error_code, "DUPLICATE_FEATURE")
        self.store.add_sleeping_branch(b)
        before = _state_digest(self.store)

        result = self.store.promote_branch(b.block_hash)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "DUPLICATE_FEATURE")
        self.assert_unchanged(before)

    def test_t11_language_invalid_unimported(self):
        # 纪元 0 激活 -；纪元 1 首块后失忆，分支块未引种直接使用 -> UNIMPORTED。
        first = self.make_candidate(height=1, parent_hash=self.store.tip.block_hash,
                                    activation=("-",), demo="(- 10 3)",
                                    tests=(TestCase("(- 10 3)", 7),))
        self.append(first)
        self.fill_to(100)
        b = self.make_candidate(height=101, parent_hash=self.store.tip.block_hash,
                                activation=(), demo="(- 10 3)",
                                tests=(TestCase("(- 10 3)", 7),))
        result = validate_block(b, self.store)
        self.assertEqual(result.error_code, "UNIMPORTED_FEATURE")
        self.store.add_sleeping_branch(b)
        before = _state_digest(self.store)

        result = self.store.promote_branch(b.block_hash)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "UNIMPORTED_FEATURE")
        self.assert_unchanged(before)

    # ---------------------------------------------------------------
    # T-12 语言重建正确性：旧后缀含唯一激活记录 -> 重组后 ever_active 收缩
    # ---------------------------------------------------------------
    def test_t12_language_rebuild_shrink(self):
        self.append_plain()
        self.append_plain()
        self.append_plain()  # H=3
        m4 = self.make_candidate(height=4, parent_hash=self.store.tip.block_hash,
                                 activation=("-",), demo="(- 10 3)",
                                 tests=(TestCase("(- 10 3)", 7),))
        self.append(m4)
        self.assertEqual(self.store.ever_active_features(), frozenset({"-"}))
        # 分支块（普通内核块）不激活任何原语。
        b = self.make_candidate(height=4, parent_hash=self.store.main_chain()[3].block_hash)
        self.submit_and_sleep(b)

        result = self.store.promote_branch(b.block_hash)
        self.assertEqual(result.status, "promoted", result)
        # 唯一激活记录在降级后缀中 -> ever_active 收缩（D3：重组 = 重推导事件）。
        self.assertEqual(self.store.ever_active_features(), frozenset())
        # 降级分组视图仍保留 -。
        self.assertEqual(self.store.branch_active_features(self.store.main_chain()[3].block_hash),
                         frozenset({"-"}))
        # 随后再激活 - 的提案按「新特性」路径通过（负测试重新成立）。
        reinstate = self.make_candidate(height=5, parent_hash=self.store.tip.block_hash,
                                        activation=("-",), demo="(- 10 3)",
                                        tests=(TestCase("(- 10 3)", 7),))
        result = validate_block(reinstate, self.store)
        self.assertTrue(result.accepted, result)
        self.store.append_main(reinstate)
        self.assertEqual(self.store.ever_active_features(), frozenset({"-"}))

    # ---------------------------------------------------------------
    # T-13 纪元摘要不变 + pending 重算
    # ---------------------------------------------------------------
    def test_t13_summary_frozen_pending_recomputed(self):
        self.fill_to(150)  # 纪元 0 finalized；纪元 1 pending（e*=1, t=199）
        summary_before = [srv._summary_to_dict(item) for item in self.store.epoch_manager.summary_chain()]
        epoch0_before = self.store.epoch_manager.get_epoch_snapshot(0)
        # 分支块（高度 101，父 M[100]）；与主链同高度块内容不同避免哈希冲突。
        b = self.make_candidate(height=101, parent_hash=self.store.main_chain()[100].block_hash,
                                proposer="矿工·分支")
        self.submit_and_sleep(b)

        result = self.store.promote_branch(b.block_hash)
        self.assertEqual(result.status, "promoted", result)
        # I-5：summary_chain 逐项不变。
        summary_after = [srv._summary_to_dict(item) for item in self.store.epoch_manager.summary_chain()]
        self.assertEqual(summary_after, summary_before)
        epoch0_after = self.store.epoch_manager.get_epoch_snapshot(0)
        self.assertEqual(epoch0_after, epoch0_before)
        # e* pending 快照按新链重算：end_height 150 -> 101，block_hashes 收缩。
        epoch1 = self.store.epoch_manager.get_epoch_snapshot(1)
        self.assertIsNotNone(epoch1)
        self.assertEqual(epoch1.end_height, 101)
        self.assertEqual(len(epoch1.block_hashes), 2)  # 100、101

    # ---------------------------------------------------------------
    # T-14 对合性：promote(C) 后再 promote(旧后缀链) 恢复原主链
    # ---------------------------------------------------------------
    def test_t14_involution(self):
        for _ in range(4):
            self.append_plain()  # M[0..4]，H=4
        # b1（高度 3，父 M[2]）先入休眠；与主链 m3 内容不同避免哈希冲突。
        b1 = self.make_candidate(height=3, parent_hash=self.store.main_chain()[2].block_hash,
                                 proposer="矿工·分支")
        self.submit_and_sleep(b1)
        initial = _state_digest(self.store)

        # 第一轮：提升 b1，旧后缀 M[3..4]（m3、m4）降级。
        result = self.store.promote_branch(b1.block_hash)
        self.assertEqual(result.status, "promoted", result)
        self.assertEqual(self.store.main_chain()[3].block_hash, b1.block_hash)
        sleeping = {blk.block_hash for blocks in self.store.sleeping_branches().values() for blk in blocks}
        self.assertEqual(len(sleeping), 2)

        # 第二轮：提升旧后缀链头（m4），恢复原主链。
        m4 = next(block for block in self.store.all_blocks()
                  if block.height == 4 and block.block_hash != b1.block_hash)
        result = self.store.promote_branch(m4.block_hash)
        self.assertEqual(result.status, "promoted", result)
        # I-12：共识态（主链/账本/语言/纪元/休眠集合）与初始态逐项相同。
        self.assertEqual(_state_digest(self.store), initial)

    # ---------------------------------------------------------------
    # T-15 持久化 round-trip：promote -> save -> load + rebuild 逐项等价
    # ---------------------------------------------------------------
    def test_t15_persistence_roundtrip(self):
        self.append_plain()
        self.append_plain()  # H=2
        b1 = self.make_candidate(height=3, parent_hash=self.store.tip.block_hash,
                                 activation=("-",), demo="(- 10 3)",
                                 tests=(TestCase("(- 10 3)", 7),))
        self.submit_and_sleep(b1)
        result = self.store.promote_branch(b1.block_hash)
        self.assertEqual(result.status, "promoted", result)
        self.assertEqual(self.store.ever_active_features(), frozenset({"-"}))

        archive = self.path("chain.json")
        miners = {self.public_key: ("矿工A", self.private_key)}
        persistence.save_state(archive, self.store, miners, {})
        data = persistence.load_state(archive)
        self.assertEqual(data["format_version"], "chain-v2")
        store2 = persistence.rebuild_store(data["blocks"], data["sleeping_branches"])

        # ① 高度与全部区块哈希一致。
        self.assertEqual(store2.height, self.store.height)
        self.assertEqual([b.block_hash for b in store2.main_chain()],
                         [b.block_hash for b in self.store.main_chain()])
        # ② 账本余额一致。
        for key in (self.public_key, self.public_key_b):
            self.assertEqual(store2.utxo_ledger.get_balance(key),
                             self.store.utxo_ledger.get_balance(key))
        # ③ 语言快照逐高度一致。
        for height in range(self.store.height + 1):
            self.assertEqual(store2.language_snapshot_at(height).active_features,
                             self.store.language_snapshot_at(height).active_features)
        # ③′ 激活后的原语在重建后仍可用（(- 10 3) == 7）。
        from novscript.language import LanguageSnapshot
        from novscript.sandbox import run_sandbox
        registry2 = LanguageSnapshot.build_registry(store2.language_snapshot_at(store2.height))
        result = run_sandbox("(- 10 3)", registry=registry2)
        self.assertTrue(result.ok, result)
        self.assertEqual(result.value, 7)
        # ④ 未激活高度（height=1，激活发生在被提升块 height=3）同一 demo 仍 NameError。
        result = run_sandbox("(- 10 3)",
                             registry=LanguageSnapshot.build_registry(store2.language_snapshot_at(1)))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "NameError")
        # ④ 休眠分组（branch_id + 组内哈希顺序）一致。
        self.assertEqual(store2.sleeping_branches(), self.store.sleeping_branches())
        # ⑤ 摘要链一致。
        self.assertEqual([srv._summary_to_dict(item) for item in store2.epoch_manager.summary_chain()],
                         [srv._summary_to_dict(item) for item in self.store.epoch_manager.summary_chain()])

    # ---------------------------------------------------------------
    # T-16 原子性总检 + API 契约
    # ---------------------------------------------------------------
    def test_t16_api_contract_and_pool_guard(self):
        archive = self.path("api_chain.json")
        state = srv.build_server_state(fresh=True, persist_path=archive)  # 预沉积 102 块
        store = state.store
        # 制造合法休眠候选（高度 103，父 tip；纯接续场景）。HTTP 流程下合法块
        # 直接上链，故用库级构造模拟「平票落选后入休眠」的分支。
        head = self.make_candidate(height=103, parent_hash=store.tip.block_hash,
                                   proposer="矿工·分支")
        result = validate_block(head, store)
        self.assertTrue(result.accepted, result)
        store.add_sleeping_branch(head)

        # 失败：缺参 / 头不存在。
        fail = srv.api_promote_branch(state, {"head_block_hash": ""})
        self.assertFalse(fail["success"])
        fail = srv.api_promote_branch(state, {"head_block_hash": "0" * 64})
        self.assertFalse(fail["success"])
        self.assertEqual(fail["error_code"], "PROMOTION_NOT_FOUND")

        # 候选池防御（D7）：池非空时拒绝重组。
        sibling = self.make_candidate(height=103, parent_hash=store.tip.block_hash,
                                      proposer="矿工·池")
        pool_result = validate_block(sibling, store)
        self.assertTrue(pool_result.accepted, pool_result)
        state.pool.submit_validated(sibling, pool_result)
        pool_result = srv.api_promote_branch(state, {"head_block_hash": head.block_hash})
        self.assertFalse(pool_result["success"])
        self.assertIn("候选池", pool_result["reason"])

        # 三旧端点字段超集兼容。
        cs = srv.api_chain_state(state)
        for field in ("chain_height", "blocks", "epochs", "sleeping_branches", "miners",
                      "epoch_blocks", "current_active_features", "summary_chain"):
            self.assertIn(field, cs)
        ev = srv.api_eval_novscript(state, {"code": "(+ 1 2)"})
        self.assertTrue(ev["ok"], ev)
        # /branches 新端点字段齐全。
        branches = srv.api_branches(state)
        self.assertIn("branches", branches)
        self.assertIn("sleeping_count", branches)
        self.assertGreaterEqual(branches["sleeping_count"], 1)
        item = branches["branches"][0]["blocks"][0]
        for field in ("height", "block_hash_b64", "reason", "promotion_status",
                      "promotion_error_code", "fork_height", "new_tip_height"):
            self.assertIn(field, item)

    def test_t16_promote_success_api_shape(self):
        archive = self.path("api_promote.json")
        state = srv.build_server_state(fresh=True, persist_path=archive)  # 预沉积 102 块
        store = state.store
        # 制造合法休眠候选（高度 103，父 tip；纯接续）。
        head = self.make_candidate(height=103, parent_hash=store.tip.block_hash,
                                   proposer="矿工·分支")
        result = validate_block(head, store)
        self.assertTrue(result.accepted, result)
        store.add_sleeping_branch(head)

        result = srv.api_promote_branch(state, {"head_block_hash": head.block_hash})
        self.assertTrue(result["success"], result)
        self.assertTrue(result["is_promoted"])
        self.assertEqual(result["chain_height"], 103)
        self.assertEqual(result["old_tip_height"], 102)
        self.assertEqual(result["new_tip_height"], 103)
        self.assertEqual(len(result["promoted_hashes"]), 1)
        self.assertEqual(result["demoted_hashes"], [])
        # 链状态已变更：被提升块进入主链。
        self.assertEqual(store.main_chain()[-1].block_hash, head.block_hash)
        # 降级/提升记账：休眠列表不再含被提升块。
        sleeping = {blk.block_hash for blocks in store.sleeping_branches().values() for blk in blocks}
        self.assertNotIn(head.block_hash, sleeping)


if __name__ == "__main__":
    unittest.main()
