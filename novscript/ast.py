"""NovScript 抽象语法树定义。

AST 使用 frozen dataclass，避免求值阶段修改语法结构，便于单机多节点重放。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True)
class IntLiteral:
    """整数常量。"""

    value: int


@dataclass(frozen=True)
class Symbol:
    """标识符，包括创世内核原语 +。"""

    name: str


@dataclass(frozen=True)
class Lambda:
    """函数表达式，保存参数名称和函数体。"""

    params: tuple[str, ...]
    body: "Expr"


@dataclass(frozen=True)
class Bind:
    """不可变绑定表达式。"""

    name: str
    expr: "Expr"


@dataclass(frozen=True)
class Call:
    """函数调用表达式。"""

    function: "Expr"
    arguments: tuple["Expr", ...]


Expr: TypeAlias = IntLiteral | Symbol | Lambda | Bind | Call


@dataclass(frozen=True)
class Program:
    """顶层表达式序列。"""

    expressions: tuple[Expr, ...]
