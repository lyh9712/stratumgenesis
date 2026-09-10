"""StratumGenesis v0.3 · 并行线 C —— 离线链分析器与实验指标。

把「语言演化实验」的链数据变成可复现、可发布的指标，对应设计白皮书
§13（学术价值）与 §14.5（长期：定期导出完整链数据、撰写实验报告）。

用法
----
    python analyze_chain.py <存档或导出 JSON> [--json out.json]
    python analyze_chain.py --synthetic [--json out.json]
    python analyze_chain.py --json out.json            # 无存档时回退到合成链
    python analyze_chain.py <存档> --verify-hashes     # 额外做完整哈希/签名重验

指标口径（关键约束）
--------------------
全部指标只从 blocks[] 的稳定字段推导：
    blocks[].activation / blocks[].height / blocks[].epoch
    blocks[].poi.standard_* / blocks[].transactions
    blocks[].proposer / blocks[].miner_pubkey_b64 / blocks[].block_hash
纪元粒度：epoch = height // 100（与 epoch_manager.EPOCH_BLOCKS 一致）。

刻意**不依赖**以下字段（语义正在 v0.3 变更中，且都能由 blocks[] 重新推导）：
    epochs[].active_features / current_active_features / language_features
    summary_chain / miner_label / reason

每个指标的定义、计算口径、来源字段与已知局限见 EXPERIMENT_METRICS.md。

并行开发边界
------------
- 只新增文件：本脚本、EXPERIMENT_METRICS.md、tests/test_analyze_chain.py；
- 不修改、不删除任何既有文件；不读写 data/ 与 data/chain_v1.json；
- 不起 HTTP 服务（127.0.0.1:28417 归其他并行线），不跑全量测试；
- 纯标准库 + 项目既有模块，无第三方库，无联网。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import types
import unicodedata
from dataclasses import replace
from statistics import mean, median
from typing import Any

EXPECTED_FORMAT_VERSION = "chain-v2"   # 与 persistence.FORMAT_VERSION 对齐
EPOCH_BLOCKS = 100                     # 与 epoch_manager.EPOCH_BLOCKS 对齐
ANALYZER_NAME = "analyze_chain.py"
ANALYZER_SCHEMA_VERSION = 1

DERIVED_FROM = (
    "blocks[].activation", "blocks[].height", "blocks[].epoch",
    "blocks[].poi.standard_input_tokens", "blocks[].poi.standard_output_tokens",
    "blocks[].poi.standard_total_tokens", "blocks[].poi.standard_tokenizer",
    "blocks[].transactions", "blocks[].proposer", "blocks[].miner_pubkey_b64",
    "blocks[].block_hash", "blocks[].proposal.kind", "blocks[].proposal.feature_id",
    "sleeping_branches[].branch_id", "sleeping_branches[].blocks[]",
    "miners[].label", "rejection_reasons",
)
AVOIDED_FIELDS = (
    "epochs[].active_features", "current_active_features",
    "language_features", "summary_chain", "miner_label", "reason",
)


# ============================================================================
# 0) 可选依赖回退：纯标准库 P-256 ECDSA shim
# ============================================================================
# 项目内只有 crypto_key.py 直接依赖第三方 ecdsa 包。本任务禁止联网安装依赖、
# 也禁止修改任何既有文件，因此当运行环境缺失该包时，这里用一个语义等价的最小
# 标准库实现（NIST P-256 曲线运算、确定性签名、DER 编解码）注入 sys.modules，
# 让既有模块原样 import 即可工作。真实 ecdsa 存在时优先使用真实实现，
# 行为完全不变。这是本分析器的运行环境兼容层，不属于协议实现的一部分。
# ============================================================================
_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
_GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5
_G = (_GX, _GY)


class _BadSignatureError(Exception):
    """shim 内部签名错误类型（对齐 ecdsa.BadSignatureError）。"""


def _ec_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2:
        if (y1 + y2) % _P == 0:
            return None
        return _ec_double(p1)
    slope = (y2 - y1) * pow(x2 - x1, -1, _P) % _P
    x3 = (slope * slope - x1 - x2) % _P
    return x3, (slope * (x1 - x3) - y1) % _P


def _ec_double(p1):
    x1, y1 = p1
    if y1 == 0:
        return None
    slope = (3 * x1 * x1) * pow(2 * y1, -1, _P) % _P
    x3 = (slope * slope - 2 * x1) % _P
    return x3, (slope * (x1 - x3) - y1) % _P


def _ec_mul(k, point):
    k %= _N
    result = None
    addend = point
    while k:
        if k & 1:
            result = _ec_add(result, addend)
        addend = _ec_double(addend)
        k >>= 1
    return result


def _on_curve(x, y) -> bool:
    return 0 <= x < _P and 0 <= y < _P and (y * y - x * x * x + 3 * x) % _P == _B


def _der_encode(r, s):
    def _part(value):
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        if raw and raw[0] & 0x80:
            raw = b"\x00" + raw
        return b"\x02" + bytes([len(raw)]) + raw
    left, right = _part(r), _part(s)
    return b"\x30" + bytes([len(left) + len(right)]) + left + right


def _der_decode(signature):
    if len(signature) < 4 or signature[0] != 0x30:
        raise _BadSignatureError("DER signature missing sequence header")
    body = signature[2:]
    if signature[1] != len(body) or body[0] != 0x02:
        raise _BadSignatureError("DER signature malformed")
    r_len = body[1]
    if not 1 <= r_len <= 33:
        raise _BadSignatureError("DER signature malformed")
    r = int.from_bytes(body[2:2 + r_len], "big")
    offset = 2 + r_len
    if body[offset:offset + 1] != b"\x02":
        raise _BadSignatureError("DER signature malformed")
    s_len = body[offset + 1]
    if not 1 <= s_len <= 33 or offset + 2 + s_len != len(body):
        raise _BadSignatureError("DER signature malformed")
    return r, int.from_bytes(body[offset + 2:offset + 2 + s_len], "big")


def _nonce(z, d):
    """确定性 nonce（RFC 6979 风格简化版，保证同密钥同消息签名稳定）。"""
    material = z.to_bytes(32, "big") + d.to_bytes(32, "big")
    counter = 0
    while True:
        candidate = int.from_bytes(
            hashlib.sha256(material + counter.to_bytes(4, "big")).digest(), "big"
        ) % _N
        if candidate > 0:
            return candidate
        counter += 1


def _install_ecdsa_shim() -> None:
    class _Curve:
        name = "nistp256"
        order = _N

    class _SigningKey:
        def __init__(self, string, curve=_Curve):
            if string is None:
                raise ValueError("SigningKey requires an explicit key string")
            if len(string) != 32:
                raise ValueError("P-256 private key must be exactly 32 bytes")
            self._priv = int.from_bytes(string, "big") % _N
            self.curve = curve

        @classmethod
        def generate(cls, curve=_Curve):
            value = int.from_bytes(os.urandom(32), "big") % (_N - 1) + 1
            return cls(value.to_bytes(32, "big"), curve)

        @classmethod
        def from_string(cls, string, curve=_Curve):
            return cls(string, curve)

        def to_string(self):
            return self._priv.to_bytes(32, "big")

        def get_verifying_key(self):
            point = _ec_mul(self._priv, _G)
            if point is None or not _on_curve(*point):
                raise ValueError("invalid P-256 private key")
            return _VerifyingKey(point[0].to_bytes(32, "big") + point[1].to_bytes(32, "big"))

        def sign(self, data):
            z = int.from_bytes(hashlib.sha256(data).digest(), "big")
            k = _nonce(z, self._priv)
            while True:
                point = _ec_mul(k, _G)
                r = point[0] % _N
                if r == 0:
                    break
                s = (z + r * self._priv) * pow(k, -1, _N) % _N
                if s != 0:
                    return _der_encode(r, s)

        sign_deterministic = sign

    class _VerifyingKey:
        def __init__(self, string, curve=_Curve):
            if len(string) != 64:
                raise ValueError("P-256 public key must be exactly 64 bytes")
            x, y = int.from_bytes(string[:32], "big"), int.from_bytes(string[32:], "big")
            if not _on_curve(x, y):
                raise ValueError("public key point is not on the P-256 curve")
            self._point = (x, y)
            self.curve = curve

        @classmethod
        def from_string(cls, string, curve=_Curve):
            return cls(string, curve)

        def to_string(self):
            return self._point[0].to_bytes(32, "big") + self._point[1].to_bytes(32, "big")

        def verify(self, signature, data):
            r, s = _der_decode(signature)
            if not (1 <= r < _N and 1 <= s < _N):
                raise _BadSignatureError("signature value out of range")
            z = int.from_bytes(hashlib.sha256(data).digest(), "big")
            inverse = pow(s, -1, _N)
            point = _ec_add(_ec_mul(z * inverse % _N, _G),
                            _ec_mul(r * inverse % _N, self._point))
            if point is None:
                raise _BadSignatureError("signature yields the point at infinity")
            return point[0] % _N == r

    module = types.ModuleType("ecdsa")
    module.NIST256p = _Curve
    module.SigningKey = _SigningKey
    module.VerifyingKey = _VerifyingKey
    module.BadSignatureError = _BadSignatureError
    module.__doc__ = "analyze_chain.py builtin P-256 shim (stdlib fallback)"
    sys.modules["ecdsa"] = module


try:
    import ecdsa  # noqa: F401
    ECDSA_BACKEND = "python-ecdsa"
except ImportError:
    _install_ecdsa_shim()
    ECDSA_BACKEND = "builtin-p256-shim"


# ============================================================================
# 1) 存档读取
# ============================================================================
class AnalysisError(Exception):
    """存档损坏 / 格式版本不匹配 / 必要字段缺失；信息为中文，供 CLI 直接展示。"""


def load_archive(path: str) -> dict:
    """读取 chain-v2 存档/导出 JSON，仅做结构与版本校验（不做逐块重验）。"""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as error:
        raise AnalysisError(f"存档文件无法读取：{path}（{error}）") from error
    except json.JSONDecodeError as error:
        raise AnalysisError(f"存档 JSON 已损坏，无法解析：{path}（{error}）") from error
    if not isinstance(data, dict):
        raise AnalysisError(f"存档根节点必须是 JSON 对象：{path}")
    version = data.get("format_version")
    if version != EXPECTED_FORMAT_VERSION:
        raise AnalysisError(
            f"存档格式版本不匹配：期望 {EXPECTED_FORMAT_VERSION}，实际 {version!r}（{path}）。"
            "本文件未被修改；如需分析旧格式样本，请先用 "
            "`python server.py --archive <新路径> --fresh` 生成一份 chain-v2 存档后再分析。"
        )
    if "blocks" not in data:
        raise AnalysisError(f"存档缺少必要字段 'blocks'：{path}")
    return data


def load_and_verify(path: str) -> dict:
    """用 persistence.load_state 做完整校验（逐块哈希 + ECDSA 签名）后返回数据。"""
    try:
        import persistence
    except Exception as error:  # noqa: BLE001
        raise AnalysisError(f"无法加载项目既有模块 persistence，无法执行完整校验：{error}") from error
    try:
        return persistence.load_state(path)
    except persistence.PersistenceError as error:
        raise AnalysisError(f"存档完整性校验未通过（{path}）：{error}") from error
