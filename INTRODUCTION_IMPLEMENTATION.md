# StratumGenesis 引种提案（Inoculation Proposal）机制实现说明

> 阶段：v0.3 · 阶段 D（纪元作用域语言 + 引种）
> 目的：把语言作用域从「链级只增不减」改为「纪元内有效」——跨纪元默认失忆，
> 引种 = 在更早纪元已出现过、本纪元重新通过 `activation` 激活的提案。
> 失忆是本阶段的核心玩法，不是 bug。

---

## 1. 为什么需要这一机制

阶段 C 之后，`ChainStore.language_registry` 是**链级单一注册表、只增不减**，
`epoch_manager` 的 `active_features` 跨纪元累计——特性一旦激活就永久继承。
这与设计白皮书 §7.6「新纪元默认不继承旧纪元特性，需引种」直接矛盾，
导致「引种」概念在实现上空转：代码里没有任何地方能表达"这个特性曾激活过、
但现在不可用、需要重新引入"。

阶段 D 的语义变更：

- 每个纪元的语言基线 = 创世内核（扩展原语集为空）；
- 一个原语要在某高度可用，必须**在本纪元内**被某个区块的 `activation` 激活；
- 「引种」= 在更早纪元已出现过、本纪元重新激活的提案；
- 「新特性」= 历史上首次被激活的原语；
- 纪元一翻，上一纪元的扩展原语默认失效（**失忆**）。

## 2. 两层注册表

| 层 | 载体 | 语义 | 用途 |
|---|---|---|---|
| 历史层（provenance） | `ChainStore.language_registry` | 链上曾经激活过的全部扩展原语，只增不减 | 判定「引种 vs 新特性」；对外 `cumulative_active_features` / `ever_active_features()` |
| 纪元层 | `ChainStore.epoch_registry` | 当前纪元已激活的原语；纪元首块（`height % 100 == 0` 且非创世）重置为空 | 语言可用的权威依据；`epoch_active_features()` |

`append_main` 对 activation 中每个名字：

- 历史层已有 → **引种**：历史层不变（**不抛** already registered，否则含引种块的
  存档无法重放）；纪元层照常累积；
- 历史层没有 → **新特性**：注册进历史层；纪元层照常累积。

`_language_snapshots[height]` 记录**纪元作用域**快照（纪元基线 + 本纪元累积），
是版本化重放的权威依据。休眠分支 `branch_active_features` 语义不变（只记自身累积），
不触碰两层注册表。

## 3. 校验：作用域收窄 + 语义化报错

「失忆」语义由既有正/负测试机制自然产生，前提是把基准注册表从链级换成
纪元作用域。四处基准点（`block_validator.py`）：

| 位置 | 阶段 C（链级） | 阶段 D（纪元作用域） |
|---|---|---|
| `_check_activation` | `store.language_registry.snapshot()` | `_epoch_registry_for(store, block.height).snapshot()` + `UNIMPORTED_FEATURE` 检查 |
| `_check_sandbox`（普通区块） | `store.language_registry` | `_epoch_registry_for(store, block.height)` |
| `_registry_with`（正测试基准） | `store.language_registry` + 本块 activation | 候选纪元生效集 + 本块 activation |
| 负测试基准 | `store.language_registry` | `_epoch_registry_for(store, block.height)` |

`_epoch_registry_for(store, height)`：候选与当前主链同纪元 → 取纪元层；
候选为纪元首块（跨纪元边界）→ 空注册表（新纪元从内核起步）。

### 错误码表

| 错误码 | 触发条件 | 语义变化 |
|---|---|---|
| `KERNEL_FEATURE_CONFLICT` | activation 名字在内核原语集 | 不变 |
| `UNKNOWN_FEATURE` | activation 名字不在 BUILTIN_POOL | 不变 |
| `DUPLICATE_FEATURE` | 名字**在本纪元**已激活 | 收窄：跨纪元重新激活从「拒绝」变为「合法引种」；消息改为 "is already active in the current epoch" |
| `UNIMPORTED_FEATURE` | demo/test_cases 引用「更早纪元激活过、本纪元未引种、且不在本块 activation 中」的名字 | **新增**；消息形如 `feature '-' belongs to epoch 0 and has not been inoculated in the current epoch (epoch 1); add it to activation to inoculate` |
| `FEATURE_NOT_USED` | demo 未引用本块 activation 中任何原语 | 不变 |

`UNIMPORTED_FEATURE` 的判定顺序（`_unimported_name`）：内核原语 → 跳过；
非预置池标识符（如绑定名）→ 跳过；本块 activation 中的名字 → 正在引种，跳过；
本纪元已激活 → 可用，跳过；其余历史曾激活过的名字 → 违规。

## 4. 纪元快照（epoch_manager）

`EpochSnapshot` 的 `active_features` 值语义由「自创世累计」改为「该纪元内有效」，
并新增三字段：

- `epoch_base_features`：该纪元开篇基线 = 首块引种集（首块无 activation 则为空）；
- `epoch_new_features`：该纪元历史首次激活的原语（引种不算新特性）；
- `cumulative_active_features`：截至该纪元末的历史累计（**保留旧语义**，
  供老消费方迁移）。

`scan_chain` 按纪元重放主链累积四元组，与 `append_main` 的纪元层运行态同源，
保证归档快照与运行态一致。

## 5. API 契约（v0.3 阶段 D）

只追加字段、不重命名、不删除；旧字段值语义变更以 `@deprecated` 标注：

- `blocks[].activation`：不变（本块激活/引种的原语名）。
- `blocks[].language_features`：语义 = 该高度当时可用的语言集（纪元作用域）。
- `epochs[].active_features`：⚠️ 值语义变更（@deprecated）：由「自创世累计」改为
  「该纪元内有效」；旧语义见 `epochs[].cumulative_active_features`。
- `epochs[].epoch_base_features` / `epoch_new_features` / `cumulative_active_features`：新增。
- 顶层 `current_active_features`：⚠️ 值语义变更（@deprecated）：由「链级累计」改为
  「当前纪元内有效」；新增顶层 `current_epoch_base_features` 与 `cumulative_active_features`。

## 6. 已知限制

- 引种 provenance 从历史层推导，不引入链上引种记录字段：跨纪元「曾激活过」的
  事实以 `first_activation_epoch()` 线性扫描主链获得（O(链高)），长链上可优化为索引。
- 同纪元重复激活仍被拒绝；「同一纪元内多次引入同一原语的不同实现」不在本版本
  支持范围内（单一实现池 BUILTIN_POOL）。
- 预沉积链（无 activation 的普通内核块）在新规则下不受影响：`_unimported_name`
  只对预置池标识符敏感，内核代码与绑定名均跳过。
- 失忆只作用于扩展原语；创世内核（`+`、bind、lambda 等）永不失忆。
- 本机制仍是单机内存仿真；真实多节点、真实 LLM 提案、真实 tokenizer 不在本版本范围。

## 7. 验收

- `tests/test_epoch_scope.py`：10 项（跨纪元失忆、引种成功、同纪元重复拒绝、
  跨纪元再引种、重放一致性、分类正确、语义化报错、API 契约、边界 99/100/101、
  预沉积回归）。
- `python -m unittest discover -s tests` 全绿；`python -m compileall -q .` 退出码 0；
  `python demo_evolution.py` exit 0。
