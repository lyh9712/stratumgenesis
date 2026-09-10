"""v0.3 结构化提案通道（POST /propose-structured）与模型身份贯通的测试。

端口纪律：本文件**不使用** 127.0.0.1:28417 端口令牌（那是既有
tests/test_http_api.py 的独占资源）。这里在 setUpClass 里临时把 srv.PORT 置 0，
让操作系统分配空闲端口，创建完立即还原，用完即关，杜绝残留进程。

覆盖：
1. 结构化提案成功上链（自写 demo_code / test_cases / activation）；
2. model_metadata 贯通 canonical_bytes、存档 round-trip、/chain-state、/branches；
3. 入参白名单与长度上限的中文结构化错误码；
4. 既有 /propose 文本通道行为零回归（含响应字段集合）；
5. STRATUM_HOST：未设置时默认仍绑 127.0.0.1，设置时才覆盖。
"""

import importlib
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import persistence
import server as srv


def _request(base: str, path: str, method: str = "GET", raw: bytes | None = None):
    request = urllib.request.Request(base + path, data=raw, method=method)
    if raw is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        payload = error.read().decode("utf-8")
        try:
            return error.code, json.loads(payload)
        except Exception:
            return error.code, {}


class StructuredProposalHttpTests(unittest.TestCase):
    """共享一条 102 块预沉积链的服务实例；各用例用互不冲突的 activation 原语，
    使执行顺序（unittest 按方法名字母序）不影响结果。"""

    @classmethod
    def setUpClass(cls):
        cls.state = srv.ServerState()   # persist_path=None：不写盘，不污染 data/
        original_port = srv.PORT
        srv.PORT = 0                    # 让 OS 分配空闲端口（避开 28417 端口令牌）
        try:
            cls.httpd = srv.create_server(cls.state)
        finally:
            srv.PORT = original_port
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    # --- helpers ---------------------------------------------------------
    def get(self, path):
        return _request(self.base, path, "GET")

    def post(self, path, body: dict):
        return _request(self.base, path, "POST", json.dumps(body).encode("utf-8"))

    def post_raw(self, path, raw: bytes):
        return _request(self.base, path, "POST", raw)

    def miner_pubkey(self) -> str:
        _, state = self.get("/chain-state")
        return state["miners"][0]["miner_pubkey_b64"]

    def structured_body(self, **overrides) -> dict:
        body = {
            "feature_id": "self-written-mul",
            "specification": "我自己写的乘法原语演示",
            "demo_code": "(* 3 4)",
            "test_cases": [{"program": "(* 3 4)", "expected": 12}],
            "activation": ["*"],
            "model_metadata": "model-alpha-1",
            "miner_pubkey_b64": self.miner_pubkey(),
        }
        body.update(overrides)
        return body

    # --- 1. 成功路径 ------------------------------------------------------
    def test_structured_proposal_is_mined_with_self_written_demo(self):
        _, before = self.get("/chain-state")
        status, resp = self.post("/propose-structured", self.structured_body())
        self.assertEqual(status, 200)
        self.assertTrue(resp["success"], resp)
        self.assertFalse(resp["is_sleeping_branch"])
        self.assertEqual(resp["chain_height"], before["chain_height"] + 1)
        self.assertEqual(resp["model_metadata"], "model-alpha-1")
        self.assertEqual(resp["error_code"], None)

        _, after = self.get("/chain-state")
        tip = after["blocks"][-1]
        self.assertEqual(tip["height"], before["chain_height"] + 1)
        # 服务端不得改写提案内容：feature_id / demo_code / test_cases 原样上链
        self.assertEqual(tip["feature_name"], "self-written-mul")
        self.assertEqual(tip["demo_code"], "(* 3 4)")
        self.assertEqual(tip["test_cases"], [{"program": "(* 3 4)", "expected": 12}])
        self.assertEqual(tip["activation"], ["*"])
        # 模型身份贯通到 API
        self.assertEqual(tip["model_metadata"], "model-alpha-1")

    def test_model_metadata_defaults_to_unspecified_when_absent(self):
        body = self.structured_body(
            feature_id="self-written-div",
            demo_code="(// 9 2)",
            test_cases=[{"program": "(// 9 2)", "expected": 4}],
            activation=["//"],
        )
        body.pop("model_metadata")
        status, resp = self.post("/propose-structured", body)
        self.assertEqual(status, 200)
        self.assertTrue(resp["success"], resp)
        self.assertEqual(resp["model_metadata"], "unspecified")

    def test_empty_model_metadata_also_falls_back_to_unspecified(self):
        body = self.structured_body(
            feature_id="self-written-length",
            demo_code="(length (list 1 2 3))",
            test_cases=[{"program": "(length (list 1 2 3))", "expected": 3}],
            activation=["length", "list"],
            model_metadata="",
        )
        status, resp = self.post("/propose-structured", body)
        self.assertEqual(status, 200)
        self.assertTrue(resp["success"], resp)
        self.assertEqual(resp["model_metadata"], "unspecified")

    # --- 2. 模型身份贯通：canonical / 存档 / API ---------------------------
    def test_model_metadata_reaches_canonical_bytes_and_archive_roundtrip(self):
        body = self.structured_body(
            feature_id="self-written-mod",
            demo_code="(% 7 3)",
            test_cases=[{"program": "(% 7 3)", "expected": 1}],
            activation=["%"],
            model_metadata="roundtrip-model.v2",
        )
        status, resp = self.post("/propose-structured", body)
        self.assertEqual(status, 200)
        self.assertTrue(resp["success"], resp)

        block = self.state.store.tip
        self.assertEqual(block.poi.model_metadata, "roundtrip-model.v2")
        # (a) canonical_bytes：签名与哈希共用的序列化里必须含该字段
        canonical = json.loads(block.canonical_bytes().decode("utf-8"))
        self.assertEqual(canonical["poi"]["model_metadata"], "roundtrip-model.v2")

        # (b) 存档 save_state -> load_state round-trip（临时目录，不落仓库）
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = os.path.join(tmpdir, "roundtrip.json")
            persistence.save_state(
                archive, self.state.store, self.state.registry.miners,
                dict(self.state.rejection_reasons),
            )
            loaded = persistence.load_state(archive)
        archived = [item for item in loaded["blocks"] if item["height"] == block.height]
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0]["poi"]["model_metadata"], "roundtrip-model.v2")

    def test_chain_state_and_branches_both_expose_model_metadata(self):
        # 先制造一个休眠分支块（demo 语法错误 -> 第 4 步解析被拒 -> 入休眠分支）
        self.post("/propose-structured", self.structured_body(
            feature_id="broken-demo",
            demo_code="(+ 1",
            test_cases=[],
            activation=[],
            model_metadata="broken-model",
        ))
        status, state = self.get("/chain-state")
        self.assertEqual(status, 200)
        for block in state["blocks"]:
            self.assertIn("model_metadata", block)
        self.assertEqual(state["blocks"][0]["model_metadata"], "genesis")
        # 既有字段不得改名或删除
        self.assertIn("feature_name", state["blocks"][0])
        self.assertIn("activation", state["blocks"][0])
        self.assertIn("current_active_features", state)

        status, branches = self.get("/branches")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(branches["sleeping_count"], 1)
        items = [item for group in branches["branches"] for item in group["blocks"]]
        self.assertTrue(items)
        for item in items:
            self.assertIn("model_metadata", item)
        self.assertIn("broken-model", [item["model_metadata"] for item in items])

    # --- 3. 入参校验与中文错误码 ------------------------------------------
    def test_model_metadata_rejects_space(self):
        status, resp = self.post("/propose-structured",
                                 self.structured_body(model_metadata="bad model"))
        self.assertEqual(status, 200)
        self.assertFalse(resp["success"])
        self.assertEqual(resp["error_code"], "INVALID_MODEL_METADATA")

    def test_model_metadata_rejects_too_long(self):
        status, resp = self.post("/propose-structured",
                                 self.structured_body(model_metadata="a" * 65))
        self.assertEqual(status, 200)
        self.assertEqual(resp["error_code"], "INVALID_MODEL_METADATA")
        self.assertIn("64", resp["reason"])

    def test_model_metadata_rejects_non_ascii(self):
        status, resp = self.post("/propose-structured",
                                 self.structured_body(model_metadata="模型甲"))
        self.assertEqual(status, 200)
        self.assertEqual(resp["error_code"], "INVALID_MODEL_METADATA")

    def test_demo_code_too_long_rejected(self):
        status, resp = self.post("/propose-structured",
                                 self.structured_body(demo_code="(+ 1 " + "0" * 2048 + ")"))
        self.assertEqual(status, 200)
        self.assertEqual(resp["error_code"], "PAYLOAD_TOO_LARGE")
        self.assertIn("demo_code", resp["reason"])

    def test_too_many_test_cases_rejected(self):
        cases = [{"program": "(+ 1 1)", "expected": 2} for _ in range(17)]
        status, resp = self.post("/propose-structured",
                                 self.structured_body(test_cases=cases))
        self.assertEqual(status, 200)
        self.assertEqual(resp["error_code"], "PAYLOAD_TOO_LARGE")
        self.assertIn("16", resp["reason"])

    def test_test_case_program_too_long_rejected(self):
        cases = [{"program": "(+ 1 " + "0" * 2048 + ")", "expected": 1}]
        status, resp = self.post("/propose-structured",
                                 self.structured_body(test_cases=cases))
        self.assertEqual(status, 200)
        self.assertEqual(resp["error_code"], "PAYLOAD_TOO_LARGE")
        self.assertIn("test_cases[0]", resp["reason"])

    def test_unknown_activation_name_rejected(self):
        status, resp = self.post("/propose-structured",
                                 self.structured_body(activation=["not-a-primitive"]))
        self.assertEqual(status, 200)
        self.assertEqual(resp["error_code"], "UNKNOWN_FEATURE")
        self.assertIn("BUILTIN_POOL", resp["reason"])

    def test_duplicate_activation_name_rejected(self):
        status, resp = self.post("/propose-structured",
                                 self.structured_body(activation=["gt", "gt"],
                                                      demo_code="(gt 3 2)",
                                                      test_cases=[{"program": "(gt 3 2)",
                                                                   "expected": 1}]))
        self.assertEqual(status, 200)
        self.assertEqual(resp["error_code"], "DUPLICATE_ACTIVATION")

    def test_missing_required_fields_rejected(self):
        for missing in ("feature_id", "specification", "demo_code", "test_cases",
                        "miner_pubkey_b64"):
            body = self.structured_body()
            body.pop(missing)
            status, resp = self.post("/propose-structured", body)
            self.assertEqual(status, 200, missing)
            self.assertFalse(resp["success"], missing)
            self.assertEqual(resp["error_code"], "MISSING_FIELD", missing)
            self.assertIsNone(resp["block_hash_b64"], missing)

    def test_test_case_without_expected_rejected(self):
        status, resp = self.post("/propose-structured",
                                 self.structured_body(test_cases=[{"program": "(+ 1 1)"}]))
        self.assertEqual(status, 200)
        self.assertEqual(resp["error_code"], "MISSING_FIELD")
        self.assertIn("expected", resp["reason"])

    def test_unknown_miner_rejected(self):
        status, resp = self.post("/propose-structured",
                                 self.structured_body(miner_pubkey_b64="AAAAAAAAAAAAAAAAAAAA=="))
        self.assertEqual(status, 200)
        self.assertEqual(resp["error_code"], "UNKNOWN_MINER")

    def test_oversized_request_body_rejected(self):
        huge = json.dumps(self.structured_body(
            specification="x" * (300 * 1024))).encode("utf-8")
        status, resp = self.post_raw("/propose-structured", huge)
        self.assertEqual(status, 200)
        self.assertEqual(resp["error_code"], "PAYLOAD_TOO_LARGE")
        self.assertIn("请求体过大", resp["reason"])

    # --- 4. 既有文本通道零回归 --------------------------------------------
    def test_legacy_text_propose_behaviour_unchanged(self):
        _, before = self.get("/chain-state")
        miner = before["miners"][0]["miner_pubkey_b64"]
        status, resp = self.post("/propose", {"proposal_text": "减法", "miner_pubkey_b64": miner})
        self.assertEqual(status, 200)
        self.assertTrue(resp["success"], resp)
        self.assertEqual(resp["chain_height"], before["chain_height"] + 1)
        # v0.2 契约：响应字段集合保持不变（不得混入 error_code / model_metadata）
        self.assertEqual(
            set(resp),
            {"success", "reason", "block_hash_b64", "is_sleeping_branch", "chain_height"},
        )
        _, after = self.get("/chain-state")
        tip = after["blocks"][-1]
        self.assertEqual(tip["description"], "减法")
        self.assertEqual(tip["activation"], ["-"])
        # 文本通道的模型身份仍是既有硬编码值，未因本次改动而改变
        self.assertEqual(tip["model_metadata"], "manual-mock")

    def test_legacy_text_propose_kernel_conflict_still_sleeps(self):
        _, before = self.get("/chain-state")
        miner = before["miners"][1]["miner_pubkey_b64"]
        status, resp = self.post("/propose", {
            "proposal_text": "修改创世内核并启用严格求值",
            "miner_pubkey_b64": miner,
        })
        self.assertEqual(status, 200)
        self.assertFalse(resp["success"])
        self.assertTrue(resp["is_sleeping_branch"])
        self.assertEqual(resp["chain_height"], before["chain_height"])


class StratumHostBindingTests(unittest.TestCase):
    """STRATUM_HOST：默认行为必须完全不变（仍绑 127.0.0.1）。"""

    def test_default_host_is_loopback_when_env_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("STRATUM_HOST", None)
            try:
                self.assertEqual(importlib.reload(srv).HOST, "127.0.0.1")
            finally:
                importlib.reload(srv)   # 还原模块状态，避免影响其他用例

    def test_stratum_host_env_overrides_default(self):
        try:
            with patch.dict(os.environ, {"STRATUM_HOST": "127.0.0.2"}):
                self.assertEqual(importlib.reload(srv).HOST, "127.0.0.2")
        finally:
            importlib.reload(srv)
        self.assertEqual(srv.HOST, "127.0.0.1")

    def test_server_actually_binds_loopback_by_default(self):
        original_port = srv.PORT
        srv.PORT = 0                     # OS 分配端口，不占用 28417 端口令牌
        try:
            httpd = srv.create_server(srv.ServerState())
        finally:
            srv.PORT = original_port
        try:
            self.assertEqual(httpd.server_address[0], "127.0.0.1")
        finally:
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
