"""NovScript BNF 的递归下降解析器。"""

from __future__ import annotations

from .ast import Bind, Call, Expr, IntLiteral, Lambda, Program, Symbol
from .errors import ParseError
from .lexer import Token, tokenize


class Parser:
    """将 token 序列解析成不可变 AST。"""

    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.index = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def advance(self) -> Token:
        token = self.current
        self.index += 1
        return token

    def expect(self, kind: str) -> Token:
        if self.current.kind != kind:
            token = self.current
            raise ParseError(
                f"line {token.line}, column {token.column}: expected {kind}, got {token.kind}"
            )
        return self.advance()

    def parse_program(self) -> Program:
        expressions: list[Expr] = []
        while self.current.kind != "EOF":
            expressions.append(self.parse_expression())
        return Program(tuple(expressions))

    def parse_expression(self) -> Expr:
        token = self.current
        if token.kind == "INTEGER":
            self.advance()
            return IntLiteral(int(token.lexeme))
        if token.kind == "IDENTIFIER":
            self.advance()
            return Symbol(token.lexeme)
        if token.kind == "LPAREN":
            return self.parse_list_form()
        if token.kind == "RPAREN":
            raise ParseError(f"line {token.line}, column {token.column}: unexpected ')' ")
        raise ParseError(f"line {token.line}, column {token.column}: expected expression")

    def parse_list_form(self) -> Expr:
        self.expect("LPAREN")
        if self.current.kind == "RPAREN":
            token = self.current
            raise ParseError(f"line {token.line}, column {token.column}: empty application")

        # 先看特殊形式名称；特殊形式的形状严格受 BNF 限制。
        if self.current.kind == "IDENTIFIER" and self.current.lexeme == "lambda":
            return self.parse_lambda_after_open()
        if self.current.kind == "IDENTIFIER" and self.current.lexeme == "bind":
            return self.parse_bind_after_open()

        function = self.parse_expression()
        arguments: list[Expr] = []
        while self.current.kind != "RPAREN":
            if self.current.kind == "EOF":
                token = self.current
                raise ParseError(f"line {token.line}, column {token.column}: missing ')' ")
            arguments.append(self.parse_expression())
        self.advance()
        return Call(function, tuple(arguments))

    def parse_lambda_after_open(self) -> Lambda:
        self.advance()  # lambda
        self.expect("LPAREN")
        params: list[str] = []
        while self.current.kind != "RPAREN":
            token = self.expect("IDENTIFIER")
            if token.lexeme in params:
                raise ParseError(f"duplicate lambda parameter {token.lexeme!r}")
            params.append(token.lexeme)
        self.advance()
        body = self.parse_expression()
        self.expect("RPAREN")
        return Lambda(tuple(params), body)

    def parse_bind_after_open(self) -> Bind:
        self.advance()  # bind
        name = self.expect("IDENTIFIER").lexeme
        expr = self.parse_expression()
        self.expect("RPAREN")
        return Bind(name, expr)


def parse(source: str) -> Program:
    """公开解析入口：tokenize 后构建 Program。"""
    return Parser(tokenize(source)).parse_program()
