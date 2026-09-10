"""NovScript 扩展原语矩阵测试（外部保险，v0.3 语言演化）。

定位：为 15 个可激活扩展原语建立系统性边界与错误类型矩阵测试。
纪律：
- 只通过公开入口 run_sandbox 断言可观察行为，不读实现细节；
- 只断言结构化 error_type（阶段 D 起错误消息在语义化演进，不锁文案）；
- 不断言 steps 等内部计数的精确值；
- 确定性、无副作用：不写文件、不改全局状态、不依赖时钟/随机。
"""

import unittest

from novscript import run_sandbox
from novscript.language import LanguageSnapshot
from novscript.registry import activate_specs
from novscript.sandbox import SandboxLimits

ALL_FEATURES = ["-", "*", "//", "%", "eq", "lt", "gt", "if",
                "list", "cons", "head", "tail", "nil?", "length", "echo"]
# 一次性激活全部预置原语，作为矩阵测试的统一语言环境。
ALL_REGISTRY = activate_specs(ALL_FEATURES)


def run(source: str, registry=ALL_REGISTRY, **limit_kw) -> object:
    """便捷入口：默认全激活注册表；可传 limits。"""
    limits = SandboxLimits(**limit_kw) if limit_kw else None
    return run_sandbox(source, limits=limits, registry=registry)


def ok(source: str, registry=ALL_REGISTRY, **limit_kw) -> object:
    result = run(source, registry, **limit_kw)
    assert result.ok, (source, result.error_type, result.error_message)
    return result


def err(source: str, error_type: str, registry=ALL_REGISTRY, **limit_kw) -> object:
    result = run(source, registry, **limit_kw)
    assert not result.ok, (source, result)
    assert result.error_type == error_type, (source, result.error_type, error_type)
    return result


# ---------------------------------------------------------------------------
# 1. 算术原语矩阵：- * // %（正常含边界 / 元数 / 类型 / 专属边界）
# ---------------------------------------------------------------------------
class ArithmeticMatrixTests(unittest.TestCase):
    def test_sub_normal(self):
        self.assertEqual(ok("(- 10 3)").value, 7)

    def test_sub_negative_and_zero(self):
        self.assertEqual(ok("(- 3 10)").value, -7)
        self.assertEqual(ok("(- 5 0)").value, 5)
        self.assertEqual(ok("(- 0 0)").value, 0)

    def test_sub_arity(self):
        err("(- 10)", "ArityError")
        err("(- 10 3 2)", "ArityError")

    def test_sub_type(self):
        err("(- (lambda (x) x) 1)", "TypeError")
        err("(- 1 (list 2))", "TypeError")

    def test_mul_normal(self):
        self.assertEqual(ok("(* 3 4)").value, 12)

    def test_mul_negative_and_zero(self):
        self.assertEqual(ok("(* -3 4)").value, -12)
        self.assertEqual(ok("(* 7 0)").value, 0)

    def test_mul_arity(self):
        err("(* 1)", "ArityError")
        err("(* 1 2 3)", "ArityError")

    def test_mul_type(self):
        err("(* 2 (list 1))", "TypeError")
        err("(* (lambda (x) x) 3)", "TypeError")

    def test_floordiv_normal(self):
        self.assertEqual(ok("(// 7 2)").value, 3)

    def test_floordiv_boundary(self):
        self.assertEqual(ok("(// -7 2)").value, -4)  # Python floor 语义
        self.assertEqual(ok("(// 0 5)").value, 0)

    def test_floordiv_zero(self):
        err("(// 7 0)", "TypeError")

    def test_floordiv_arity(self):
        err("(// 7)", "ArityError")

    def test_floordiv_type(self):
        err("(// 7 (list 1))", "TypeError")

    def test_mod_normal(self):
        self.assertEqual(ok("(% 7 3)").value, 1)

    def test_mod_boundary(self):
        self.assertEqual(ok("(% 0 3)").value, 0)
        self.assertEqual(ok("(% -7 3)").value, 2)

    def test_mod_zero(self):
        err("(% 7 0)", "TypeError")

    def test_mod_arity(self):
        err("(% 7 3 1)", "ArityError")

    def test_mod_type(self):
        err("(% (list) 3)", "TypeError")


# ---------------------------------------------------------------------------
# 2. 比较原语矩阵：eq lt gt（返回 0/1，整数操作数）
# ---------------------------------------------------------------------------
class ComparisonMatrixTests(unittest.TestCase):
    def test_eq_true(self):
        self.assertEqual(ok("(eq 5 5)").value, 1)

    def test_eq_false(self):
        self.assertEqual(ok("(eq 5 6)").value, 0)

    def test_eq_zero_boundary(self):
        self.assertEqual(ok("(eq 0 0)").value, 1)
        self.assertEqual(ok("(eq 0 -0)").value, 1)

    def test_eq_arity(self):
        err("(eq 1)", "ArityError")
        err("(eq 1 2 3)", "ArityError")

    def test_eq_type(self):
        err("(eq 1 (list 1))", "TypeError")

    def test_lt_true(self):
        self.assertEqual(ok("(lt 1 2)").value, 1)

    def test_lt_false(self):
        self.assertEqual(ok("(lt 2 1)").value, 0)

    def test_lt_equal_boundary(self):
        self.assertEqual(ok("(lt 0 0)").value, 0)
        self.assertEqual(ok("(lt -1 0)").value, 1)

    def test_lt_arity(self):
        err("(lt 1)", "ArityError")

    def test_lt_type(self):
        err("(lt (lambda (x) x) 1)", "TypeError")

    def test_gt_true(self):
        self.assertEqual(ok("(gt 2 1)").value, 1)

    def test_gt_false(self):
        self.assertEqual(ok("(gt 1 2)").value, 0)

    def test_gt_equal_boundary(self):
        self.assertEqual(ok("(gt 0 0)").value, 0)
        self.assertEqual(ok("(gt 1 0)").value, 1)

    def test_gt_arity(self):
        err("(gt 1 2 3)", "ArityError")

    def test_gt_type(self):
        err("(gt 1 (list))", "TypeError")


# ---------------------------------------------------------------------------
# 3. 条件原语矩阵：if（惰性选择分支是核心契约）
# ---------------------------------------------------------------------------
class ConditionalMatrixTests(unittest.TestCase):
    def test_if_then_branch(self):
        self.assertEqual(ok("(if 1 7 8)").value, 7)

    def test_if_else_branch(self):
        self.assertEqual(ok("(if 0 7 8)").value, 8)

    def test_if_negative_is_truthy(self):
        self.assertEqual(ok("(if -1 7 8)").value, 7)

    def test_if_lazy_unselected_then(self):
        # 未选中的假分支含非法 head 应用：不得求值 -> 返回 7 而不报错。
        self.assertEqual(ok("(if 1 7 (head 5))").value, 7)

    def test_if_lazy_unselected_else(self):
        self.assertEqual(ok("(if 0 (head 5) 8)").value, 8)

    def test_if_arity(self):
        err("(if 1 7)", "ArityError")
        err("(if 1 7 8 9)", "ArityError")

    def test_if_condition_type(self):
        err("(if (list 1) 7 8)", "TypeError")


# ---------------------------------------------------------------------------
# 4. 列表原语矩阵：list cons head tail nil? length
# ---------------------------------------------------------------------------
class ListMatrixTests(unittest.TestCase):
    def test_list_empty(self):
        result = ok("(list)")
        self.assertEqual(result.value, {"type": "InternalNil"})

    def test_list_values(self):
        result = ok("(list 1 2 3)")
        self.assertEqual(result.value, {
            "type": "Pair", "left": 1,
            "right": {"type": "Pair", "left": 2,
                      "right": {"type": "Pair", "left": 3,
                                "right": {"type": "InternalNil"}}},
        })

    def test_list_variadic(self):
        # 变长：0 参与 5 参均合法。
        ok("(list)")
        ok("(list 1 2 3 4 5)")

    def test_cons_proper(self):
        self.assertEqual(ok("(head (cons 1 (list 2 3)))").value, 1)

    def test_cons_improper_pair(self):
        # cons 允许任意右值：得到非 proper pair，本身合法。
        result = ok("(cons 1 2)")
        self.assertEqual(result.value["type"], "Pair")

    def test_cons_arity(self):
        err("(cons 1)", "ArityError")
        err("(cons 1 2 3)", "ArityError")

    def test_head_normal(self):
        self.assertEqual(ok("(head (list 1 2 3))").value, 1)

    def test_head_single(self):
        self.assertEqual(ok("(head (list 42))").value, 42)

    def test_head_arity(self):
        err("(head)", "ArityError")
        err("(head (list 1) (list 2))", "ArityError")

    def test_head_type_int(self):
        err("(head 5)", "TypeError")

    def test_head_type_nil(self):
        err("(head (list))", "TypeError")

    def test_tail_normal(self):
        self.assertEqual(ok("(head (tail (list 1 2 3)))").value, 2)

    def test_tail_single(self):
        self.assertEqual(ok("(tail (list 1))").value, {"type": "InternalNil"})

    def test_tail_arity(self):
        err("(tail)", "ArityError")

    def test_tail_type(self):
        err("(tail 5)", "TypeError")
        err("(tail (list))", "TypeError")

    def test_nil_p_empty(self):
        self.assertEqual(ok("(nil? (list))").value, 1)

    def test_nil_p_nonempty(self):
        self.assertEqual(ok("(nil? (list 1))").value, 0)

    def test_nil_p_any_value(self):
        self.assertEqual(ok("(nil? 0)").value, 0)

    def test_nil_p_arity(self):
        err("(nil?)", "ArityError")

    def test_length_empty(self):
        self.assertEqual(ok("(length (list))").value, 0)

    def test_length_multi(self):
        self.assertEqual(ok("(length (list 1 2 3))").value, 3)

    def test_length_nested(self):
        self.assertEqual(ok("(length (list (list 1) (list 2 3)))").value, 2)

    def test_length_arity(self):
        err("(length)", "ArityError")

    def test_length_improper(self):
        err("(length (cons 1 2))", "TypeError")

    def test_length_type_int(self):
        err("(length 5)", "TypeError")


# ---------------------------------------------------------------------------
# 5. 输出原语矩阵：echo（返回 nil，输出进 result.output）
# ---------------------------------------------------------------------------
class EchoMatrixTests(unittest.TestCase):
    def test_echo_returns_nil(self):
        self.assertEqual(ok("(echo 1)").value, {"type": "InternalNil"})

    def test_echo_output_single(self):
        self.assertEqual(ok("(echo 42)").output, "42")

    def test_echo_output_multi(self):
        self.assertEqual(ok("(echo 1 2 3)").output, "1 2 3")

    def test_echo_variadic(self):
        ok("(echo)")  # 0 参合法

    def test_echo_accumulates_lines(self):
        self.assertEqual(ok("(echo 1)(echo 2)").output, "1\n2")

    def test_echo_any_value_type(self):
        result = ok("(echo (list 1 2))")
        self.assertTrue(result.output)  # 列表也有可显示形式，不锁文案


# ---------------------------------------------------------------------------
# 6. 纪元作用域外部保险（阶段 D）：可用性判定由注册表决定
# ---------------------------------------------------------------------------
class EpochScopeInsuranceTests(unittest.TestCase):
    def test_kernel_language_has_no_extension(self):
        result = run_sandbox("(- 10 3)")  # 不传 registry：仅创世内核
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "NameError")

    def test_activate_minus_via_registry(self):
        registry = activate_specs(["-"])
        result = run_sandbox("(- 10 3)", registry=registry)
        self.assertTrue(result.ok, (result.error_type, result.error_message))
        self.assertEqual(result.value, 7)

    def test_snapshot_rebuild_minus(self):
        snapshot = LanguageSnapshot(height=1, active_features=frozenset({"-"}))
        registry = LanguageSnapshot.build_registry(snapshot)
        result = run_sandbox("(- 10 3)", registry=registry)
        self.assertTrue(result.ok)
        self.assertEqual(result.value, 7)

    def test_list_without_head_is_name_error(self):
        registry = activate_specs(["list"])  # 只激活 list，未激活 head
        result = run_sandbox("(head (list 1 2))", registry=registry)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "NameError")


# ---------------------------------------------------------------------------
# 7. 沙箱上限矩阵（阶段 C 能力回归）
# ---------------------------------------------------------------------------
class SandboxLimitMatrixTests(unittest.TestCase):
    def test_output_exact_limit(self):
        # 10 行 × 10 字符 = 恰好 100 字符（累计不含 join 分隔符）-> ok。
        result = run("(echo 1234567890)" * 10, max_output_chars=100)
        self.assertTrue(result.ok, (result.error_type, result.error_message))
        self.assertGreaterEqual(len(result.output), 100)

    def test_output_over_limit(self):
        # 100 字符后再多 1 个字符 -> 超限。
        result = run("(echo 1234567890)" * 10 + "(echo 1)", max_output_chars=100)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "ResourceLimitError")

    def test_steps_tiny_limit(self):
        # max_steps=3 下任何非平凡表达式都超限。
        result = run("(+ 1 1)", max_steps=3)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "ResourceLimitError")

    def test_deep_nesting_source(self):
        # 20000 层括号：必须返回结构化错误，宿主递归细节不得泄漏。
        source = "(" * 20000 + "1" + ")" * 20000
        result = run_sandbox(source)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "ResourceLimitError")
        self.assertNotIn("maximum recursion depth exceeded", result.error_message or "")

    def test_deep_nesting_steps_positive(self):
        # 深层结构即使失败也应记录稳定步骤数（仅断言 ≥0，不锁精确值）。
        source = "(" * 20000 + "1" + ")" * 20000
        result = run_sandbox(source)
        self.assertGreaterEqual(result.steps, 0)


if __name__ == "__main__":
    unittest.main()
