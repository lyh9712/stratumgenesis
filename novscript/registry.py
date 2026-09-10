"""NovScript 扩展原语注册表与预置原语池。

创世内核只内置 + 加法。本模块提供可被「语言扩展提案」激活的预置原语池
（BUILTIN_POOL）与运行时注册表（FeatureRegistry）：提案通过校验后，其
activation 中列出的原语被注册进链级注册表，后续区块即可调用这些原语；
历史区块按当时的语言快照重放，从而让「语言真实演化」成为可验证的事实。

原型范围说明：
- 本版只做「原语级」注册，不做语法级扩展（parser 不变）。
- 布尔值用整数 0/1 表示（Value 类型只有整数），nil 用 InternalNil 表示。
- 所有实现与内核 + 一致：严格求值风格，参数数量错误抛 ArityError。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .evaluator import (
    ArityError,
    InternalNil,
    LimitsState,
    Pair,
    Thunk,
    TypeError,
    Value,
    display_value,
)

PrimitiveImpl = Callable[[list[Thunk], LimitsState], Value]

# 内核自带原语名，扩展提案不得重新激活（防止同名覆盖内核）。
KERNEL_PRIMITIVES = frozenset({"+", "bind", "lambda"})


def _require_arity(arguments: list[Thunk], count: int, name: str) -> None:
    if len(arguments) != count:
        raise ArityError(f"{name} expects {count} arguments, got {len(arguments)}")


def _require_int(value: Value, name: str, index: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} expects integer argument #{index}")
    return value


def _force_int(arguments: list[Thunk], state: LimitsState, name: str, index: int) -> int:
    return _require_int(arguments[index].force(state), name, index)


# ---------------------------------------------------------------------------
# 预置原语实现（与内核 _plus 同签名：list[Thunk], LimitsState -> Value）
# ---------------------------------------------------------------------------
def _impl_sub(arguments: list[Thunk], state: LimitsState) -> Value:
    """整数减法：(- a b)。"""
    _require_arity(arguments, 2, "-")
    return _force_int(arguments, state, "-", 0) - _force_int(arguments, state, "-", 1)


def _impl_mul(arguments: list[Thunk], state: LimitsState) -> Value:
    """整数乘法：(* a b)。"""
    _require_arity(arguments, 2, "*")
    return _force_int(arguments, state, "*", 0) * _force_int(arguments, state, "*", 1)


def _impl_floordiv(arguments: list[Thunk], state: LimitsState) -> Value:
    """整数整除：// a b（Python floor 除法语义）。"""
    _require_arity(arguments, 2, "//")
    denominator = _force_int(arguments, state, "//", 1)
    if denominator == 0:
        raise TypeError("// division by zero")
    return _force_int(arguments, state, "//", 0) // denominator


def _impl_mod(arguments: list[Thunk], state: LimitsState) -> Value:
    """整数取模：% a b。"""
    _require_arity(arguments, 2, "%")
    denominator = _force_int(arguments, state, "%", 1)
    if denominator == 0:
        raise TypeError("% modulo by zero")
    return _force_int(arguments, state, "%", 0) % denominator


def _impl_eq(arguments: list[Thunk], state: LimitsState) -> Value:
    """整数相等：返回 1（相等）或 0（不等）。"""
    _require_arity(arguments, 2, "eq")
    return 1 if _force_int(arguments, state, "eq", 0) == _force_int(arguments, state, "eq", 1) else 0


def _impl_lt(arguments: list[Thunk], state: LimitsState) -> Value:
    """整数小于：返回 1 或 0。"""
    _require_arity(arguments, 2, "lt")
    return 1 if _force_int(arguments, state, "lt", 0) < _force_int(arguments, state, "lt", 1) else 0


def _impl_gt(arguments: list[Thunk], state: LimitsState) -> Value:
    """整数大于：返回 1 或 0。"""
    _require_arity(arguments, 2, "gt")
    return 1 if _force_int(arguments, state, "gt", 0) > _force_int(arguments, state, "gt", 1) else 0


def _impl_if(arguments: list[Thunk], state: LimitsState) -> Value:
    """条件：非 0 为真，惰性选择分支（未选中的分支不求值）。"""
    _require_arity(arguments, 3, "if")
    condition = _force_int(arguments, state, "if", 0)
    if condition != 0:
        return arguments[1].force(state)
    return arguments[2].force(state)


def _impl_list(arguments: list[Thunk], state: LimitsState) -> Value:
    """变长列表构造：(list a b c ...) -> 嵌套 Pair 链，空表为 nil。"""
    result: Value = InternalNil()
    for argument in reversed(arguments):
        result = Pair(argument.force(state), result)
    return result


def _impl_cons(arguments: list[Thunk], state: LimitsState) -> Value:
    """把值放进对：(cons 1 (list 2 3)) -> (1 2 3)。"""
    _require_arity(arguments, 2, "cons")
    return Pair(arguments[0].force(state), arguments[1].force(state))


def _require_pair(value: Value, name: str) -> Pair:
    if not isinstance(value, Pair):
        raise TypeError(f"{name} expects a pair/list argument")
    return value


def _impl_head(arguments: list[Thunk], state: LimitsState) -> Value:
    """取列表头：(head (list 1 2)) -> 1。"""
    _require_arity(arguments, 1, "head")
    return _require_pair(arguments[0].force(state), "head").left


def _impl_tail(arguments: list[Thunk], state: LimitsState) -> Value:
    """取列表尾：(tail (list 1 2)) -> (2)。"""
    _require_arity(arguments, 1, "tail")
    return _require_pair(arguments[0].force(state), "tail").right


def _impl_nil_p(arguments: list[Thunk], state: LimitsState) -> Value:
    """判断是否空表：nil 为 1，否则 0。"""
    _require_arity(arguments, 1, "nil?")
    return 1 if isinstance(arguments[0].force(state), InternalNil) else 0


def _impl_length(arguments: list[Thunk], state: LimitsState) -> Value:
    """求 proper list 长度：(length (list 1 2 3)) -> 3。"""
    _require_arity(arguments, 1, "length")
    value = arguments[0].force(state)
    count = 0
    while isinstance(value, Pair):
        count += 1
        value = value.right
    if not isinstance(value, InternalNil):
        raise TypeError("length expects a proper list")
    return count


def _impl_echo(arguments: list[Thunk], state: LimitsState) -> Value:
    """把参数的可显示形式写入沙箱输出缓冲区，返回 nil。

    输出经 LimitsState.append_output 累计字符数，超过 max_output_chars
    时抛 ResourceLimitError（由沙箱统一归类为结构化错误）。
    """
    parts = []
    for argument in arguments:
        value = argument.force(state)
        parts.append(display_value(value))
    state.append_output(" ".join(parts))
    return InternalNil()


# ---------------------------------------------------------------------------
# 预置原语池：name -> PrimitiveSpec（可被提案激活的全部扩展原语）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PrimitiveSpec:
    """一个可被激活的原语定义。

    注意：参数数量约束（arity）由各实现函数自查（抛 ArityError），
    不在元数据中声明，避免装饰性字段被未来校验逻辑误信。
    """

    name: str
    impl: PrimitiveImpl
    description: str


def _build_specs() -> dict[str, PrimitiveSpec]:
    impls: dict[str, PrimitiveImpl] = {
        "-": _impl_sub,
        "*": _impl_mul,
        "//": _impl_floordiv,
        "%": _impl_mod,
        "eq": _impl_eq,
        "lt": _impl_lt,
        "gt": _impl_gt,
        "if": _impl_if,
        "list": _impl_list,
        "cons": _impl_cons,
        "head": _impl_head,
        "tail": _impl_tail,
        "nil?": _impl_nil_p,
        "length": _impl_length,
        "echo": _impl_echo,
    }
    descriptions = {
        "-": "整数减法：(- a b)",
        "*": "整数乘法：(* a b)",
        "//": "整数整除：// a b",
        "%": "整数取模：% a b",
        "eq": "整数相等判定，返回 1/0",
        "lt": "整数小于判定，返回 1/0",
        "gt": "整数大于判定，返回 1/0",
        "if": "惰性条件分支：if 条件 真分支 假分支",
        "list": "变长列表构造：(list a b c ...)",
        "cons": "把值放入对：cons",
        "head": "取列表头",
        "tail": "取列表尾",
        "nil?": "判断空表，返回 1/0",
        "length": "求 proper list 长度",
        "echo": "把参数显示形式写入输出缓冲区",
    }
    return {
        name: PrimitiveSpec(name=name, impl=impls[name], description=descriptions[name])
        for name in impls
    }


_BUILTIN_SPECS = _build_specs()

# 预置原语池（只读映射）；未知名字的激活会抛 NameError。
BUILTIN_POOL: dict[str, PrimitiveSpec] = dict(_BUILTIN_SPECS)


@dataclass
class FeatureRegistry:
    """链级/分支级原语注册表：记录当前已激活的扩展原语。"""

    _specs: dict[str, PrimitiveSpec] = field(default_factory=dict)

    @classmethod
    def from_specs(cls, specs: list[PrimitiveSpec] | tuple[PrimitiveSpec, ...]) -> "FeatureRegistry":
        registry = cls()
        for spec in specs:
            registry.register(spec)
        return registry

    def register(self, spec: PrimitiveSpec) -> None:
        if spec.name in KERNEL_PRIMITIVES:
            raise NameError(f"feature {spec.name} conflicts with NovScript kernel primitive")
        if spec.name in self._specs:
            raise NameError(f"feature {spec.name} is already registered")
        self._specs[spec.name] = spec

    def has(self, name: str) -> bool:
        return name in self._specs

    def get(self, name: str) -> PrimitiveSpec | None:
        return self._specs.get(name)

    def snapshot(self) -> frozenset[str]:
        """返回已激活原语名集合（用于语言快照与确定性重放）。"""
        return frozenset(self._specs)

    def all_specs(self) -> tuple[PrimitiveSpec, ...]:
        """按名字排序返回全部已注册定义（确定性顺序）。"""
        return tuple(self._specs[name] for name in sorted(self._specs))


def spec_of(name: str) -> PrimitiveSpec | None:
    """从预置池取原语定义；未知名字返回 None。"""
    return _BUILTIN_SPECS.get(name)


def activate_specs(names: list[str] | tuple[str, ...]) -> FeatureRegistry:
    """从预置池按名字构造注册表；未知名字抛 NameError。"""
    specs = []
    for name in names:
        spec = _BUILTIN_SPECS.get(name)
        if spec is None:
            raise NameError(f"feature {name} not in BUILTIN_POOL")
        specs.append(spec)
    return FeatureRegistry.from_specs(specs)
