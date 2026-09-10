"""NovScript 惰性求值器。

实现重点：bind 和函数参数都保存为 thunk；第一次 force 时求值并记忆化。
解释器永不调用 eval/exec，也不把 NovScript 翻译成 Python。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .ast import Bind, Call, Expr, IntLiteral, Lambda, Program, Symbol
from .errors import ArityError, NameError, RecursionError, ResourceLimitError, TypeError


@dataclass
class LimitsState:
    """一次求值的可变资源计数器，仅存在于解释器内部。"""

    max_steps: int
    max_heap_objects: int
    max_output_chars: int = 4_096
    steps: int = 0
    heap_objects: int = 0
    call_depth: int = 0
    max_call_depth: int = 1_000
    # echo 等输出类原语写入的缓冲区；沙箱结束时会聚合成 EvalResult.output。
    output_buffer: list[str] = field(default_factory=list)
    # 已写入输出缓冲区的累计字符数（强制输出上限的计账字段）。
    output_chars: int = 0

    def step(self) -> None:
        self.steps += 1
        if self.steps > self.max_steps:
            raise ResourceLimitError("maximum evaluation steps exceeded")

    def allocate(self, count: int = 1) -> None:
        self.heap_objects += count
        if self.heap_objects > self.max_heap_objects:
            raise ResourceLimitError("maximum heap objects exceeded")

    def append_output(self, text: str) -> None:
        """向输出缓冲区写入一行文本，并累计字符数。

        累计超过 max_output_chars 时抛 ResourceLimitError（纳入既有 8 类
        结构化错误，不新增错误类型），保证 echo 等输出原语无法无限撑爆
        沙箱结果。
        """
        self.output_chars += len(text)
        if self.output_chars > self.max_output_chars:
            raise ResourceLimitError("maximum output characters exceeded")
        self.output_buffer.append(text)


@dataclass
class Environment:
    """词法环境；bindings 仅允许新增名称，已有名称不可覆盖。"""

    bindings: dict[str, "Binding"]
    parent: "Environment | None" = None

    def lookup(self, name: str) -> "Binding":
        if name in self.bindings:
            return self.bindings[name]
        if self.parent is not None:
            return self.parent.lookup(name)
        raise NameError(f"unbound name: {name}")

    def extend(self, name: str, binding: "Binding") -> "Environment":
        if name in self.bindings:
            raise NameError(f"duplicate binding: {name}")
        return Environment({name: binding}, self)


class Binding:
    """绑定抽象基类。"""

    def force(self, state: LimitsState) -> "Value":
        raise NotImplementedError


@dataclass
class ValueBinding(Binding):
    value: "Value"

    def force(self, state: LimitsState) -> "Value":
        return self.value


@dataclass
class Thunk(Binding):
    """可记忆化 thunk，FORCING 状态用于检测循环强制。"""

    expression: Expr
    environment: Environment
    state: str = "UNFORCED"
    cached: "Value | None" = None

    def force(self, state: LimitsState) -> "Value":
        if self.state == "FORCED":
            assert self.cached is not None
            return self.cached
        if self.state == "FORCING":
            raise RecursionError("cyclic thunk forcing detected")
        self.state = "FORCING"
        try:
            value = evaluate_expr(self.expression, self.environment, state)
        except Exception:
            # 失败后恢复为未强制，避免错误对象被伪装成合法缓存值。
            self.state = "UNFORCED"
            raise
        self.cached = value
        self.state = "FORCED"
        return value


@dataclass
class Closure:
    params: tuple[str, ...]
    body: Expr
    environment: Environment


@dataclass(frozen=True)
class Builtin:
    name: str
    implementation: Callable[[list[Thunk], LimitsState], "Value"]


@dataclass(frozen=True)
class InternalNil:
    """解释器内部的空结果标记，不作为 NovScript 公共类型暴露。"""


@dataclass(frozen=True)
class Pair:
    """列表/对值：扩展原语 list/cons/head/tail 等操作的底层表示。"""

    left: "Value"
    right: "Value"


Value = int | Closure | Builtin | InternalNil | Pair


def display_value(value: Value) -> str:
    """把值转成可读字符串（供 echo 原语与沙箱展示使用）。

    - 整数 -> 十进制文本；nil -> "nil"；
    - Pair -> 尽量按 proper list 形式输出 "(1 2 3)"，不闭合的链按 "(1 . 2)"；
    - Closure/Builtin -> 各自的一等值标签。

    右链（长列表）用迭代展开，不随列表长度递归；left 侧的深嵌套受
    parser 递归深度天然限制，残余宿主递归由沙箱防御层兜底映射。
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, InternalNil):
        return "nil"
    if isinstance(value, Pair):
        items: list[str] = []
        cursor: Value = value
        while isinstance(cursor, Pair):
            items.append(display_value(cursor.left))
            cursor = cursor.right
        if isinstance(cursor, InternalNil):
            return "(" + " ".join(items) + ")"
        return "(" + " ".join(items) + " . " + display_value(cursor) + ")"
    if isinstance(value, Closure):
        return "#<closure>"
    if isinstance(value, Builtin):
        return f"#<builtin:{value.name}>"
    return "#<unknown>"


def _plus(arguments: list[Thunk], state: LimitsState) -> Value:
    if len(arguments) != 2:
        raise ArityError(f"+ expects 2 arguments, got {len(arguments)}")
    values = [argument.force(state) for argument in arguments]
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        raise TypeError("+ expects integer arguments")
    return values[0] + values[1]


def initial_environment(state: LimitsState, registry=None) -> Environment:
    """创建每次运行都独立的新创世环境。

    registry：可选 FeatureRegistry。为 None 时只加载创世内核（+ 加法），
    行为与语言演化改造前完全一致；传入注册表时，把其中已激活的扩展原语
    一并注册进环境（同名与内核冲突在注册阶段已由 FeatureRegistry 拒绝）。
    """
    state.allocate()
    bindings: dict[str, Binding] = {"+": ValueBinding(Builtin("+", _plus))}
    if registry is not None:
        for spec in registry.all_specs():
            bindings[spec.name] = ValueBinding(Builtin(spec.name, spec.impl))
    return Environment(bindings)


def evaluate_expr(expression: Expr, environment: Environment, state: LimitsState) -> Value:
    state.step()
    if isinstance(expression, IntLiteral):
        return expression.value
    if isinstance(expression, Symbol):
        return environment.lookup(expression.name).force(state)
    if isinstance(expression, Lambda):
        state.allocate()
        return Closure(expression.params, expression.body, environment)
    if isinstance(expression, Bind):
        state.allocate()
        # 非顶层 bind 的值不会自动传递出当前表达式；这里仍保留语义上的
        # 延迟绑定。顶层程序绑定由 evaluate_program 负责扩展到后续表达式。
        # 不在此处 force RHS，也不把绑定变成宿主语言变量。
        return InternalNil()
    if isinstance(expression, Call):
        function = evaluate_expr(expression.function, environment, state)
        arguments = [Thunk(argument, environment) for argument in expression.arguments]
        state.allocate(len(arguments))
        return apply_value(function, arguments, state)
    raise TypeError(f"unsupported AST node: {type(expression).__name__}")


def apply_value(function: Value, arguments: list[Thunk], state: LimitsState) -> Value:
    state.step()
    if isinstance(function, Builtin):
        return function.implementation(arguments, state)
    if not isinstance(function, Closure):
        raise TypeError("attempted to call a non-function")
    if len(arguments) != len(function.params):
        raise ArityError(
            f"function expects {len(function.params)} arguments, got {len(arguments)}"
        )
    state.call_depth += 1
    if state.call_depth > state.max_call_depth:
        state.call_depth -= 1
        raise RecursionError("maximum call depth exceeded")
    try:
        call_environment = function.environment
        for name, argument in zip(function.params, arguments):
            call_environment = call_environment.extend(name, argument)
        return evaluate_expr(function.body, call_environment, state)
    finally:
        state.call_depth -= 1


def evaluate_program(program: Program, state: LimitsState, registry=None) -> Value:
    environment = initial_environment(state, registry)
    result: Value = InternalNil()
    for expression in program.expressions:
        state.step()
        if isinstance(expression, Bind):
            # 顶层 bind 必须把绑定扩展到后续表达式；仍不强制 RHS。
            # 先建立新环境，再让 thunk 捕获该新环境，使 (bind x x) x
            # 被识别为循环 thunk，而不是错误地变成“未绑定名称”。
            if expression.name in environment.bindings:
                raise NameError(f"duplicate binding: {expression.name}")
            new_environment = Environment({}, environment)
            new_environment.bindings[expression.name] = Thunk(expression.expr, new_environment)
            environment = new_environment
            state.allocate()
            result = InternalNil()
        else:
            result = evaluate_expr(expression, environment, state)
    return result
