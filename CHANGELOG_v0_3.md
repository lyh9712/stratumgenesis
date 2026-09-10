# StratumGenesis · v0.3 版本变更日志

> 版本：v0.3（阶段 A：git 基线 + 磁盘持久化与链数据导出）
> 日期：2026-09-09
> 基线：v0.2（前后端打通 · 单机内存仿真 · 72 项测试）

## v0.3 · 阶段 A

### 版本控制基线

- 在 `E:\my-code\tokenmint` 建立本项目独立 git 仓库（父目录为无关项目的 monorepo，不在此仓库内混入其他项目文件）。
- 新增 `.gitignore`：忽略 `__pycache__/`、`*.pyc`、`server.log`、`data/`、`*.tmp`。
- 提交 v0.2 归档基线并打标签：`git tag v0.2`（commit `59bfe1b`）。
- 已在 `CHANGELOG_v0_2.md` 末尾追加基线记录行。

### 磁盘持久化与链数据导出

- 新增 `persistence.py`：
  - 确定性 JSON 存档格式（`format_version=chain-v1`）；
  - 落盘最小权威状态：主链全部区块 + 休眠分支（分支标识 + 区块序列）+ 矿工注册表（含私钥）+ 拒绝原因；
  - UTXO 账本与纪元快照**不序列化**，加载时从主链按既有规则确定性重建（防漂移 + 天然校验）；
  - 原子写入（临时文件 + `os.replace`）；
  - 逐区块 SHA-256 哈希校验；损坏/版本不匹配拒绝加载；
  - `save_state` / `load_state` / `rebuild_store` / `export_chain` / `miners_to_list` / `miners_from_list` / CLI `python persistence.py export <path>`。
- `server.py` 接入：
  - 启动策略：有存档则加载继续（不再预沉积）；无存档维持创世 + 预沉积 102 并立即落盘；
  - `--fresh` 忽略存档重建演示链；`--export <path>` 校验并导出存档后退出；
  - 每次链状态变更（成功上链 / 候选入休眠分支）自动保存，失败仅打印中文警告不影响操作；
  - 存档缺失/损坏/版本不匹配：中文明确报错并拒绝启动，提示 `--fresh`；
  - 三个既有 API 响应契约不变；`chain-state.miners` 数组改为按公钥稳定排序输出。
- 新增 `tests/test_persistence.py` 8 项测试（roundtrip 等值、HTTP 一致性、损坏拒绝、--fresh、导出）。

### 文档

- 新增 `PERSISTENCE_IMPLEMENTATION.md`：格式、format_version、保存/恢复策略、为何账本与快照重建而非序列化、私钥持久化安全边界、已知限制。
- 新增 `CHANGELOG_v0_3.md`（本文件）。
- 更新 `API_SPEC.md`、`使用说明.md`：存档路径、`--fresh`、导出方式。
- 更新 `ARCHIVE_FILE_MANIFEST.md`、`REFERENCE_DOCS_INDEX.md` 登记新文件。

### 验证结果

- 全量回归：`python -m unittest discover -s tests -v` → **80 项全部通过，失败 0**（72 原有 + 8 新增）。
- 字节码检查：`python -m compileall -q .` 通过。
- 手工验证：首次启动 102 → `/propose` 后 103 → 停止重启加载存档仍为 103（提案仍在）→ `--fresh` 回到 102；导出 CLI 产出 `chain-v1` 完整副本。

## v0.3 · 阶段 B（mock 纪元摘要：确定性生成 + 加权投票）

### 纪元摘要模块

- 新增 `epoch_summary.py`：
  - 数据模型 `SummaryCandidate` / `EpochSummary`（候选文本、模板名、生产者、权重、胜者、最终文本、方法标签 `mock-rule-v1`、状态、平票标记）；
  - 三套确定性规则模板：`keyword-top`（特性关键词词频 Top3）、`contributor-distribution`（贡献者分布）、`first-last-narrative`（首末特性串讲）；
  - 复用 `weight_calculator.calculate_historical_weights`（仅主链、截止纪元边界）加权投票；平票按模板名排序取首并记录 `tie_occurred`；
  - 全程 mock：无真实 LLM、无网络；为未来 LLM 接入预留替换点（详见 EPOCH_SUMMARY_IMPLEMENTATION.md §5）。
- `epoch_manager.py`：`EpochSnapshot` 追加 `summary` / `summary_status` 字段（不删不改既有字段）；`scan_chain` 在边界（height % 100 == 0）确定性 finalize；新增 `_summary_chain` 摘要链（按纪元顺序，为「大断层事件」留钩子）。
- 与阶段 A 持久化协同：摘要**不序列化进存档**，save→load 由主链重放确定性重建，逐字段一致（新增测试断言）。

### 接口与前端

- `GET /chain-state`：`epochs[i]` 追加 `summary`（已归档纪元 finalized / 未封口 null）与 `summary_status`；顶层追加 `summary_chain`（只追加，不改既有字段名）。
- `index.html`：已归档纪元标签下新增可折叠摘要卡（原生 `<details>`，展示胜者/最终文本/候选权重/平票标记）；纯追加式，不动既有动画与交互。

### 阶段 A 遗留小修（监督验收发现）

1. `persistence.load_state()` 加载时逐块补验 ECDSA 签名（跳过创世块），仅篡改签名的存档现会被拒绝加载（错误含「签名校验失败」）。
2. 全部文档编译检查命令统一为 `python -m compileall -q .`（修复 PowerShell 不展开 `*.py` 通配符问题，已实测退出码 0）。

### 验证结果

- 全量回归：`python -m unittest discover -s tests` → **90 项全部通过，失败 0**（80 原有 + 10 新增）。
- 字节码检查：`python -m compileall -q .` 退出码 0。
- 手工验证：`--fresh` 启动后 `/chain-state` 纪元 0 含 finalized 摘要（三候选 + 胜者）、纪元 1 为 pending；提案推进主链后纪元 1 仍 pending（跨边界行为正确）；重启（不加 --fresh）摘要字段与重启前一致。

## v0.3 · 阶段 C（语言真实演化：提案真的改变语言）

> 背景：专业评审指出项目最致命缺口——提案的 `feature_id/specification` 只用于展示
> 与序列化，解释器没有任何原语注册或动态扩展机制，「从零共同创造一门前所未有的
> 语言」是名义上的。本阶段让扩展提案真正改变 NovScript 能力。

### 核心机制

- 新增 `novscript/registry.py`：
  - `PrimitiveSpec`（name/impl/description）+ `FeatureRegistry`（register/has/get/snapshot/all_specs）；
    **arity 不写入元数据**（收尾补丁 C 已删除装饰性 `arity` 字段，参数约束由各实现自查抛 ArityError）；
  - `BUILTIN_POOL` 预置原语池 15 个：算术 `- * // %`、比较 `eq/lt/gt`、惰性条件 `if`、
    列表 `list/cons/head/tail/nil?/length`、输出 `echo`；布尔用 0/1、nil 用 InternalNil；
  - 内核原语（`+ bind lambda`）不可经注册表激活。
- 新增 `novscript/language.py`：`LanguageSnapshot(height, active_features)` +
  `from_registry` / `build_registry`（快照只记名字集合，实现统一取自预置池，可跨进程重建）。
- `novscript/evaluator.py`：`Value` 新增 `Pair`；`initial_environment(state, registry=None)`
  先注册内核 `+` 再注入注册表原语，未注入时行为与改造前完全一致；新增 `display_value`。
- `novscript/sandbox.py`：`run_sandbox/evaluate/validate_on_nodes` 增加 `registry=None`；
  `EvalResult` 新增 `output`（echo 输出缓冲区）；`_public_value` 递归展开 Pair。
- `novscript/lexer.py`：接受符号型原语名（`-` `*` `%` `//`）为标识符；负整数字面量行为不变。
- `block_model.py`：`Block` 新增 `activation: tuple[str, ...]`，纳入 `canonical_payload`
  （哈希与 ECDSA 签名随之覆盖）。
- `block_validator.py`：流水线升级为 8 步 9 检查——新增第 5 步特性激活校验（预置池内、
  不与链级已激活重复、非内核原语）与第 7 步语言扩展正负测试（正：激活后 demo+test_cases
  全过；负：不激活时同一 demo 必失败；附加：demo 词法须含激活原语名）。
- `chain_store.py`：链级 `language_registry` + 逐高度 `LanguageSnapshot`；`append_main`
  追加成功后将 activation 真实注册并生成快照；休眠分支不污染链级注册表（提供
  `branch_active_features` 记录分支自身激活集）。
- `epoch_manager.py`：`EpochSnapshot` 新增 `active_features`（该纪元结束时链级语言状态）。
- `persistence.py`：`FORMAT_VERSION` 升级 `chain-v2`，区块序列化同步 `activation`；
  加载时由主链重放重建注册表与快照（与账本/纪元同一哲学）。
- `server.py`：提案关键词 → activation 映射（减法/列表/条件等）；`/chain-state` 返回
  `current_active_features`、每区块 `activation`/`language_features`、纪元 `active_features`；
  `/eval-novscript` 默认按「创世内核 + 当前链级注册表」执行。

### 演示与测试

- 新增 `demo_evolution.py`：创世仅内核 → 激活 `-` → 历史块版本化重放 → 再激活
  `list/head` → 重复激活被拒 → 打印语言演化时间线。
- 新增 `tests/test_evolution.py` 12 项：注册后可调用、未激活 NameError、未知原语拒绝、
  重复激活拒绝、正负测试证明演化、demo 不引用新特性拒绝、版本化重放一致、休眠分支
  不污染链级注册表、activation 纳入哈希与签名。

### 验证结果

- 全量回归：`python -m unittest discover -s tests` → **102 项全部通过，失败 0**（90 原有 + 12 新增）。
- 字节码检查：`python -m compileall -q .` 退出码 0。
- 端到端：`demo_evolution.py` 全流程通过；HTTP 层「减法扩展」提案 → `success=true`、
  `current_active_features=['-']`、`/eval-novscript (- 10 3)` → 7；重复激活进休眠分支；
  存档保存→加载后注册表、逐高度快照、求值能力完整重建。

### 兼容性说明

- **旧存档不兼容**：canonical 纳入 activation 后旧 `chain-v1` 存档哈希/签名失效，
  启动需 `python server.py --fresh` 重建演示链（加载会中文报错并提示）。
- 词法边界：`(-3)` 是负整数字面量，`(- 3)` 才是减法应用（与 Lisp 惯例一致）。

### 阶段 C 收尾补丁（监督验收 A～F）

1. **A 输出上限强制**：`LimitsState` 新增 `max_output_chars`/`output_chars` 计账与
   `append_output()`；`echo` 改走该方法累计字符，超限抛既有 `ResourceLimitError`
   （"maximum output characters exceeded"），不新增错误类型。新增
   `tests/test_sandbox_limits.py`：500 条 echo 超 4096 → `ok=False,
   error_type=="ResourceLimitError"`；恰好等于上限 100 → 成功且输出完整。
2. **B 宿主递归归类**：`_public_value` 的 Pair 展开改右链迭代（长列表不随长度递归）；
  沙箱入口新增 `builtins.RecursionError` 防御层，统一映射为
   `ResourceLimitError("maximum structure depth exceeded")`，不再把
   "maximum recursion depth exceeded" 上报为 SandboxError。2000 元素列表断言稳定
   返回且消息不含宿主细节。
3. **C arity 元数据**：删除 `PrimitiveSpec.arity` 装饰性字段（全项目无读取点、
   真实约束由实现自查），避免未来校验逻辑误信；文档同步（CHANGELOG/EVOLUTION）。
4. **D 文档同步**：`PERSISTENCE_IMPLEMENTATION.md` 与 `ARCHIVE_FILE_MANIFEST.md`
   更正为 chain-v2 并说明升级原因；`BLOCK_LAYER_PROTOTYPE_IMPLEMENTATION.md`
   顶部标注 v0.2 历史阶段（现行 9 检查见 EVOLUTION_IMPLEMENTATION.md）；
   `ARCHIVE_FILE_MANIFEST.md`/`REFERENCE_DOCS_INDEX.md` 登记阶段 C 文件。
5. **E 旧存档非破坏**：拒绝加载时提示改用 `--archive <新路径>`；`--fresh` 重建前
   将旧存档重命名为 `<原名>.bak-<旧format_version>` 保留不删。新增测试：fresh 后
   `.bak` 保留、拒绝加载时原文件未动（`tests/test_persistence.py` 追加）。
6. **F 持久化×语言演化耦合**：新增 `tests/test_persistence_evolution.py`——
   save→load+rebuild 后断言高度/区块哈希一致、各高度语言快照一致、
   激活后 `(- 10 3)`=7、未激活高度同一 demo 仍 NameError。

### 阶段 C 收尾验证结果

- 全量回归：`python -m unittest discover -s tests` → **110 项全部通过，失败 0**。
- 字节码检查：`python -m compileall -q .` 退出码 0。
- 手工验证：`python server.py --fresh` 启动 → `/chain-state` 含 activation 字段与
  纪元摘要共存 → 提交「减法扩展」提案通过 9 检查 → 重启（不加 --fresh）激活状态与
  语言快照仍在；旧 chain-v1 存档被保留为 `.bak-chain-v1`。

## 尚未实现（沿用 v0.2 清单，本阶段未触碰）

- 真实 LLM 纪元摘要（当前为 mock-rule-v1 规则模板）；引种提案；大断层事件；
- P2P 网络、真实 tokenizer、真实 LLM；
- 增量归档、加密存档、校验和文件、密钥托管；
- **语法级语言扩展**（本阶段只做原语级注册，parser/AST 不变）；
- 任何可交易代币或现实金融功能。
