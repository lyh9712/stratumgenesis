# StratumGenesis 语言真实演化模块实现说明

> 阶段：v0.3 · 阶段 C（语言演化）
> 目的：修复评审指出的最致命缺口——**提案只被记录展示，不改变语言能力**。
> 本模块让区块上的扩展提案真正改变 NovScript 解释器：特性注册表 + 求值器派发 + 版本化重放 + 正负双重测试。

---

## 1. 为什么需要这一模块

改造前：`feature_id / specification` 只用于展示与序列化；`novscript/` 中没有
任何原语注册或动态扩展机制。每个「扩展提案」不给解释器增加任何能力，
`demo_code` 只是在创世内核既有语法里跑一段程序——「从零共同创造一门前所未有
的语言」是名义上的。

改造后：一个区块携带 `activation`（本块要激活的新原语名），通过 8 步校验后，
这些原语被**真实注册**进链级语言注册表；后续区块即可调用；历史区块按当时的
语言快照版本化重放，保证「当时的代码按当时的语言版本求值」。

## 2. 核心设计

```
提案文本 ──关键词映射──▶ activation: ("-",) / ("list","head") / ...
                              │
                              ▼
                        Block.activation ──纳入──▶ canonical_bytes ──▶ SHA-256 哈希 + ECDSA 签名
                              │
                              ▼
                      8 步校验流水线（第 5/6 步为语言演化专属）
                              │
                              ▼
                   链级 FeatureRegistry 注册新原语
                              │
                              ▼
              LanguageSnapshot(height, active_features) 存入 ChainStore
                              │
                              ▼
         Evaluator 运行时按注册表派发 → 后续区块可用新原语
         （历史块用 build_registry(snapshot) 重建当时语言版本重放）
```

## 3. 校验流水线（8 步，9 个检查）

| 步 | 阶段 | 说明 |
|---|---|---|
| 0 | signature | ECDSA 签名校验（不变） |
| 1 | structure | 结构与父区块/高度检查（不变） |
| 2 | kernel_compatibility | 创世内核兼容性检查（不变） |
| 3 | poi | PoI mock token 校验（不变） |
| 4 | parse | demo/test_cases 解析校验（不变） |
| 5 | activation | **新增**：activation 中每个原语必须在 BUILTIN_POOL；不得与当前链已激活特性重复；不得是内核原语（+）；为空则跳过 |
| 6 | sandbox | 普通区块的基础沙箱运行校验（原第 5 步；带 activation 的区块跳过，交由第 7 步承担） |
| 7 | language_evolution | **新增**：语言扩展正负测试（见下） |
| 8 | utxo | UTXO 交易校验（不变） |

## 4. 正负测试原理（第 7 步核心）

一次提案必须同时证明「激活后能跑」且「不激活跑不了」，才算真的改变语言：

- **正测试**：用「链级已激活 + 本块 activation」临时注册表运行 `demo_code` 与全部
  `test_cases`，必须全部通过；
- **负测试**：用「链级已激活（不含本块 activation）」注册表运行同一 `demo_code`，
  **必须失败**（任意错误类型）；
- **附加检查**：`demo_code` 词法必须包含本块 `activation` 中的至少一个原语名，
  防止用与提案无关的代码糊弄负测试。

三者同时通过 → 该提案确实改变了语言能力；否则拒绝（`FEATURE_NOT_USED` /
`POSITIVE_DEMO_FAILED` / `NEGATIVE_TEST_PASSED`）。

## 5. 源码变更清单

### 新增
| 文件 | 职责 |
|---|---|
| `novscript/registry.py` | `PrimitiveSpec`、`FeatureRegistry`、`BUILTIN_POOL`（15 个预置原语） |
| `novscript/language.py` | `LanguageSnapshot`（height + active_features）、`from_registry`、`build_registry` |
| `demo_evolution.py` | 语言演化全流程演示 |
| `tests/test_evolution.py` | 12 项演化测试 |
| `EVOLUTION_IMPLEMENTATION.md` | 本文档 |

### 修改
| 文件 | 变更 |
|---|---|
| `novscript/evaluator.py` | `Value` 新增 `Pair` 值类型；`initial_environment(state, registry=None)` 注册表注入；`display_value` |
| `novscript/sandbox.py` | `run_sandbox/evaluate/validate_on_nodes` 增加 `registry=None` 参数；`EvalResult` 新增 `output`；`_public_value` 递归处理 Pair |
| `novscript/lexer.py` | 接受符号型原语名（`-` `*` `%` `//`）作为标识符；负整数字面量行为不变 |
| `novscript/__init__.py` | 导出 registry/language 新接口 |
| `block_model.py` | `Block` 新增 `activation: tuple[str, ...]`，纳入 `canonical_payload`（哈希与签名随之覆盖） |
| `block_validator.py` | 流水线升级为 8 步（新增 activation 校验与正负测试） |
| `chain_store.py` | 链级 `language_registry` + `_language_snapshots`；`append_main` 注册激活；`branch_active_features` |
| `epoch_manager.py` | `EpochSnapshot` 新增 `active_features`（纪元结束时链级语言状态） |
| `persistence.py` | `FORMAT_VERSION` 升级 `chain-v2`；区块序列化/反序列化同步 `activation` |
| `server.py` | 提案关键词 → activation 映射；`/chain-state` 返回 `current_active_features`、每区块 `activation`/`language_features`、纪元 `active_features`；`/eval-novscript` 使用链级注册表 |

## 6. 预置原语池（BUILTIN_POOL，15 个）

| 类别 | 原语 | 说明 |
|---|---|---|
| 算术扩展 | `-` `*` `//` `%` | 整数二元运算，与内核 `+` 同风格的严格求值 |
| 比较 | `eq` `lt` `gt` | 整数比较，返回 1/0（布尔用整数表示） |
| 条件 | `if` | 惰性选择分支：未选中的分支不求值 |
| 列表 | `list` `cons` `head` `tail` `nil?` `length` | 用嵌套 Pair 表示列表，nil 用 `InternalNil`，无需改 parser |
| 输出 | `echo` | 把参数显示形式写入沙箱输出缓冲区（`EvalResult.output`） |

## 7. 验收结果

```text
python demo_evolution.py          # 全流程演示通过
python -m unittest discover -s tests -v   # 102 tests OK（90 旧 + 12 新）
python -m compileall -q .         # 编译检查通过
```

端到端验证（server API）：
- 提交「减法扩展」提案 → `success=true`，链高 +1，`current_active_features=['-']`；
- `POST /eval-novscript {code: "(- 10 3)"}` → `value=7`（链级注册表已生效）；
- 重复提交「再激活减法」→ `activation` 阶段 `DUPLICATE_FEATURE` 拒绝，入休眠分支；
- 存档保存→加载：注册表、逐高度语言快照、求值能力完整重建（`chain-v2` 格式）。

## 8. 暂未实现清单（本模块边界）

- **语法级扩展**：本版只做原语级注册，parser/AST 结构不变（`if` 为特殊原语而非特殊形式）；
- **字符串/布尔值类型**：布尔用 0/1、nil 用 InternalNil 表示；
- **分支级完整注册表演化**：休眠分支只记录自身额外激活集（`branch_active_features`），
  未实现分支上链后的语言合并规则；
- **真实 LLM 提案生成**：activation 仍由关键词映射（mock）；
- **P2P 网络**、**磁盘级语言快照**（快照从链数据重放重建，不单独落盘）、
  **可交易代币**：均不在本模块范围。

## 9. 已知限制与风险

1. **历史存档不兼容**：`canonical_bytes` 纳入 activation 后，旧 `chain-v1` 存档
   的区块哈希/签名全部失效，加载被拒——需 `python server.py --fresh` 重建演示链；
2. **符号原语名的词法边界**：`(-3)` 会被识别为负整数字面量而非减法应用
   （与 Lisp 惯例一致，需空格 `(- 3)` 调用原语）；
3. **正负测试的成本**：带 activation 的区块每次校验需多次沙箱运行（正 demo +
   正全部 test_cases + 负 demo），区块越多运行越慢；当前单机规模可接受；
4. **演示代码仍是 mock 映射**：提案文本 → activation 是关键词映射，真实 LLM
   提案生成留待后续阶段。
