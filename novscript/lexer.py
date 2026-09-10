"""NovScript 字符级词法分析器。

仅实现创世内核需要的整数、标识符、括号、空白和 ;; 行注释。
字符串、列表、方括号和其他扩展语法会明确报 LexError。
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import LexError


@dataclass(frozen=True)
class Token:
    """词法 token，保留位置以便诊断。"""

    kind: str
    lexeme: str
    line: int
    column: int


_SINGLE = {"(": "LPAREN", ")": "RPAREN"}


def tokenize(source: str) -> list[Token]:
    """把源代码转换成 token 列表，并在结尾追加 EOF。"""
    tokens: list[Token] = []
    i, line, column = 0, 1, 1
    length = len(source)

    def advance() -> str:
        nonlocal i, line, column
        char = source[i]
        i += 1
        if char == "\n":
            line, column = line + 1, 1
        else:
            column += 1
        return char

    while i < length:
        char = source[i]
        if char.isspace():
            advance()
            continue
        if char == ";":
            start_line, start_column = line, column
            if i + 1 >= length or source[i + 1] != ";":
                raise LexError(f"line {line}, column {column}: single ';' is invalid")
            advance(); advance()
            while i < length and source[i] != "\n":
                advance()
            # 注释本身不产生 token；换行在下一轮作为空白处理。
            continue
        if char in _SINGLE:
            tokens.append(Token(_SINGLE[char], advance(), line, column - 1))
            continue
        if char.isdigit() or (char == "-" and i + 1 < length and source[i + 1].isdigit()):
            start_line, start_column = line, column
            text = advance()
            while i < length and source[i].isdigit():
                text += advance()
            tokens.append(Token("INTEGER", text, start_line, start_column))
            continue
        # + 是创世内核唯一的内置加法原语，作为保留标识符接受。
        if char == "+":
            tokens.append(Token("IDENTIFIER", advance(), line, column - 1))
            continue
        if char.isalpha():
            start_line, start_column = line, column
            text = advance()
            while i < length and (source[i].isalnum() or source[i] in "-_?!"):
                text += advance()
            tokens.append(Token("IDENTIFIER", text, start_line, start_column))
            continue
        # 扩展原语名（符号形式）：- * % 单独出现时作为标识符；
        # - 后跟数字的负整数字面量已在上方 INTEGER 分支处理。
        if char in "-*%":
            tokens.append(Token("IDENTIFIER", advance(), line, column - 1))
            continue
        # 整除原语 //：双字符符号标识符（与 ;; 行注释不冲突）。
        if char == "/" and i + 1 < length and source[i + 1] == "/":
            tokens.append(Token("IDENTIFIER", advance() + advance(), line, column - 2))
            continue
        raise LexError(f"line {line}, column {column}: invalid character {char!r}")

    tokens.append(Token("EOF", "", line, column))
    return tokens
