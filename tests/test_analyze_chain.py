"""StratumGenesis v0.3 · 并行线 C：离线链分析器测试。

覆盖范围（只针对 analyze_chain.py，不启动 HTTP 服务、不读写 data/）：
  1. 合成链的语言演化指标：首次激活高度、新激活/引种分类、逐纪元失忆集合；
  2. 合成链的链与共识、账本、PoI 指标与休眠分支对账；
  3. 边界：空链（无 blocks）与仅创世块；
  4. 错误处理：文件不存在、损坏 JSON、根节点非对象、版本不匹配、缺 blocks；
  5. 依赖边界：指标只由 blocks[].activation / height 推导，不依赖
     epochs[].active_features / current_active_features / language_features，
     且不信任 blocks[].epoch（按 height // 100 重新推导）；
  6. 跨 AI 创造力指标（--by-model）：按 blocks[].poi.model_metadata 分组的
     接受与产出、引种留存率与半衰期、原语偏好、组合新颖度、分工与协作；
  7. 缺 ecdsa 依赖的诚实降级：依赖项以 @unittest.skipUnless 跳过（0 失败 0 错误），
     无参回退/--synthetic 打印中文可执行提示并以非零码退出。

本测试不触碰端口 28417，因此可单独用
    python -m unittest discover -s tests -p "test_analyze_chain.py"
运行；有 ecdsa（Python 3.13）时全部通过，无 ecdsa 时依赖合成链/验签的用例被跳过。
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

import analyze_chain


def _ecdsa_available() -> bool:
    """skipUnless 用的可判定谓词：仅当真实后端为 python-ecdsa 时才运行依赖用例。"""
    return analyze_chain.ECDSA_BACKEND == analyze_chain.BACKEND_PYTHON_ECDSA


ECDSA_REQUIRED = "需要 ecdsa 依赖（构造合成链/验签需 crypto_key 真实签名）"


# ---------------------------------------------------------------------------
# 测试用最小 JSON 构造器（刻意省略 activation / height 以外的所有派生字段）
# ---------------------------------------------------------------------------
def make_block(height: int, activation=(), tokens: int = 30,
               miner: str = "AA==", proposer: str = "", tokenizer: str = "mock-v1",
               model_metadata: str = "") -> dict:
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
            "model_metadata": model_metadata,
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


@unittest.skipUnless(_ecdsa_available(), ECDSA_REQUIRED)
class SyntheticChainLanguageMetricsTest(unittest.TestCase):
    """合成链（跨 3 个纪元）的语言演化指标。构造合成链需要 ecdsa 真实签名。"""

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


@unittest.skipUnless(_ecdsa_available(), ECDSA_REQUIRED)
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
        # 存档路径不依赖 ecdsa（账本重放失败时自动降级），可无 ecdsa 运行
        path = write_tmp(make_archive([make_block(0), make_block(1, activation=["a"])]))
        self.assertEqual(analyze_chain.main([path, "--compact"]), 0)

    @unittest.skipUnless(_ecdsa_available(), ECDSA_REQUIRED)
    def test_cli_synthetic_returns_zero(self):
        # --synthetic 构造合成链需要 ecdsa 真实签名，缺依赖时返回 1（见
        # MissingEcdsaChineseHintTest），因此 exit 0 分支在此断言
        self.assertEqual(analyze_chain.main(["--synthetic", "--compact"]), 0)


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


@unittest.skipUnless(_ecdsa_available(), ECDSA_REQUIRED)
class VerifyAndTamperTest(unittest.TestCase):
    """--verify 走 crypto_key.verify_block_signature；篡改签名必须被抓到。

    真实签名只有 build_synthetic_chain 能提供（make_block 的最小条目无签名），
    因此这里序列化合成链到临时目录再验。不触碰端口、不读写 data/。
    本类依赖 ecdsa，缺依赖时整类跳过（@unittest.skipUnless）。
    """

    @classmethod
    def setUpClass(cls):
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

    @unittest.skipUnless(_ecdsa_available(), "需要 ecdsa 依赖（无参回退 exit 0 需 ecdsa 可用）")
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


class MissingEcdsaChineseHintTest(unittest.TestCase):
    """缺 ecdsa 依赖：中文可执行提示 + 非零退出（模拟缺失，不落正式代码）。

    用临时改写 analyze_chain.ECDSA_BACKEND 模拟缺失；tearDown 还原，
    不影响同进程内其他测试的真实后端判定。
    """

    def _patch_missing(self):
        self._saved_backend = analyze_chain.ECDSA_BACKEND
        analyze_chain.ECDSA_BACKEND = analyze_chain.BACKEND_UNAVAILABLE

    def tearDown(self):
        if hasattr(self, "_saved_backend"):
            analyze_chain.ECDSA_BACKEND = self._saved_backend

    def test_require_ecdsa_raises_chinese_hint(self):
        self._patch_missing()
        with self.assertRaises(analyze_chain.AnalysisError) as ctx:
            analyze_chain.require_ecdsa_for_synthetic()
        message = str(ctx.exception)
        self.assertIn("缺少 ecdsa 依赖", message)
        self.assertIn("pip install ecdsa", message)
        self.assertNotIn("No module named", message)

    def test_synthetic_without_ecdsa_exits_nonzero_with_chinese_hint(self):
        self._patch_missing()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = analyze_chain.main(["--synthetic", "--compact"])
        self.assertEqual(code, 1)
        output = buffer.getvalue()
        self.assertIn("缺少 ecdsa 依赖", output)
        self.assertIn("pip install ecdsa", output)
        self.assertNotIn("No module named", output)

    def test_noarg_fallback_without_ecdsa_exits_nonzero(self):
        self._patch_missing()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = analyze_chain.main([])
        self.assertEqual(code, 1)
        self.assertIn("缺少 ecdsa 依赖", buffer.getvalue())

    def test_skip_condition_reflects_backend(self):
        # 谓词必须跟随真实后端：有 ecdsa 为 True，模拟缺失为 False。
        self.assertEqual(_ecdsa_available(),
                         analyze_chain.ECDSA_BACKEND == analyze_chain.BACKEND_PYTHON_ECDSA)
        self._patch_missing()
        self.assertFalse(_ecdsa_available())


@unittest.skipUnless(_ecdsa_available(), ECDSA_REQUIRED)
class ByModelSyntheticTest(unittest.TestCase):
    """合成链剧情：A 的特性在下一纪元被引种、B 的被遗忘（硬编码期望值）。"""

    @classmethod
    def setUpClass(cls):
        cls.data = analyze_chain.build_synthetic_chain()
        cls.by_model = analyze_chain.analyze_by_model(cls.data)

    def models(self):
        return {item["model_id"]: item for item in self.by_model["models"]}

    def test_three_models_and_acceptance_counts(self):
        models = self.models()
        self.assertEqual(sorted(models), ["synthetic-model-a", "synthetic-model-b", "synthetic-model-c"])
        accept_a = models["synthetic-model-a"]["acceptance"]
        accept_b = models["synthetic-model-b"]["acceptance"]
        accept_c = models["synthetic-model-c"]["acceptance"]
        self.assertEqual((accept_a["proposals"], accept_a["accepted_to_main"],
                          accept_a["rejected_to_sleeping_branch"]), (69, 69, 0))
        self.assertEqual(accept_a["acceptance_rate"], 1.0)
        self.assertEqual((accept_b["proposals"], accept_b["accepted_to_main"],
                          accept_b["rejected_to_sleeping_branch"]), (69, 68, 1))
        self.assertAlmostEqual(accept_b["acceptance_rate"], 68 / 69, places=9)
        self.assertEqual((accept_c["proposals"], accept_c["accepted_to_main"],
                          accept_c["rejected_to_sleeping_branch"]), (68, 68, 0))
        self.assertEqual(accept_c["acceptance_rate"], 1.0)
        # 接受数 + 落选数 = 提案数；创世块不计入任何模型
        for model in self.by_model["models"]:
            a = model["acceptance"]
            self.assertEqual(a["proposals"],
                             a["accepted_to_main"] + a["rejected_to_sleeping_branch"])
        self.assertNotIn("genesis", models)

    def test_retention_story_a_reintroduced_b_forgotten(self):
        models = self.models()
        retain_a = models["synthetic-model-a"]["retention"]
        retain_b = models["synthetic-model-b"]["retention"]
        retain_c = models["synthetic-model-c"]["retention"]
        # A：- 首次激活后于纪元 1 被引种（半衰期跨度 1 纪元）
        self.assertEqual(retain_a["features_first_activated"], ["-"])
        self.assertEqual(retain_a["reintroduction_events"], 1)
        self.assertEqual(retain_a["half_life_epochs"], 1.0)
        feat_a = retain_a["features"][0]
        self.assertEqual(feat_a["first_height"], 1)
        self.assertEqual(feat_a["first_epoch"], 0)
        self.assertEqual(feat_a["reintroduction_count"], 1)
        self.assertEqual(feat_a["last_reintroduction_epoch"], 1)
        self.assertEqual(feat_a["span_epochs"], 1)
        self.assertEqual(feat_a["silent_epochs_since_first"], 1)
        # B：list/head/* 全部未再被引种（被遗忘）
        self.assertEqual(retain_b["features_first_activated"], ["*", "head", "list"])
        self.assertEqual(retain_b["reintroduction_events"], 0)
        self.assertEqual(retain_b["half_life_epochs"], 0.0)
        spans_b = {item["primitive"]: item for item in retain_b["features"]}
        self.assertEqual(spans_b["head"]["span_epochs"], 0)
        self.assertEqual(spans_b["head"]["silent_epochs_since_first"], 2)
        self.assertEqual(spans_b["list"]["silent_epochs_since_first"], 2)
        self.assertEqual(spans_b["*"]["first_epoch"], 1)
        self.assertEqual(spans_b["*"]["silent_epochs_since_first"], 1)
        # C：无首次激活特性 -> 半衰期为 None + 样本量警示
        self.assertEqual(retain_c["features_first_activated"], [])
        self.assertIsNone(retain_c["half_life_epochs"])
        self.assertTrue(retain_c["sample_size_warning"])
        # 样本量警示：A/B 各只有 1/3 个特性，均低于阈值
        self.assertTrue(retain_a["sample_size_warning"])
        self.assertTrue(retain_b["sample_size_warning"])

    def test_primitive_preference_and_combination_novelty(self):
        models = self.models()
        pref_a = models["synthetic-model-a"]["primitive_preference"]
        pref_b = models["synthetic-model-b"]["primitive_preference"]
        self.assertEqual(pref_a["activation_blocks"], 2)
        self.assertEqual(pref_a["primitives"], {"-": 2})
        self.assertEqual(pref_b["primitives"], {"*": 1, "head": 1, "list": 1})
        novel_a = models["synthetic-model-a"]["combination_novelty"]
        novel_b = models["synthetic-model-b"]["combination_novelty"]
        novel_c = models["synthetic-model-c"]["combination_novelty"]
        # A 的组合 ("-",) 全局首次出现；B 的 ("head","list") 与 ("*",) 也是全局首次
        self.assertEqual(novel_a["novel_count"], 1)
        self.assertEqual(novel_a["non_novel_count"], 0)
        self.assertTrue(novel_a["combinations_first_activated"][0]["globally_first_seen"])
        self.assertEqual(novel_b["novel_count"], 2)
        self.assertEqual(novel_b["non_novel_count"], 0)
        combos_b = {tuple(item["combination"]): item
                    for item in novel_b["combinations_first_activated"]}
        self.assertIn(("head", "list"), combos_b)
        self.assertIn(("*",), combos_b)
        self.assertEqual(novel_c["combinations_first_activated"], [])
        self.assertEqual(novel_c["novel_count"], 0)

    def test_collaboration_single_identity_per_miner(self):
        collab = self.by_model["collaboration"]
        self.assertEqual(collab["miners_with_multiple_models"], [])
        self.assertEqual(collab["multi_model_miner_count"], 0)
        self.assertEqual(collab["models_used_by_multiple_miners"], [])
        self.assertEqual(collab["multi_miner_model_count"], 0)
        for model in self.by_model["models"]:
            self.assertEqual(model["miner_count"], 1)

    def test_report_json_partition_stable_keys(self):
        report, _ = analyze_chain.build_report(self.data, source="s", source_label="s",
                                               include_by_model=True)
        partition = report["by_model"]
        self.assertEqual(
            sorted(partition),
            ["collaboration", "derived_from", "models", "sample_size_warning_threshold", "scope"],
        )
        self.assertIn("blocks[].poi.model_metadata", partition["derived_from"])
        self.assertTrue(partition["scope"]["genesis_excluded"])
        model_keys = sorted(partition["models"][0])
        self.assertEqual(model_keys, ["acceptance", "combination_novelty", "miner_count",
                                      "miners", "model_id", "primitive_preference", "retention"])
        retention = partition["models"][0]["retention"]
        for key in ("features_first_activated", "feature_count", "reintroduction_events",
                    "half_life_epochs", "mean_span_epochs", "span_epochs_min",
                    "span_epochs_max", "features", "sample_size_warning"):
            self.assertIn(key, retention)
        acceptance = partition["models"][0]["acceptance"]
        for key in ("proposals", "accepted_to_main", "rejected_to_sleeping_branch",
                    "main_chain_blocks", "sleeping_branch_blocks", "acceptance_rate"):
            self.assertIn(key, acceptance)

    def test_console_section_gated_by_flag(self):
        _, text_without = analyze_chain.build_report(self.data, source="s", source_label="s")
        self.assertNotIn("跨 AI 创造力指标", text_without)
        _, text_with = analyze_chain.build_report(self.data, source="s", source_label="s",
                                                  include_by_model=True)
        self.assertIn("跨 AI 创造力指标", text_with)
        self.assertIn("接受率", text_with)
        self.assertIn("半衰期", text_with)
        self.assertIn("组合新颖度", text_with)


class ByModelUnitTest(unittest.TestCase):
    """--by-model 的退化行为与口径细节（最小 JSON 输入，不依赖 ecdsa）。"""

    def _report(self, blocks, **extra):
        data = make_archive(blocks, **extra)
        return analyze_chain.build_report(data, source="test", source_label="test",
                                          include_by_model=True)

    def test_single_model_degenerate_behavior(self):
        branch_blocks = [make_block(4, model_metadata="only-model")]
        report, _ = self._report(
            [make_block(0, tokens=0, model_metadata="genesis"),
             make_block(1, activation=["x"], model_metadata="only-model"),
             make_block(2, activation=["y"], model_metadata="only-model"),
             make_block(3, model_metadata="only-model")],
            sleeping_branches=[{"branch_id": "br-1", "blocks": branch_blocks}],
        )
        models = report["by_model"]["models"]
        self.assertEqual(len(models), 1)
        model = models[0]
        self.assertEqual(model["model_id"], "only-model")
        self.assertEqual(model["acceptance"], {
            "proposals": 4, "accepted_to_main": 3, "rejected_to_sleeping_branch": 1,
            "main_chain_blocks": 3, "sleeping_branch_blocks": 1,
            "acceptance_rate": 0.75,
        })
        # 退化：单模型下留存指标照常给出（样本量警示开启）
        self.assertEqual(model["retention"]["features_first_activated"], ["x", "y"])
        self.assertTrue(model["retention"]["sample_size_warning"])
        self.assertIn("样本量", " | ".join(report["warnings"]))

    def test_missing_model_metadata_groups_to_unnamed(self):
        report, _ = self._report([make_block(0, tokens=0), make_block(1, activation=["a"])])
        models = report["by_model"]["models"]
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["model_id"], "(未标注)")
        self.assertEqual(models[0]["acceptance"]["accepted_to_main"], 1)

    def test_only_genesis_yields_empty_models(self):
        report, _ = self._report([make_block(0, tokens=0, model_metadata="genesis")])
        self.assertEqual(report["by_model"]["models"], [])
        self.assertEqual(report["by_model"]["collaboration"]["multi_model_miner_count"], 0)
        self.assertEqual(report["by_model"]["collaboration"]["multi_miner_model_count"], 0)

    def test_miner_with_multiple_model_identities(self):
        report, _ = self._report([
            make_block(0, tokens=0),
            make_block(1, miner="miner-1", model_metadata="m1"),
            make_block(2, miner="miner-1", model_metadata="m2"),
        ])
        collab = report["by_model"]["collaboration"]
        self.assertEqual(collab["multi_model_miner_count"], 1)
        entry = collab["miners_with_multiple_models"][0]
        self.assertEqual(entry["miner_pubkey_b64"], "miner-1")
        self.assertEqual(entry["models"], ["m1", "m2"])
        # 两个模型各自只挂一名矿工
        model_ids = [m["model_id"] for m in report["by_model"]["models"]]
        self.assertEqual(sorted(model_ids), ["m1", "m2"])
        self.assertEqual(report["by_model"]["models"][0]["miner_count"], 1)

    def test_model_used_by_multiple_miners(self):
        report, _ = self._report([
            make_block(0, tokens=0),
            make_block(1, miner="miner-1", model_metadata="shared"),
            make_block(2, miner="miner-2", model_metadata="shared"),
        ])
        collab = report["by_model"]["collaboration"]
        self.assertEqual(collab["multi_miner_model_count"], 1)
        entry = collab["models_used_by_multiple_miners"][0]
        self.assertEqual(entry["model_id"], "shared")
        self.assertEqual(entry["miner_count"], 2)
        self.assertEqual(sorted(entry["miners"]), ["miner-1", "miner-2"])

    def test_sentinel_zero_leakage_in_by_model(self):
        blocks = [
            make_block(0, tokens=0),
            make_block(1, activation=["alpha"], model_metadata="real-model"),
        ]
        report, text = analyze_chain.build_report(
            make_archive(blocks), source="test", source_label="test", include_by_model=True)
        raw = json.dumps(report, ensure_ascii=False)
        for sentinel in DependencyBoundaryTest.SENTINELS:
            self.assertNotIn(sentinel, raw)
            self.assertNotIn(sentinel, text)
        # 模型身份来自 poi.model_metadata（真实字段），而非被避开的派生字段
        self.assertIn("real-model", raw)
        self.assertIn("blocks[].poi.model_metadata", report["by_model"]["derived_from"])


class GbkConsoleSafetyTest(unittest.TestCase):
    """GBK 控制台安全（线③收口）：中文 Windows 默认 GBK 代码页下 CLI 不崩溃。

    复现方式：subprocess 强制 PYTHONIOENCODING=gbk 运行 CLI（等价于
    GBK 控制台写 stdout 的真实条件），断言 exit 0 且无 codec 崩溃；
    并断言报告正文不含 U+26A0 等 GBK 不可编码字符、--json 文件仍为 UTF-8。
    """

    SCRIPT = os.path.join(os.path.dirname(os.path.abspath(analyze_chain.__file__)),
                          "analyze_chain.py")

    def _run_cli(self, args):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "gbk"
        env.pop("PYTHONUTF8", None)
        return subprocess.run(
            [sys.executable, self.SCRIPT] + args,
            capture_output=True, cwd=os.path.dirname(self.SCRIPT),
            env=env)

    @staticmethod
    def _gbk_encodable(text: str) -> bool:
        try:
            text.encode("gbk")
            return True
        except UnicodeEncodeError:
            return False

    @unittest.skipUnless(_ecdsa_available(), ECDSA_REQUIRED)
    def test_synthetic_by_model_exits_zero_under_gbk_env(self):
        result = self._run_cli(["--synthetic", "--by-model"])
        self.assertEqual(result.returncode, 0)
        # 修复前这里会崩在 '"gbk" codec can't encode character' 上
        self.assertNotIn(b"codec can't encode", result.stderr)
        self.assertNotIn("codec can't encode", result.stderr.decode("utf-8", errors="replace"))
        out = result.stdout.decode("utf-8", errors="replace")
        self.assertIn("synthetic-model-a", out)
        self.assertIn("留存率", out)

    @unittest.skipUnless(_ecdsa_available(), ECDSA_REQUIRED)
    def test_report_has_no_non_gbk_characters(self):
        result = self._run_cli(["--synthetic", "--by-model"])
        self.assertEqual(result.returncode, 0)
        out = result.stdout.decode("utf-8", errors="replace")
        # U+26A0（⚠）等装饰字符在 GBK 下无法编码，正文必须改用 [警示]
        self.assertNotIn("\u26a0", out)
        self.assertIn("[警示]", out)
        # 正则扫：正文中所有字符都能被 GBK 编码（中文本身在 GBK 内，允许）
        bad = [repr(ch) for ch in out if not self._gbk_encodable(ch)]
        self.assertEqual(bad, [])

    def test_json_output_stays_utf8_under_gbk_env(self):
        # 最小存档 + --json：不依赖 ecdsa，GBK 环境也要能写出标准 UTF-8 JSON
        path = write_tmp(make_archive([make_block(0, tokens=0, model_metadata="genesis"),
                                       make_block(1, activation=["a"], model_metadata="manual-mock")]))
        with tempfile.TemporaryDirectory(prefix="analyze_gbk_json_") as tmpdir:
            out = os.path.join(tmpdir, "metrics.json")
            result = self._run_cli([path, "--by-model", "--json", out])
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
            self.assertTrue(os.path.exists(out))
            # 必须能用 UTF-8 直接读回并解析（GBK 编码的伪 UTF-8 会在这里解码失败/乱码）
            with open(out, "r", encoding="utf-8") as handle:
                doc = json.load(handle)
            self.assertIn("by_model", doc)
            self.assertEqual(doc["by_model"]["models"][0]["model_id"], "manual-mock")
            self.assertIn("跨 AI 创造力指标", result.stdout.decode("utf-8", errors="replace"))

    def test_main_tolerates_stringio_stdout(self):
        # 既有测试用 redirect_stdout(StringIO()) 调 main：StringIO 无 reconfigure，
        # 入口的编码容错必须优雅降级（AttributeError 分支），不能把测试模式打破
        path = write_tmp(make_archive([make_block(0, tokens=0), make_block(1, activation=["a"])]))
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = analyze_chain.main([path, "--compact"])
        self.assertEqual(code, 0)
        self.assertIn("高度", buffer.getvalue())


@unittest.skipUnless(_ecdsa_available(), ECDSA_REQUIRED)
class PublicMetricsExportTest(unittest.TestCase):
    """`export_public.py --metrics` 的落盘契约与两条红线（私钥剥离 / 模型身份）。

    全部走进程内调用 export_public._cli，不起 HTTP 服务；输入存档与输出文件
    一律落在系统临时目录，不碰项目 data/，也不在仓库里留任何探针文件。
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="stratum_metrics_test_")
        self.archive = os.path.join(self._tmpdir, "archive.json")
        self.out_state = os.path.join(self._tmpdir, "chain_state.json")
        self.out_metrics = os.path.join(self._tmpdir, "metrics.json")

    def tearDown(self):
        for name in os.listdir(self._tmpdir):
            try:
                os.remove(os.path.join(self._tmpdir, name))
            except OSError:
                pass
        try:
            os.rmdir(self._tmpdir)
        except OSError:
            pass

    def _run_cli(self, *extra):
        """调用导出脚本，返回 (退出码, 标准输出)。"""
        import export_public
        buffer = io.StringIO()
        argv = ["--in", self.archive, "--out", self.out_state] + list(extra)
        with contextlib.redirect_stdout(buffer):
            code = export_public._cli(argv)
        return code, buffer.getvalue()

    def _write_min_archive(self):
        """写一份真实有效（可被 persistence.rebuild_store 解析）的 chain-v2 存档。

        用 server.build_server_state(fresh=True) 生成的链含完整 proposal/signature，
        api_chain_state 可正常序列化；所有区块 model_metadata 为 "manual-mock"。
        """
        import server as srv
        srv.build_server_state(fresh=True, persist_path=self.archive)

    # ---- 用例 1：--metrics 输出结构稳定（顶层键名与契约常量一致）----
    def test_metrics_top_level_keys_match_contract(self):
        self._write_min_archive()
        code, text = self._run_cli("--metrics", self.out_metrics)
        self.assertEqual(code, 0, text)
        with open(self.out_metrics, encoding="utf-8") as handle:
            metrics = json.load(handle)
        self.assertEqual(tuple(sorted(metrics.keys())),
                         tuple(sorted(analyze_chain.PUBLIC_METRICS_KEYS)))
        self.assertEqual(metrics["schema_version"],
                         analyze_chain.METRICS_SCHEMA_VERSION)
        self.assertTrue(metrics["readonly"])
        self.assertEqual(metrics["generated_by"], "export_public.py --metrics")
        # 分析器自身口径版本仍独立存在，不因公开契约而变
        self.assertEqual(metrics["schema"]["schema_version"],
                         analyze_chain.ANALYZER_SCHEMA_VERSION)

    # ---- 用例 2：两份输出的链高必须一致 ----
    def test_metrics_chain_height_matches_chain_state(self):
        self._write_min_archive()
        code, text = self._run_cli("--metrics", self.out_metrics)
        self.assertEqual(code, 0, text)
        with open(self.out_metrics, encoding="utf-8") as handle:
            metrics = json.load(handle)
        with open(self.out_state, encoding="utf-8") as handle:
            state = json.load(handle)
        self.assertEqual(metrics["chain_height"], state["chain_height"])
        self.assertGreaterEqual(metrics["chain_height"], 1)

    # ---- 用例 3（红线 a 回归）：两个输出文件都零私钥 ----
    def test_both_outputs_leak_no_private_key(self):
        self._write_min_archive()
        code, text = self._run_cli("--metrics", self.out_metrics)
        self.assertEqual(code, 0, text)
        for path in (self.out_state, self.out_metrics):
            with open(path, encoding="utf-8") as handle:
                content = handle.read()
            self.assertNotRegex(content, r"private[\s_\-]*key",
                                f"{os.path.basename(path)} 出现私钥字段痕迹")
            import export_public
            self.assertIsNone(export_public._SECRET_RE.search(content))
        # 矿工段仍保留公开字段
        with open(self.out_state, encoding="utf-8") as handle:
            state = json.load(handle)
        for miner in state.get("miners", []):
            self.assertIn("miner_pubkey_b64", miner)

    # ---- 用例 4（红线 b）：公开快照必须含 model_metadata ----
    def test_public_snapshot_carries_model_metadata(self):
        self._write_min_archive()
        code, text = self._run_cli("--metrics", self.out_metrics)
        self.assertEqual(code, 0, text)
        with open(self.out_state, encoding="utf-8") as handle:
            state = json.load(handle)
        for block in state["blocks"]:
            self.assertIn("model_metadata", block)
        with open(self.out_metrics, encoding="utf-8") as handle:
            metrics = json.load(handle)
        models = metrics["by_model"]["models"]
        self.assertTrue(models, "by_model 分区不得为空")
        self.assertTrue(all(str(m.get("model_id") or "").strip() for m in models))

    # ---- 用例 5（红线 b 反向）：缺 model_metadata 必须拒绝写出 ----
    def test_missing_model_metadata_is_rejected(self):
        """模拟「未升级的导出路径」：/chain-state 不带 model_metadata → 两个文件都不写出。"""
        import server as srv
        self._write_min_archive()
        original = srv.api_chain_state

        def stripped(state):
            payload = original(state)
            for block in payload.get("blocks", []):
                block.pop("model_metadata", None)
            return payload

        srv.api_chain_state = stripped
        try:
            code, text = self._run_cli("--metrics", self.out_metrics)
        finally:
            srv.api_chain_state = original
        self.assertEqual(code, 1)
        self.assertIn("模型身份自检未通过", text)
        self.assertFalse(os.path.exists(self.out_metrics), "断言失败时不得产出文件")
        self.assertFalse(os.path.exists(self.out_state), "断言失败时不得产出文件")

    # ---- 用例 6：断言函数本身对 by_model 分区为空的情形也拒绝 ----
    def test_assert_model_identity_rejects_empty_partition(self):
        import export_public
        payload = {"blocks": [{"height": 0, "model_metadata": "genesis"}]}
        with self.assertRaises(export_public.ExportError) as ctx:
            export_public.assert_model_identity(payload, {"by_model": {"models": []}})
        self.assertIn("模型身份自检未通过", str(ctx.exception))
        with self.assertRaises(export_public.ExportError):
            export_public.assert_model_identity(
                payload, {"by_model": {"models": [{"model_id": "  "}]}})
        with self.assertRaises(export_public.ExportError):
            export_public.assert_model_identity({"blocks": []}, {"by_model": {}})
        # 正例：不抛异常
        export_public.assert_model_identity(
            payload, {"by_model": {"models": [{"model_id": "manual-mock"}]}})

    # ---- 用例 7：不指定 --metrics 时不产出指标文件（既有行为不变）----
    def test_without_metrics_flag_no_metrics_file(self):
        self._write_min_archive()
        with open(self.archive, encoding="utf-8") as handle:
            before = handle.read()
        code, text = self._run_cli()
        self.assertEqual(code, 0, text)
        self.assertTrue(os.path.exists(self.out_state))
        self.assertFalse(os.path.exists(self.out_metrics))
        with open(self.archive, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), before, "源存档不得被修改")

    # ---- 用例 7：结构化提案构造的两个模型身份 → by_model 正确分组 ----
    def test_by_model_groups_two_structured_proposal_models(self):
        import server as srv
        state = srv.build_server_state(fresh=True, persist_path=self.archive)
        base_height = state.store.height
        pubkey = srv.b64e(sorted(state.registry.miners)[0])

        plan = [
            ("self-written-tail", "(head (tail (list 1 2 3)))",
             "(head (tail (list 1 2 3)))", 2, ["tail", "head", "list"], "model-alpha"),
            ("self-written-eq", "(eq (% 9 4) 1)",
             "(eq (% 9 4) 1)", 1, ["eq", "%", "//"], "model-beta"),
        ]
        for feature_id, demo, program, expected, activation, model in plan:
            response = srv.api_propose_structured(state, {
                "feature_id": feature_id,
                "specification": f"{model} 自写的演示",
                "demo_code": demo,
                "test_cases": [{"program": program, "expected": expected}],
                "activation": activation,
                "model_metadata": model,
                "miner_pubkey_b64": pubkey,
            })
            self.assertTrue(response["success"], f"{model} 上链失败：{response}")

        code, text = self._run_cli("--metrics", self.out_metrics)
        self.assertEqual(code, 0, text)

        with open(self.out_metrics, encoding="utf-8") as handle:
            metrics = json.load(handle)
        with open(self.out_state, encoding="utf-8") as handle:
            state_json = json.load(handle)

        # 链高：预沉积 + 2 个新提案
        self.assertEqual(state_json["chain_height"], base_height + 2)
        self.assertEqual(metrics["chain_height"], state_json["chain_height"])

        model_ids = {m["model_id"] for m in metrics["by_model"]["models"]}
        self.assertIn("model-alpha", model_ids)
        self.assertIn("model-beta", model_ids)
        # 预沉积链的既有身份仍在，不得被覆盖
        self.assertIn("manual-mock", model_ids)

        # 新块在 chain_state 里的 model_metadata 与提交值一致
        on_chain = {b["feature_name"]: b.get("model_metadata")
                    for b in state_json["blocks"]}
        self.assertEqual(on_chain.get("self-written-tail"), "model-alpha")
        self.assertEqual(on_chain.get("self-written-eq"), "model-beta")

        # 分组计数：每个新模型各 1 块主链提案
        counts = {m["model_id"]: m["acceptance"]["main_chain_blocks"]
                  for m in metrics["by_model"]["models"]}
        self.assertEqual(counts.get("model-alpha"), 1)
        self.assertEqual(counts.get("model-beta"), 1)


if __name__ == "__main__":
    unittest.main()
