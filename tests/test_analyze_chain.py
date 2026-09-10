"""StratumGenesis v0.3 · 并行线 C：离线链分析器测试。

覆盖范围（只针对新增的 analyze_chain.py，不启动 HTTP 服务、不读写 data/）：
  1. 合成链的语言演化指标：首次激活高度、新激活/引种分类、逐纪元失忆集合；
  2. 合成链的链与共识、账本、PoI 指标与休眠分支对账；
  3. 边界：空链（无 blocks）与仅创世块；
  4. 错误处理：文件不存在、损坏 JSON、根节点非对象、版本不匹配、缺 blocks；
  5. 依赖边界：指标只由 blocks[].activation / height 推导，不依赖
     epochs[].active_features / current_active_features / language_features，
     且不信任 blocks[].epoch（按 height // 100 重新推导）。

本测试不触碰端口 28417，因此可单独用
    python -m unittest discover -s tests -p "test_analyze_chain.py"
运行，不需要起服务、不需要真实 ecdsa 包（缺失时走 analyze_chain 的标准库回退）。
"""

import contextlib
import io
import json
import os
import tempfile
import unittest

import analyze_chain


# ---------------------------------------------------------------------------
# 测试用最小 JSON 构造器（刻意省略 activation / height 以外的所有派生字段）
# ---------------------------------------------------------------------------
def make_block(height: int, activation=(), tokens: int = 30,
               miner: str = "AA==", proposer: str = "", tokenizer: str = "mock-v1") -> dict:
    """构造一个只含稳定字段的最小区块条目。"""
    return {
        "height": height,
        "epoch": 999,  # 故意写错：分析器必须按 height // 100 重新推导
        "miner_pubkey_b64": miner,
        "block_hash": "hash-%d" % height,
        "proposer": proposer,
        "activation": list(activation),
        "poi": {
            "standard_tokenizer": tokenizer,
            "standard_total_tokens": tokens,
            "standard_input_tokens": tokens // 3,
            "standard_output_tokens": tokens - tokens // 3,
        },
    }


def make_archive(blocks, miners=None, **extra) -> dict:
    """构造一份最小 chain-v2 存档（含一批故意写错的派生字段用于泄漏检测）。"""
    archive = {
        "format_version": "chain-v2",
        # 下面这些字段必须完全被忽略；值里带 SENTINEL 前缀便于断言「零泄漏」
        "current_active_features": ["SENTINEL_A", "SENTINEL_B"],
        "language_features": [{"id": "SENTINEL_C"}],
        "epochs": [
            {"epoch": 0, "active_features": ["SENTINEL_D"]},
            {"epoch": 1, "active_features": ["SENTINEL_E"]},
        ],
        "blocks": list(blocks),
        "sleeping_branches": [],
        "rejection_reasons": {},
    }
    if miners is not None:
        archive["miners"] = miners
    archive.update(extra)
    return archive


def write_tmp(doc, name: str = "archive.json") -> str:
    """把对象写进系统临时目录（不碰项目 data/），返回路径。"""
    handle, path = tempfile.mkstemp(prefix="analyze_chain_test_", suffix=".json")
    with os.fdopen(handle, "w", encoding="utf-8") as handle:
        if isinstance(doc, str):
            handle.write(doc)
        else:
            json.dump(doc, handle, ensure_ascii=False)
    os.chmod(path, 0o600)
    return path


class SyntheticChainLanguageMetricsTest(unittest.TestCase):
    """合成链（跨 3 个纪元）的语言演化指标。"""

    @classmethod
    def setUpClass(cls):
        cls.data = analyze_chain.build_synthetic_chain()

    def test_shape(self):
        blocks = self.data["blocks"]
        epochs = analyze_chain.analyze_language(self.data)
        self.assertEqual(epochs["first_activation_count"], 4)
        self.assertEqual(epochs["activation_events_total"], 5)
        self.assertEqual(len(epochs["epochs"]), 3)
        self.assertEqual(blocks[0]["height"], 0)
        self.assertEqual(blocks[-1]["height"], 205)

    def test_first_activation_heights(self):
        first = analyze_chain.analyze_language(self.data)["first_activation"]
        self.assertEqual(first["-"]["height"], 1)
        self.assertEqual(first["-"]["epoch"], 0)
        self.assertEqual(first["list"]["height"], 2)
        self.assertEqual(first["head"]["height"], 2)
        self.assertEqual(first["*"]["height"], 101)
        self.assertEqual(first["*"]["epoch"], 1)

    def test_epoch0_all_new_no_inoculation(self):
        rec = analyze_chain.analyze_language(self.data)["epochs"][0]
        self.assertEqual(rec["epoch"], 0)
        self.assertEqual(rec["newly_activated"], ["-", "head", "list"])
        self.assertEqual(rec["inoculated"], [])
        self.assertEqual(rec["lost_memory"], [])
        self.assertEqual(rec["available_at_open"], ["-"])

    def test_epoch1_inoculation_and_new_activation(self):
        rec = analyze_chain.analyze_language(self.data)["epochs"][1]
        self.assertEqual(rec["epoch"], 1)
        self.assertEqual(rec["available_at_open"], ["-"])
        self.assertEqual(rec["inoculated"], ["-"])
        self.assertEqual(rec["inoculated_count"], 1)
        self.assertEqual(rec["newly_activated"], ["*"])
        # 纪元开篇未引种 head / list -> 相对纪元 0 的失忆集合
        self.assertEqual(rec["lost_memory"], ["head", "list"])
        self.assertEqual(rec["lost_memory_count"], 2)

    def test_epoch2_total_amnesia(self):
        rec = analyze_chain.analyze_language(self.data)["epochs"][2]
        self.assertEqual(rec["epoch"], 2)
        self.assertEqual(rec["available_at_open"], [])
        self.assertEqual(rec["newly_activated"], [])
        self.assertEqual(rec["inoculated"], [])
        self.assertEqual(rec["lost_memory"], ["*", "-", "head", "list"])
        self.assertEqual(rec["lost_memory_count"], 4)

    def test_totals_and_provenance_only_grows(self):
        lang = analyze_chain.analyze_language(self.data)
        self.assertEqual(lang["total_inoculation_events"], 1)
        self.assertEqual(lang["total_new_activations"], 4)
        self.assertEqual(lang["total_lost_memory_features"], 6)
        # 历史层 provenance 只增不减，与逐纪元推导一致
        self.assertEqual(lang["cumulative_ever_active"], ["*", "-", "head", "list"])


class SyntheticChainOtherMetricsTest(unittest.TestCase):
    """合成链的链与共识 / 账本 / PoI / 休眠分支指标。"""

    @classmethod
    def setUpClass(cls):
        cls.data = analyze_chain.build_synthetic_chain()

    def test_chain_consensus(self):
        cons = analyze_chain.analyze_chain_consensus(self.data)
        self.assertEqual(cons["total_height"], 205)
        self.assertEqual(cons["main_chain_blocks"], 206)
        self.assertEqual(cons["epoch_count"], 3)
        blocks_by_epoch = [rec["blocks"] for rec in cons["epochs"]]
        self.assertEqual(blocks_by_epoch, [100, 100, 6])
        self.assertEqual([rec["is_full"] for rec in cons["epochs"]], [True, True, False])
        self.assertEqual(cons["sleeping_branch_count"], 1)
        self.assertEqual(cons["sleeping_branch_block_total"], 1)
        branch = cons["sleeping_branches"][0]
        self.assertEqual(branch["blocks"], 1)
        self.assertEqual(branch["activations"], ["-"])
        self.assertEqual(branch["epochs"], [2])
        self.assertEqual(branch["rejection_reason"], "冲突投票落选，保存为休眠分支")
        self.assertEqual(cons["rejection_reason_counts"],
                         {"冲突投票落选，保存为休眠分支": 1})

    def test_proposal_success_rate(self):
        rate = analyze_chain.analyze_chain_consensus(self.data)["proposal_success_rate"]
        self.assertEqual(rate["proposals_submitted"], 206)
        self.assertEqual(rate["accepted_to_main"], 205)
        self.assertEqual(rate["rejected_to_branch"], 1)
        self.assertAlmostEqual(rate["rate_main"], 205 / 206, places=9)
        self.assertAlmostEqual(rate["rate_sleeping_branch"], 1 / 206, places=9)

    def test_miner_output_and_weight(self):
        cons = analyze_chain.analyze_chain_consensus(self.data)
        by_miner = cons["miners"]["by_miner"]
        registered = [row for row in by_miner if row["registered_in_archive"]]
        unregistered = [row for row in by_miner if not row["registered_in_archive"]]
        self.assertEqual(cons["miners"]["count"], 4)
        # 3 个注册矿工 + 1 个仅出创世块（不在 miners 注册表）
        self.assertEqual(len(registered), 3)
        self.assertEqual(len(unregistered), 1)
        self.assertEqual(unregistered[0]["genesis_blocks"], 1)
        self.assertEqual(unregistered[0]["standard_total_tokens"], 0)
        # 三矿工轮换产出，块数应在 68~69 之间且合计 205
        self.assertEqual(sum(row["blocks"] for row in registered), 205)
        for row in registered:
            self.assertIn(row["blocks"], (68, 69))
            self.assertEqual(row["avg_tokens_per_block"] * row["blocks"],
                             row["standard_total_tokens"])
        total = sum(row["standard_total_tokens"] for row in by_miner)
        self.assertAlmostEqual(sum(row["share_of_total_tokens"] for row in by_miner if
                                   row["share_of_total_tokens"] is not None), 1.0, places=9)
        dist = cons["voting_weight_distribution"]
        self.assertEqual(dist["total_weight"], total)
        self.assertGreater(dist["max"], dist["p50"])
        self.assertGreaterEqual(dist["p50"], dist["min"])
        self.assertAlmostEqual(dist["rows"][0]["share"], dist["top_miner_share"], places=9)

    def test_ledger(self):
        ledger = analyze_chain.ledger_metrics(self.data)
        self.assertTrue(ledger["warnings"] == [], ledger["warnings"])
        self.assertEqual(ledger["reward_amount"], 100)
        # 创世块不发奖励：206 块 -> 205 块发奖励
        self.assertEqual(ledger["rewarded_blocks"], 205)
        self.assertEqual(ledger["rewards_issued"], 20500)
        self.assertEqual(ledger["consumed_by_transactions"], 0)
        self.assertEqual(ledger["total_supply"], 20500)
        self.assertEqual(ledger["unspent_utxos"], 205)
        self.assertEqual(ledger["transaction_count"], 0)
        balances = ledger["balances"]
        self.assertEqual(len(balances), 3)
        self.assertEqual(sum(row["balance"] for row in balances), ledger["total_supply"])
        self.assertEqual(sum(row["unspent_utxos"] for row in balances), 205)
        # 余额 = 块数 * 100，与共识侧的矿工块数可对账
        cons = analyze_chain.analyze_chain_consensus(self.data)
        for row in balances:
            match = [m for m in cons["miners"]["by_miner"]
                     if m["miner"] == row["miner"]]
            self.assertEqual(len(match), 1, "矿工 %s 未在共识侧匹配到" % row["miner"])
            self.assertEqual(match[0]["blocks"] * 100, row["balance"])

    def test_poi(self):
        poi = analyze_chain.analyze_poi(self.data)
        self.assertEqual(poi["blocks"], 206)
        self.assertEqual(poi["zero_token_blocks"], 1)  # 创世块
        self.assertEqual(poi["total_tokens"], sum(
            b["poi"]["standard_total_tokens"] for b in self.data["blocks"]))
        self.assertEqual(poi["input_tokens_total"] + poi["output_tokens_total"],
                         poi["total_tokens"])
        main_only = poi["main_chain_only"]
        self.assertEqual(main_only["blocks"], 205)
        self.assertEqual(main_only["total_tokens"], poi["total_tokens"])
        self.assertAlmostEqual(poi["mean"], poi["total_tokens"] / 206, places=6)
        usage = poi["tokenizer_usage"]
        self.assertEqual(sum(info["blocks"] for info in usage.values()), 206)
        self.assertEqual(sum(info["blocks_with_tokens"] for info in usage.values()), 205)
        self.assertLessEqual(poi["p25"], poi["median"])
        self.assertLessEqual(poi["median"], poi["p75"])
        self.assertLessEqual(poi["p75"], poi["p90"])


class EdgeCaseTest(unittest.TestCase):
    """空链 / 仅创世块等边界处理。"""

    def test_empty_chain(self):
        data = make_archive([])
        report, _ = analyze_chain.build_report(data, source="test", source_label="test")
        chain = report["chain"]
        self.assertEqual(chain["total_height"], 0)
        self.assertEqual(chain["main_chain_blocks"], 0)
        self.assertEqual(chain["epoch_count"], 0)
        lang = report["language_evolution"]
        self.assertEqual(lang["epochs"], [])
        self.assertEqual(lang["first_activation"], {})
        self.assertEqual(lang["total_inoculation_events"], 0)
        self.assertEqual(lang["total_lost_memory_features"], 0)
        cons = report["chain_consensus"]
        self.assertEqual(cons["miners"]["count"], 0)
        self.assertIsNone(cons["proposal_success_rate"]["rate_main"])
        self.assertIsNone(cons["proposal_success_rate"]["rate_sleeping_branch"])
        poi = report["poi"]
        self.assertEqual(poi["blocks"], 0)
        self.assertEqual(poi["total_tokens"], 0)
        self.assertEqual(poi["mean"], 0.0)
        ledger = report["ledger"]
        self.assertEqual(ledger["total_supply"], 0)
        self.assertEqual(ledger["rewards_issued"], 0)
        self.assertIn("主链为空", " | ".join(report["warnings"]))

    def test_genesis_only(self):
        data = make_archive([make_block(0, tokens=0)])
        report, _ = analyze_chain.build_report(data, source="test", source_label="test")
        chain = report["chain"]
        self.assertEqual(chain["total_height"], 0)
        self.assertEqual(chain["main_chain_blocks"], 1)
        self.assertEqual(chain["epoch_count"], 1)
        lang = report["language_evolution"]
        self.assertEqual(lang["epochs"][0]["epoch"], 0)
        self.assertEqual(lang["epochs"][0]["blocks"], 1)
        self.assertEqual(lang["activation_events_total"], 0)
        # 只有一个纪元，不存在「相对上一纪元」的比较，失忆应为空而非报错
        self.assertEqual(lang["epochs"][0]["lost_memory"], [])
        cons = report["chain_consensus"]
        # 创世块不是提案 -> 提交 0 个提案，比率应为 None（无样本）
        self.assertEqual(cons["proposal_success_rate"]["proposals_submitted"], 0)
        self.assertIsNone(cons["proposal_success_rate"]["rate_main"])
        ledger = report["ledger"]
        self.assertEqual(ledger["rewarded_blocks"], 0)
        self.assertEqual(ledger["total_supply"], 0)
        poi = report["poi"]
        self.assertEqual(poi["blocks"], 1)
        self.assertEqual(poi["total_tokens"], 0)
        self.assertEqual(poi["main_chain_only"]["blocks"], 0)

    def test_corrupt_block_shape_is_rejected(self):
        with self.assertRaises(analyze_chain.AnalysisError) as ctx:
            analyze_chain.analyze_language({"blocks": [
                {"height": 1, "poi": "not-a-dict", "activation": []}
            ]})
        self.assertIn("存档已损坏", str(ctx.exception))
        with self.assertRaises(analyze_chain.AnalysisError):
            analyze_chain.analyze_language({"blocks": [{"height": -1, "poi": {}}]})
        with self.assertRaises(analyze_chain.AnalysisError):
            analyze_chain.analyze_language({"blocks": [{"height": "x", "poi": {}}]})


class ErrorHandlingTest(unittest.TestCase):
    """损坏 JSON / 版本不匹配 / 结构错误的明确报错与非零退出。"""

    def test_missing_file(self):
        path = os.path.join(tempfile.gettempdir(), "analyze_chain_no_such_file.json")
        with self.assertRaises(analyze_chain.AnalysisError) as ctx:
            analyze_chain.load_archive(path)
        self.assertIn("无法读取", str(ctx.exception))

    def test_corrupt_json(self):
        path = write_tmp("{this is not json")
        with self.assertRaises(analyze_chain.AnalysisError) as ctx:
            analyze_chain.load_archive(path)
        self.assertIn("已损坏", str(ctx.exception))

    def test_non_object_root(self):
        path = write_tmp("[]")
        with self.assertRaises(analyze_chain.AnalysisError) as ctx:
            analyze_chain.load_archive(path)
        self.assertIn("根节点必须是 JSON 对象", str(ctx.exception))

    def test_wrong_version(self):
        path = write_tmp({"format_version": "chain-v1", "blocks": []})
        with self.assertRaises(analyze_chain.AnalysisError) as ctx:
            analyze_chain.load_archive(path)
        self.assertIn("格式版本不匹配", str(ctx.exception))
        self.assertIn("chain-v2", str(ctx.exception))

    def test_missing_blocks_field(self):
        path = write_tmp({"format_version": "chain-v2"})
        with self.assertRaises(analyze_chain.AnalysisError) as ctx:
            analyze_chain.load_archive(path)
        self.assertIn("blocks", str(ctx.exception))

    def test_cli_returns_nonzero_on_error(self):
        path = write_tmp("{broken")
        self.assertEqual(analyze_chain.main([path]), 1)
        self.assertEqual(analyze_chain.main([
            os.path.join(tempfile.gettempdir(), "analyze_chain_absent.json")]), 1)

    def test_cli_returns_zero_on_success(self):
        self.assertEqual(analyze_chain.main(["--synthetic", "--compact"]), 0)
        path = write_tmp(make_archive([make_block(0), make_block(1, activation=["a"])]))
        self.assertEqual(analyze_chain.main([path, "--compact"]), 0)


class DependencyBoundaryTest(unittest.TestCase):
    """指标依赖边界：只读稳定字段，派生字段与 blocks[].epoch 必须被忽略。"""

    SENTINELS = ("SENTINEL_A", "SENTINEL_B", "SENTINEL_C",
                 "SENTINEL_D", "SENTINEL_E")

    def _report(self, blocks, **extra):
        data = make_archive(blocks, **extra)
        return analyze_chain.build_report(data, source="test", source_label="test")

    def test_ignored_fields_do_not_leak_into_report(self):
        report, text = self._report([
            make_block(0),
            make_block(1, activation=["alpha"]),
            make_block(100, activation=["alpha", "beta"]),
            make_block(200),
        ])
        for sentinel in self.SENTINELS:
            self.assertNotIn(sentinel, text)
        raw = json.dumps(report, ensure_ascii=False)
        for sentinel in self.SENTINELS:
            self.assertNotIn(sentinel, raw)

    def test_epoch_is_recomputed_from_height(self):
        data = make_archive([
            make_block(0),
            make_block(1, activation=["alpha"]),
            make_block(100, activation=["alpha", "beta"]),
            make_block(200),
        ])
        # 所有块的 blocks[].epoch 都被故意写成 999
        for block in data["blocks"]:
            self.assertEqual(block["epoch"], 999)
        report, _ = analyze_chain.build_report(data, source="t", source_label="t")
        cons = report["chain_consensus"]
        self.assertEqual(cons["epoch_count"], 3)
        self.assertEqual([rec["epoch"] for rec in cons["epochs"]], [0, 1, 2])
        self.assertEqual(cons["epochs"][0]["start_height"], 0)
        self.assertEqual(cons["epochs"][1]["start_height"], 100)
        self.assertEqual(cons["epochs"][2]["start_height"], 200)
        self.assertEqual(
            [rec["epoch"] for rec in report["language_evolution"]["epochs"]], [0, 1, 2])

    def test_activation_and_height_drive_language_metrics(self):
        report, _ = self._report([
            make_block(0),
            make_block(1, activation=["alpha"]),
            make_block(100, activation=["alpha", "beta"]),
            make_block(200),
        ])
        lang = report["language_evolution"]
        self.assertEqual(lang["first_activation"], {
            "alpha": {"epoch": 0, "height": 1, "proposer": ""},
            "beta": {"epoch": 1, "height": 100, "proposer": ""},
        })
        self.assertEqual(lang["total_inoculation_events"], 1)
        self.assertEqual(lang["total_new_activations"], 2)
        self.assertEqual(lang["total_lost_memory_features"], 2)
        by_epoch = {rec["epoch"]: rec for rec in lang["epochs"]}
        self.assertEqual(by_epoch[0]["newly_activated"], ["alpha"])
        self.assertEqual(by_epoch[1]["inoculated"], ["alpha"])
        self.assertEqual(by_epoch[1]["newly_activated"], ["beta"])
        self.assertEqual(by_epoch[1]["lost_memory"], [])
        self.assertEqual(by_epoch[2]["lost_memory"], ["alpha", "beta"])

    def test_activation_defaults_to_empty_when_missing(self):
        data = make_archive([
            make_block(0),
            {"height": 1, "epoch": 999, "block_hash": "h1", "poi": {}},  # 无 activation
        ])
        lang = analyze_chain.analyze_language(data)
        self.assertEqual(lang["activation_events_total"], 0)
        self.assertEqual(lang["epochs"][0]["available_at_open"], [])

    def test_provenance_declares_the_boundary(self):
        report, _ = self._report([make_block(0), make_block(1, activation=["a"])])
        provenance = report["field_provenance"]
        self.assertIn("blocks[].activation", provenance["derived_from"])
        self.assertIn("blocks[].height", provenance["derived_from"])
        self.assertEqual(provenance["epoch_formula"], "epoch = height // 100")
        for field in ("epochs[].active_features", "current_active_features",
                      "language_features", "blocks[].epoch"):
            self.assertIn(field, provenance["avoided_fields"])
        for field in provenance["avoided_fields"]:
            self.assertNotIn(field, provenance["derived_from"])
        self.assertEqual(analyze_chain.EPOCH_BLOCKS, 100)


class VerifyAndTamperTest(unittest.TestCase):
    """--verify 走 crypto_key.verify_block_signature；篡改签名必须被抓到。

    真实签名只有 build_synthetic_chain 能提供（make_block 的最小条目无签名），
    因此这里序列化合成链到临时目录再验。不触碰端口、不读写 data/。
    """

    @classmethod
    def setUpClass(cls):
        if analyze_chain.ECDSA_BACKEND != analyze_chain.BACKEND_PYTHON_ECDSA:
            raise unittest.SkipTest("本机缺少 ecdsa，跳过真实验签往返测试")
        import tempfile as _tf
        cls.dir = tempfile.mkdtemp(prefix="analyze_chain_verify_")
        doc = analyze_chain.build_synthetic_chain()
        cls.path = os.path.join(cls.dir, "clean.json")
        with open(cls.path, "w", encoding="utf-8") as handle:
            json.dump(doc, handle, ensure_ascii=False)

    def test_schema_reports_python_ecdsa(self):
        report, _ = analyze_chain.build_report(
            analyze_chain.load_archive(self.path), source="t", source_label="t")
        self.assertEqual(report["schema"]["ecdsa_backend"], "python-ecdsa")
        self.assertEqual(report["schema"]["signature_verification"], "enabled")

    def test_verify_archive_passes_on_clean_archive(self):
        passed, detail = analyze_chain.verify_archive(self.path)
        self.assertTrue(passed, detail)
        self.assertIn("ECDSA 签名重验通过", detail)
        self.assertIn("206 个主链区块", detail)

    def test_verify_clean_archive_exits_zero(self):
        self.assertEqual(analyze_chain.main([self.path, "--compact", "--verify"]), 0)

    def test_verify_hashes_alias_is_accepted(self):
        # --verify-hashes 是 --verify 的等价别名；argparse 拒绝未知旗标会 exit 2
        self.assertEqual(analyze_chain.main([self.path, "--compact", "--verify-hashes"]), 0)

    def test_tampered_signature_is_rejected(self):
        import base64 as _b64
        with open(self.path, "r", encoding="utf-8") as handle:
            doc = json.load(handle)
        target = next(b for b in doc["blocks"] if b["height"] == 42)
        signature = _b64.b64decode(target["signature_bytes_b64"])  # bytes（32 字节 DER-less 签名）
        # 翻转 32 字节签名的前导字节：哈希仍匹配（签名不在 block_hash 内），签名必失效
        flipped = bytes([signature[0] ^ 0xFF]) + signature[1:]
        tampered = dict(doc)
        tampered["blocks"] = [dict(b) for b in doc["blocks"]]
        for block in tampered["blocks"]:
            if block["height"] == 42:
                block["signature_bytes_b64"] = _b64.b64encode(flipped).decode()
        path = os.path.join(self.dir, "tampered.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(tampered, handle, ensure_ascii=False)

        passed, detail = analyze_chain.verify_archive(path)
        self.assertFalse(passed)
        self.assertIn("签名校验失败", detail)
        self.assertIn("height=42", detail)
        self.assertEqual(analyze_chain.main([path, "--compact", "--verify"]), 1)


class MissingEcdsaSkipTest(unittest.TestCase):
    """缺少 ecdsa 依赖：明确跳过 + schema/warnings 标注，绝不冒充真实验签。

    用临时属性打点模拟缺失（测试专用，不落正式代码）；tearDown 中还原，
    因此不影响同进程内其他测试的真实后端判定。
    """

    def _patch_missing(self):
        self._saved_backend = analyze_chain.ECDSA_BACKEND
        analyze_chain.ECDSA_BACKEND = analyze_chain.BACKEND_UNAVAILABLE

    def tearDown(self):
        if hasattr(self, "_saved_backend"):
            analyze_chain.ECDSA_BACKEND = self._saved_backend

    def test_backend_probe_reports_unavailable(self):
        self._patch_missing()
        self.assertEqual(analyze_chain.BACKEND_UNAVAILABLE, "unavailable")
        self.assertEqual(analyze_chain.VERIFY_SKIPPED_NO_ECDSA, "skipped_no_ecdsa")

    def test_verify_archive_refuses_to_fake_success(self):
        self._patch_missing()
        path = write_tmp(make_archive([make_block(0), make_block(1)]))
        passed, detail = analyze_chain.verify_archive(path)
        self.assertFalse(passed, "缺依赖时不得返回通过")
        self.assertIn("缺少 ecdsa 依赖", detail)
        self.assertIn("跳过签名重验", detail)

    def test_report_schema_marks_skipped(self):
        self._patch_missing()
        report, text = analyze_chain.build_report(
            make_archive([make_block(0), make_block(1, activation=["a"])]),
            source="test", source_label="test")
        self.assertEqual(report["schema"]["ecdsa_backend"], "unavailable")
        self.assertEqual(report["schema"]["signature_verification"], "skipped_no_ecdsa")
        self.assertIn("缺少 ecdsa", " | ".join(report["warnings"]))
        self.assertIn("缺少 ecdsa 依赖，签名重验已跳过", text)

    def test_cli_skips_and_still_analyzes(self):
        self._patch_missing()
        path = write_tmp(make_archive([make_block(0), make_block(1, activation=["a"])]))
        out_path = write_tmp({}, name="verify_skip_out.json")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = analyze_chain.main([path, "--verify", "--json", out_path])
        self.assertEqual(code, 0)
        self.assertIn("本机缺少 ecdsa 依赖，跳过签名重验", buffer.getvalue())
        with open(out_path, "r", encoding="utf-8") as handle:
            doc = json.load(handle)
        self.assertEqual(doc["schema"]["ecdsa_backend"], "unavailable")
        self.assertEqual(doc["schema"]["signature_verification"], "skipped_no_ecdsa")
        self.assertIn("缺少 ecdsa", " | ".join(doc["warnings"]))


class NoArgumentFallbackTest(unittest.TestCase):
    """无位置参数：提示 + 内存合成链演示 + 退出码 0（已批准行为，须可断言）。"""

    def test_no_archive_prints_hint_and_exits_zero(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = analyze_chain.main(["--compact"])
        output = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("[提示]", output)
        self.assertIn("内存合成链", output)
        self.assertIn("来源=合成链（无存档模式）", output)

    def test_help_documents_the_flag_and_the_fallback(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            with self.assertRaises(SystemExit) as ctx:
                analyze_chain.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        help_text = buffer.getvalue()
        self.assertIn("--verify", help_text)
        self.assertIn("--verify-hashes", help_text)
        # docstring 与 --help 不再宣传不存在的旗标
        self.assertNotIn("--verify-hashes 并不存在", help_text)
        # P3：无参数行为必须写进 --help，避免自动化调用方误判
        self.assertIn("退出码仍为 0", help_text)
        self.assertIn("参数被忽略", help_text)


if __name__ == "__main__":
    unittest.main()
