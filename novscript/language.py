"""NovScript 语言快照：绑定「区块高度 → 当时已激活的语言特性」。

语言快照是版本化重放的核心：每个主链区块保存一份它当时的已激活原语
集合（active_features），重放历史区块时用其快照重建注册表，即可保证
「当时的代码按当时的语言版本求值」，不受后续语言演化影响。

快照本身只记录原语名集合（frozenset），实现定义统一从 BUILTIN_POOL 取，
因此快照可确定性序列化、跨实现重建。
"""

from __future__ import annotations

from dataclasses import dataclass

from .registry import BUILTIN_POOL, FeatureRegistry, PrimitiveSpec


@dataclass(frozen=True)
class LanguageSnapshot:
    """某一高度上链级语言已激活特性的不可变快照。"""

    height: int
    active_features: frozenset[str]

    @classmethod
    def from_registry(cls, registry: FeatureRegistry, height: int) -> "LanguageSnapshot":
        """从注册表构造快照（记录注册表当前已激活原语名集合）。"""
        return cls(height=height, active_features=registry.snapshot())

    @classmethod
    def build_registry(cls, snapshot: "LanguageSnapshot") -> FeatureRegistry:
        """从快照重建注册表：实现定义统一取自 BUILTIN_POOL。

        重建结果与当初的注册表在行为上等价（实现来自同一预置池），
        保证跨进程/跨存档重放的确定性。
        """
        specs: list[PrimitiveSpec] = []
        for name in sorted(snapshot.active_features):
            spec = BUILTIN_POOL.get(name)
            if spec is None:
                # 快照记录了预置池外的名字：视为数据损坏（防御性兜底）。
                raise NameError(f"snapshot references unknown feature: {name}")
            specs.append(spec)
        return FeatureRegistry.from_specs(specs)
