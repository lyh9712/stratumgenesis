"""沙箱输出上限与宿主递归错误归类的回归测试（v0.3 阶段 C 收尾）。"""

import unittest

from novscript import SandboxLimits, run_sandbox
from novscript.registry import activate_specs


class SandboxOutputLimitTests(unittest.TestCase):
    """A：max_output_chars 必须真实生效（超限抛 ResourceLimitError）。"""

    def setUp(self) -> None:
        # 只激活 echo，避免其它原语干扰；创世内核 + echo 即可完成输出测试。
        self.registry = activate_specs(("echo",))

    def test_output_exceeding_limit_raises_resource_limit_error(self):
        # 500 条 echo，每条输出 10 字符 -> 无上限时累计 5000 字符；
        # 上限 4096 时应在第 410 条处抛 ResourceLimitError。
        limits = SandboxLimits(max_output_chars=4096)
        source = " ".join("(echo 1234567890)" for _ in range(500))
        result = run_sandbox(source, limits=limits, registry=self.registry)
        self.assertFalse(result.ok, result)
        self.assertEqual(result.error_type, "ResourceLimitError")
        self.assertIn("output", result.error_message)

    def test_output_exactly_at_limit_succeeds(self):
        # 10 条 echo × 10 字符 = 100，恰好等于上限：应成功且输出完整。
        limits = SandboxLimits(max_output_chars=100)
        source = " ".join("(echo 1234567890)" for _ in range(10))
        result = run_sandbox(source, limits=limits, registry=self.registry)
        self.assertTrue(result.ok, result)
        # 10 行文本 + 9 个换行符（join 在最后执行，不计入累计上限）。
        self.assertEqual(result.output, "\n".join(["1234567890"] * 10))


class SandboxRecursionClassificationTests(unittest.TestCase):
    """B：宿主递归错误不得伪装成 SandboxError。"""

    def test_long_list_returns_stable_result_without_host_recursion_leak(self):
        # 2000 元素扁列表：旧实现 _public_value 递归展开会触发宿主
        # RecursionError 并被兜底上报为 SandboxError；现应迭代展开成功。
        registry = activate_specs(("list",))
        source = "(list " + " ".join(["1"] * 2000) + ")"
        result = run_sandbox(source, registry=registry)
        self.assertTrue(result.ok, result)
        self.assertIsNotNone(result.value)
        self.assertNotIn("maximum recursion depth exceeded", result.error_message or "")

    def test_host_recursion_fallback_is_classified_as_resource_limit(self):
        # 防御层验证：显式制造宿主 RecursionError 场景（深嵌套源码，
        # parser 递归下降超限），必须稳定归类为 ResourceLimitError，
        # 不得把 "maximum recursion depth exceeded" 原样上报。
        depth = 10_000
        source = "(" * depth + "1" + ")" * depth
        result = run_sandbox(source, registry=None)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "ResourceLimitError")
        self.assertNotIn("maximum recursion depth exceeded", result.error_message or "")


if __name__ == "__main__":
    unittest.main()
