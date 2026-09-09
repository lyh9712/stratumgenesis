"""NovScript 原型的结构化错误类型。

这些异常只描述解释器内部失败原因；对外由 sandbox.run_sandbox 统一转换为
EvalResult。错误类型名称是单机多节点模拟比较结果时的稳定协议字段。
"""


class NovScriptError(Exception):
    """所有 NovScript 错误的共同基类。"""


class LexError(NovScriptError):
    """词法分析失败。"""


class ParseError(NovScriptError):
    """语法分析失败。"""


class NameError(NovScriptError):
    """读取未绑定名称或重复创建绑定。"""


class TypeError(NovScriptError):
    """值类型不满足操作要求。"""


class ArityError(NovScriptError):
    """函数或内置原语参数数量错误。"""


class RecursionError(NovScriptError):
    """解释器调用深度或 thunk 强制递归超限。"""


class ResourceLimitError(NovScriptError):
    """执行步骤、堆对象、源码或输出资源超限。"""


class SandboxError(NovScriptError):
    """沙箱配置或解释器边界错误。"""
