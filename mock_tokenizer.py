"""PoI 的本地 mock 标准分词器。

原型不调用真实 LLM，也不依赖第三方 tokenizer。这里用确定性的字符/词片规则
模拟 input/output/total token 计数，仅用于校验流程演示，不代表最终协议 tokenizer。
"""

from __future__ import annotations

from dataclasses import dataclass
import re

MOCK_TOKENIZER_ID = "mock-tokenizer-v1"
_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_?!-]*|\d+|[^\s]")


@dataclass(frozen=True)
class MockTokenCounts:
    """mock tokenizer 的三项计数结果。"""

    standard_input_tokens: int
    standard_output_tokens: int
    standard_total_tokens: int
    tokenizer_id: str = MOCK_TOKENIZER_ID


def count_text(text: str) -> int:
    """对文本执行确定性 mock 计数；空文本计数为 0。"""
    return len(_TOKEN_PATTERN.findall(text))


def count_poi_tokens(prompt: str, output: str) -> MockTokenCounts:
    """统计 PoI 所需的 prompt、output 及总 token 数。"""
    input_tokens = count_text(prompt)
    output_tokens = count_text(output)
    return MockTokenCounts(input_tokens, output_tokens, input_tokens + output_tokens)
