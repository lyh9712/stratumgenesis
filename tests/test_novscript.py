"""NovScript 原型完整回归测试。

测试编号对应《StratumGenesis_最小原型工程规范_NovScript沙箱解释器.md》的 S/F 清单。
"""

import unittest

from novscript import SandboxLimits, run_sandbox, validate_on_nodes


class NovScriptPrototypeTests(unittest.TestCase):
    def assert_ok(self, source: str, value=None):
        result = run_sandbox(source)
        self.assertTrue(result.ok, result)
        if value is not None:
            self.assertEqual(result.value, value)
        return result

    def assert_error(self, source: str, error_type: str, limits=None):
        result = run_sandbox(source, limits=limits)
        self.assertFalse(result.ok, result)
        self.assertEqual(result.error_type, error_type, result)
        return result

    # S-01 ~ S-12：成功用例
    def test_s01_integer(self):
        self.assert_ok("42", 42)

    def test_s02_negative_integer(self):
        self.assert_ok("-7", -7)

    def test_s03_addition(self):
        self.assert_ok("(+ 1 2)", 3)

    def test_s04_binding_read(self):
        self.assert_ok("(bind x 9) x", 9)

    def test_s05_lazy_binding(self):
        self.assert_ok("(bind x (+ 1 2)) 4", 4)

    def test_s06_closure_creation(self):
        result = self.assert_ok("(lambda (x) x)")
        self.assertEqual(result.value, {"type": "Closure", "arity": 1})

    def test_s07_closure_call(self):
        self.assert_ok("((lambda (x) x) 8)", 8)

    def test_s08_lazy_argument(self):
        self.assert_ok("((lambda (x) 42) (+ 1 2))", 42)

    def test_s09_closure_capture(self):
        self.assert_ok("(bind a 5) ((lambda (x) (+ x a)) 3)", 8)

    def test_s10_multiple_top_level_expressions(self):
        self.assert_ok("(bind a 1) (bind b 2) (+ a b)", 3)

    def test_s11_comment(self):
        self.assert_ok(";; comment\n(+ 2 3)", 5)

    def test_s12_multiple_nodes(self):
        reports = validate_on_nodes("(+ 20 22)", ["node-a", "node-b", "node-c"])
        self.assertEqual(len(reports), 3)
        self.assertTrue(all(report.accepted for report in reports))
        self.assertEqual({report.result.value for report in reports}, {42})
        self.assertEqual(len({report.interpreter_version for report in reports}), 1)

    # F-01 ~ F-18：边界与失败用例
    def test_f01_empty_program_fixed_as_internal_nil(self):
        result = self.assert_ok("")
        self.assertEqual(result.value, {"type": "InternalNil"})

    def test_f02_unclosed_parenthesis(self):
        self.assert_error("(+ 1 2", "ParseError")

    def test_f03_extra_right_parenthesis(self):
        self.assert_error("(+ 1 2))", "ParseError")

    def test_f04_illegal_character(self):
        self.assert_error("(+ 1 @)", "LexError")

    def test_f05_unbound_name(self):
        self.assert_error("missing-name", "NameError")

    def test_f06_duplicate_binding(self):
        self.assert_error("(bind x 1) (bind x 2)", "NameError")

    def test_f07_non_function_call(self):
        self.assert_error("(1 2)", "TypeError")

    def test_f08_plus_too_few(self):
        self.assert_error("(+ 1)", "ArityError")

    def test_f09_plus_too_many(self):
        self.assert_error("(+ 1 2 3)", "ArityError")

    def test_f10_plus_type_error(self):
        self.assert_error("(+ 1 (lambda (x) x))", "TypeError")

    def test_f11_function_too_few(self):
        self.assert_error("((lambda (x y) x) 1)", "ArityError")

    def test_f12_function_too_many(self):
        self.assert_error("((lambda (x) x) 1 2)", "ArityError")

    def test_f13_cyclic_thunk(self):
        self.assert_error("(bind x x) x", "RecursionError")

    def test_f14_infinite_recursion(self):
        self.assert_error(
            "((lambda (x) (x x)) (lambda (x) (x x)))",
            "ResourceLimitError",
            SandboxLimits(max_steps=100, max_heap_objects=1_000, max_output_chars=100),
        )

    def test_f15_source_too_long(self):
        self.assert_error("1" * (64 * 1024 + 1), "ResourceLimitError")

    def test_f16_fake_external_import(self):
        # 字符串不是当前语法，因此先在词法层拒绝，不会触碰宿主导入。
        self.assert_error('(__import__ "os")', "LexError")

    def test_f17_unclosed_unsupported_string(self):
        self.assert_error('"unterminated', "LexError")

    def test_f18_node_results_are_deterministic(self):
        reports = validate_on_nodes("(+ 1 41)", ["a", "b", "c"])
        signatures = [(r.accepted, r.result.value, r.result.error_type) for r in reports]
        self.assertEqual(signatures, [(True, 42, None)] * 3)


if __name__ == "__main__":
    unittest.main()
