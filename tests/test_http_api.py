"""StratumGenesis HTTP API 单元测试。

测试会自行启动 server.py 的服务实例（绑定 127.0.0.1:28417）。
运行测试前请先停止正在运行的服务，否则端口冲突会报错。
"""

import json
import threading
import unittest
import urllib.request
import urllib.error

import server as srv

BASE = "http://127.0.0.1:28417"


def http_json(path: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


class HttpApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = srv.create_server()
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def test_chain_state_returns_genesis_miners_and_epochs(self):
        status, state = http_json("/chain-state")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(state["chain_height"], 102)
        blocks = state["blocks"]
        self.assertEqual(blocks[0]["height"], 0)
        self.assertEqual(blocks[0]["feature_name"], "novscript-genesis-kernel")
        self.assertTrue(state["miners"])
        self.assertEqual(len(state["miners"]), 3)
        epochs = {e["epoch_number"]: e for e in state["epochs"]}
        self.assertIn(0, epochs)
        self.assertTrue(epochs[0]["archived"])
        self.assertIn(1, epochs)
        self.assertFalse(epochs[1]["archived"])
        # v0.3 追加 model_metadata（模型身份，来源 blocks[].poi.model_metadata）。
        required_fields = {"height", "epoch", "miner_label", "miner_pubkey_b64", "feature_name",
                           "description", "demo_code", "test_cases", "block_hash_b64",
                           "model_metadata"}
        self.assertTrue(required_fields.issubset(blocks[1].keys()))

    def test_propose_valid_proposal_is_mined_to_main_chain(self):
        _, state = http_json("/chain-state")
        miner = state["miners"][0]
        before = state["chain_height"]
        status, resp = http_json("/propose", "POST", {
            "proposal_text": "函数增量扩展",
            "miner_pubkey_b64": miner["miner_pubkey_b64"],
        })
        self.assertEqual(status, 200)
        self.assertTrue(resp["success"], resp)
        self.assertFalse(resp["is_sleeping_branch"])
        self.assertIsNotNone(resp["block_hash_b64"])
        self.assertEqual(resp["chain_height"], before + 1)
        _, after = http_json("/chain-state")
        self.assertEqual(after["chain_height"], before + 1)
        tip = after["blocks"][-1]
        self.assertEqual(tip["description"], "函数增量扩展")
        self.assertEqual(tip["height"], before + 1)

    def test_propose_kernel_conflict_goes_to_sleeping_branch(self):
        _, state = http_json("/chain-state")
        miner = state["miners"][1]
        before = state["chain_height"]
        status, resp = http_json("/propose", "POST", {
            "proposal_text": "修改创世内核并启用严格求值",
            "miner_pubkey_b64": miner["miner_pubkey_b64"],
        })
        self.assertEqual(status, 200)
        self.assertFalse(resp["success"])
        self.assertTrue(resp["is_sleeping_branch"])
        self.assertIsNotNone(resp["block_hash_b64"])
        self.assertEqual(resp["chain_height"], before)
        _, after = http_json("/chain-state")
        self.assertEqual(after["chain_height"], before)
        self.assertTrue(any(s["reason"].startswith("kernel_compatibility") for s in after["sleeping_branches"]))

    def test_propose_unknown_miner_rejected(self):
        _, state = http_json("/chain-state")
        before = state["chain_height"]
        status, resp = http_json("/propose", "POST", {
            "proposal_text": "合法提案文本",
            "miner_pubkey_b64": "AAAAAAAAAAAAAAAAAAAA==",
        })
        self.assertEqual(status, 200)
        self.assertFalse(resp["success"])
        self.assertEqual(resp["chain_height"], before)

    def test_eval_novscript_valid_code(self):
        status, resp = http_json("/eval-novscript", "POST", {"code": "(+ 1 2)"})
        self.assertEqual(status, 200)
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["value"], 3)
        self.assertIsNone(resp["error_type"])

    def test_eval_novscript_syntax_error(self):
        status, resp = http_json("/eval-novscript", "POST", {"code": "(+ 1 2"})
        self.assertEqual(status, 200)
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["error_type"], "语法错误")

    def test_eval_novscript_unbound_name(self):
        status, resp = http_json("/eval-novscript", "POST", {"code": "missing-name"})
        self.assertEqual(status, 200)
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["error_type"], "未绑定名称")

    def test_index_html_is_served(self):
        request = urllib.request.Request(BASE + "/index.html", method="GET")
        with urllib.request.urlopen(request, timeout=10) as response:
            self.assertEqual(response.status, 200)
            self.assertTrue(response.headers.get("Content-Type", "").startswith("text/html"))
            payload = response.read()
        self.assertTrue(b"<!DOCTYPE html" in payload)


if __name__ == "__main__":
    unittest.main()
