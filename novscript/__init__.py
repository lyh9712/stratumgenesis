"""StratumGenesis NovScript 最小原型公共接口。"""

from .ast import Program
from .language import LanguageSnapshot
from .parser import parse
from .registry import BUILTIN_POOL, FeatureRegistry, KERNEL_PRIMITIVES, PrimitiveSpec
from .sandbox import EvalResult, SandboxLimits, ValidationReport, evaluate, run_sandbox, validate_on_nodes

__all__ = [
    "BUILTIN_POOL",
    "EvalResult",
    "FeatureRegistry",
    "KERNEL_PRIMITIVES",
    "LanguageSnapshot",
    "PrimitiveSpec",
    "Program",
    "SandboxLimits",
    "ValidationReport",
    "evaluate",
    "parse",
    "run_sandbox",
    "validate_on_nodes",
]
