"""NovScript 对外沙箱入口和单机多节点模拟接口。"""

from __future__ import annotations

import builtins
from dataclasses import dataclass
from typing import Any

from .ast import Program
from .errors import (
    ArityError,
    LexError,
    NameError,
    NovScriptError,
    ParseError,
    RecursionError,
    ResourceLimitError,
    SandboxError,
    TypeError,
)
from .evaluator import Closure, InternalNil, LimitsState, Pair, evaluate_program
from .parser import parse

INTERPRETER_VERSION = "novscript-prototype-0.1"
MAX_SOURCE_CHARS = 64 * 1024


@dataclass(frozen=True)
class SandboxLimits:
    """一次运行的硬资源上限。"""

    max_steps: int = 100_000
    max_heap_objects: int = 10_000
    max_output_chars: int = 4_096


@dataclass(frozen=True)
class EvalResult:
    """可序列化的统一运行结果。"""

    ok: bool
    value: Any | None = None
    error_type: str | None = None
    error_message: str | None = None
    steps: int = 0
    # echo 等输出原语写入的文本（每次运行独立，默认空串向后兼容）。
    output: str = ""


@dataclass(frozen=True)
class ValidationReport:
    """一个单机模拟节点的独立验证报告。"""

    node_id: str
    accepted: bool
    result: EvalResult
    interpreter_version: str


def _validate_limits(limits: SandboxLimits) -> None:
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in (
        limits.max_steps, limits.max_heap_objects, limits.max_output_chars
    )):
        raise SandboxError("sandbox limits must be integers")
    if min(limits.max_steps, limits.max_heap_objects, limits.max_output_chars) <= 0:
        raise SandboxError("sandbox limits must be positive")


def _public_value(value: Any) -> Any:
    """仅把语言原始整数公开；闭包和内部值用稳定描述，避免泄露宿主地址。

    Pair（列表）展开为可序列化的嵌套结构 {"type": "Pair", ...}；右链（长列表）
    用迭代组装，不随列表长度递归，避免宿主 RecursionError 泄露为 SandboxError。
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, Closure):
        return {"type": "Closure", "arity": len(value.params)}
    if isinstance(value, InternalNil):
        return {"type": "InternalNil"}
    if not isinstance(value, Pair):
        return {"type": type(value).__name__}
    # 先沿右链收集全部 Pair 节点（迭代），再反向逐层组装嵌套结构。
    nodes: list[Pair] = []
    cursor: Any = value
    while isinstance(cursor, Pair):
        nodes.append(cursor)
        cursor = cursor.right
    result: Any = _public_value(cursor)
    for node in reversed(nodes):
        result = {"type": "Pair", "left": _public_value(node.left), "right": result}
    return result


def evaluate(
    program: Program,
    *,
    limits: SandboxLimits | None = None,
    registry=None,
) -> EvalResult:
    """在不接收宿主对象的环境中求值。

    registry：可选 FeatureRegistry；为 None 时只加载创世内核（与改造前一致）。
    """
    effective = limits or SandboxLimits()
    try:
        _validate_limits(effective)
        state = LimitsState(effective.max_steps, effective.max_heap_objects,
                            max_output_chars=effective.max_output_chars)
        value = evaluate_program(program, state, registry)
        return EvalResult(
            True, _public_value(value), steps=state.steps,
            output="\n".join(state.output_buffer),
        )
    except NovScriptError as error:
        # 只返回稳定类型名和诊断文字，不返回宿主 traceback。
        return EvalResult(False, error_type=type(error).__name__, error_message=str(error),
                          steps=locals().get("state", LimitsState(0, 1)).steps)
    except builtins.RecursionError:
        # 防御层：任何漏网的宿主递归错误统一映射为结构化资源限制错误，
        # 不得把 "maximum recursion depth exceeded" 原样上报为 SandboxError。
        return EvalResult(False, error_type="ResourceLimitError",
                          error_message="maximum structure depth exceeded",
                          steps=locals().get("state", LimitsState(0, 1)).steps)
    except Exception as error:
        return EvalResult(False, error_type="SandboxError", error_message=str(error),
                          steps=locals().get("state", LimitsState(0, 1)).steps)


def run_sandbox(
    source: str,
    *,
    limits: SandboxLimits | None = None,
    registry=None,
) -> EvalResult:
    """执行 parse + evaluate，对外入口与工程规范保持一致。

    registry：可选 FeatureRegistry；为 None 时只加载创世内核（与改造前一致）。
    """
    effective = limits or SandboxLimits()
    try:
        _validate_limits(effective)
        if not isinstance(source, str):
            raise SandboxError("source must be a string")
        if len(source) > MAX_SOURCE_CHARS:
            raise ResourceLimitError("source exceeds maximum length")
        program = parse(source)
        return evaluate(program, limits=effective, registry=registry)
    except NovScriptError as error:
        return EvalResult(False, error_type=type(error).__name__, error_message=str(error), steps=0)
    except builtins.RecursionError:
        # 防御层：解析阶段（深层嵌套源码）的宿主递归错误同样稳定归类。
        return EvalResult(False, error_type="ResourceLimitError",
                          error_message="maximum structure depth exceeded", steps=0)
    except Exception as error:
        return EvalResult(False, error_type="SandboxError", error_message=str(error), steps=0)


def validate_on_nodes(
    source: str,
    node_ids: list[str],
    *,
    limits: SandboxLimits | None = None,
    registry=None,
) -> list[ValidationReport]:
    """用独立运行调用模拟多个节点；不实现网络通信或真实共识。"""
    reports: list[ValidationReport] = []
    for node_id in node_ids:
        result = run_sandbox(source, limits=limits, registry=registry)
        reports.append(ValidationReport(node_id, result.ok, result, INTERPRETER_VERSION))
    return reports
