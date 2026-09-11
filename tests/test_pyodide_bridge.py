"""Pyodide 浏览器内核桥的本地等价冒烟测试（卡 4/4）。

说明：浏览器内的 Pyodide 运行环境无法用 unittest 直接驱动，因此这里在「本机真实
Python 解释器 + 已安装 ecdsa」上，对 web/py_sandbox.py 暴露的、与 bridge.js 一一对应的
Python 入口做冒烟测试。这些函数正是 Pyodide 加载后 JS 桥会调用的同一份逻辑，因此本
测试等价于浏览器内核的入口级验证（浏览器内的「真实签名 / WASM / 首屏耗时」由人工/Playwright
实跑，见 web/README.md 与回传报告）。

本测试只新增文件，不修改任何既有测试；运行方式与全量套件一致：
    python -m unittest discover -s tests -p "test_*.py"
"""

import json
import os
import sys
import unittest

# 让 web 包（namespace package）可被导入：把仓库根加入搜索路径。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import web.py_sandbox as sandbox  # noqa: E402


class PyodideBridgeSmokeTest(unittest.TestCase):
    def setUp(self):
        # 每次用例使用干净的会话（重置链与内存密钥）。
        json.loads(sandbox.py_reset(102))

    def test_init_seeds_103_blocks(self):
        out = json.loads(sandbox.py_init(102))
        self.assertEqual(out["chain_height"], 102)
        self.assertEqual(out["mode"], "browser-kernel")
        st = json.loads(sandbox.py_chain_state())
        self.assertEqual(len(st["blocks"]), 103)
        # 种子块沿用与后端一致的 manual-mock 模型身份
        self.assertEqual(st["blocks"][1]["model_metadata"], "manual-mock")
        # 语言快照字段存在（前端语言地层依赖）
        self.assertIsNotNone(st["blocks"][1]["language_features"])

    def test_chain_state_view_has_required_keys(self):
        st = json.loads(sandbox.py_chain_state())
        for key in ("chain_height", "blocks", "epochs", "sleeping_branches", "miners"):
            self.assertIn(key, st)
        self.assertIn("current_active_features", st)
        self.assertIn("cumulative_active_features", st)

    def test_structured_propose_subtraction_then_eval(self):
        payload = {
            "feature_id": "sub-demo",
            "specification": "演示减法原语",
            "demo_code": "(- 10 3)",
            "test_cases": [{"program": "(- 10 3)", "expected": 7}],
            "activation": ["-"],
            "model_metadata": "browser-kernel",
        }
        resp = json.loads(sandbox.py_propose_structured(json.dumps(payload)))
        self.assertTrue(resp["success"], resp)
        self.assertEqual(resp["chain_height"], 103)
        self.assertEqual(resp["model_metadata"], "browser-kernel")
        # 新区块真实落链
        st = json.loads(sandbox.py_chain_state())
        self.assertEqual(len(st["blocks"]), 104)
        # 沙箱真实执行 (- 10 3) == 7（验证语言演化确实生效）
        ev = json.loads(sandbox.py_eval(json.dumps({"code": "(- 10 3)"})))
        self.assertTrue(ev["ok"], ev)
        self.assertEqual(ev["value"], 7)

    def test_language_evolution_after_activation(self):
        # 激活 "-"
        json.loads(sandbox.py_propose_structured(json.dumps({
            "feature_id": "sub", "specification": "s", "demo_code": "(- 10 3)",
            "test_cases": [{"program": "(- 10 3)", "expected": 7}],
            "activation": ["-"], "model_metadata": "browser-kernel"})))
        # 此后普通区块（无 activation）引用 "-" 也应通过（语言已演化）
        ok = json.loads(sandbox.py_propose_structured(json.dumps({
            "feature_id": "x", "specification": "y", "demo_code": "(- 1 1)",
            "test_cases": [{"program": "(- 1 1)", "expected": 0}],
            "activation": [], "model_metadata": "browser-kernel"})))
        self.assertTrue(ok["success"], ok)

    def test_reject_when_feature_not_inoculated(self):
        # 全新链上 "*" 尚未引种：沙箱运行失败 -> 进入休眠分支，不写入主链
        bad = {
            "feature_id": "x", "specification": "y", "demo_code": "(* 3 4)",
            "test_cases": [{"program": "(* 3 4)", "expected": 12}],
            "activation": [], "model_metadata": "browser-kernel",
        }
        rb = json.loads(sandbox.py_propose_structured(json.dumps(bad)))
        self.assertFalse(rb["success"])
        self.assertTrue(rb["is_sleeping_branch"])
        st = json.loads(sandbox.py_chain_state())
        self.assertEqual(len(st["blocks"]), 103)  # 主链未增长

    def test_propose_text_maps_and_validates(self):
        r = json.loads(sandbox.py_propose_text(json.dumps({
            "text": "增加一个乘法原语", "model_metadata": "browser-kernel"})))
        self.assertTrue(r["success"], r)

    def test_export_import_roundtrip_no_private_keys(self):
        # 先提案，改变链状态
        json.loads(sandbox.py_propose_structured(json.dumps({
            "feature_id": "sub", "specification": "s", "demo_code": "(- 10 3)",
            "test_cases": [{"program": "(- 10 3)", "expected": 7}],
            "activation": ["-"], "model_metadata": "browser-kernel"})))
        arc = sandbox.py_export_archive()
        arc_obj = json.loads(arc)
        # 红线：导出存档绝不包含矿工私钥
        self.assertEqual(arc_obj["format_version"], "chain-v2")
        self.assertNotIn("miners", arc_obj)
        # 导入复原
        before = len(json.loads(sandbox.py_chain_state())["blocks"])
        imp = json.loads(sandbox.py_import_archive(arc))
        self.assertTrue(imp["success"])
        after = len(json.loads(sandbox.py_chain_state())["blocks"])
        self.assertEqual(before, after)

    def test_promote_is_stubbed(self):
        pr = json.loads(sandbox.py_promote(json.dumps({"head_hash": "abc"})))
        self.assertEqual(pr["status"], "not_implemented")


if __name__ == "__main__":
    unittest.main()
