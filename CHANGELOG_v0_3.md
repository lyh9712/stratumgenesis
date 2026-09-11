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

## v0.3 · 阶段 D（纪元作用域语言（失忆）+ 引种提案）— ⚠️ BREAKING（字段值语义变更）

> 背景：阶段 C 的 `language_registry` 是链级单一注册表、只增不减，特性一旦激活
> 就永久继承——与白皮书 §7.6「新纪元默认不继承旧纪元特性，需引种」矛盾，
> 「引种」在实现上空转。本阶段把语言作用域改为**纪元内有效**：跨纪元默认失忆
> （核心玩法），引种 = 在更早纪元已出现过、本纪元重新激活的提案。

### 核心机制

- `chain_store.py`：两层注册表——
  - **历史层** `language_registry`（provenance，只增不减）：判定「引种 vs 新特性」，
    对外 `cumulative_active_features`/`ever_active_features()`；
  - **纪元层** `epoch_registry`（新增）：当前纪元已激活集，纪元首块
    （`height % 100 == 0` 且非创世）重置为空；`epoch_active_features()`；
  - `append_main`：历史层已有 → 引种（**不抛** already registered，否则含引种块
    存档无法重放）；历史层没有 → 新特性注册进历史层；纪元层照常累积；
    `_language_snapshots[height]` 记录**纪元作用域**快照。
  - 新增只读查询：`epoch_active_features()`、`ever_active_features()`、
    `epoch_of_height()`、`first_activation_epoch()`；`language_snapshot_at`/
    `current_language_snapshot` 语义升级为纪元作用域。
- `block_validator.py`：四处基准注册表从链级换成纪元作用域（`_epoch_registry_for`：
  同纪元取纪元层、跨纪元首块为空）——`_check_activation`、`_check_sandbox`（普通区块）、
  `_registry_with`（正测试）、负测试基准；错误码：`DUPLICATE_FEATURE` 收窄为
  「本纪元已激活」（消息 "is already active in the current epoch"），
  **新增 `UNIMPORTED_FEATURE`**（demo/test_cases 引用更早纪元激活过、本纪元未引种、
  且不在本块 activation 中的原语；消息形如 `feature '-' belongs to epoch 0 and has
  not been inoculated in the current epoch (epoch 1); add it to activation to inoculate`）。
- `epoch_manager.py`：`EpochSnapshot.active_features` 值语义由「自创世累计」改为
  「该纪元内有效」；新增 `epoch_base_features`（首块引种集）、`epoch_new_features`
  （本纪元历史首次）、`cumulative_active_features`（保留旧语义）；`scan_chain`
  按纪元重放累积四元组。
- `server.py`：只追加字段——顶层 `current_epoch_base_features`、`cumulative_active_features`；
  `epochs[]` 追加 `epoch_base_features`/`epoch_new_features`/`cumulative_active_features`；
  `current_active_features` 与 `epochs[].active_features` 值语义变更并标注
  `@deprecated`（旧语义由累计字段承接）。
- `FORMAT_VERSION` 保持 `chain-v2`：不新增/修改 Block 字段，未动 canonical_bytes；
  引种 provenance 从历史层推导，不引入链上引种记录字段；旧存档重放不变严。

### 文档

- 白皮书 §7.6 新增 `7.6.1 引种提案（Inoculation Proposal）操作说明`（失忆原因、
  引种怎么提、依赖/顺序、纪元开篇引种玩法、与摘要/大断层的关系）。
- 新增 `INTRODUCTION_IMPLEMENTATION.md`（两层注册表、作用域校验、错误码表、已知限制）。
- 更新 `EVOLUTION_IMPLEMENTATION.md`（顶部标注阶段 D 修订 + 第 4 节「作用域与引种」）、
  `API_SPEC.md`（新增「v0.3 阶段 D 契约变更」一节）、`使用说明.md`。
- `ARCHIVE_FILE_MANIFEST.md`、`REFERENCE_DOCS_INDEX.md` 登记新文件。

### 测试

- 新增 `tests/test_epoch_scope.py` 10 项：跨纪元失忆（`UNIMPORTED_FEATURE`）、
  引种成功、同纪元重复拒绝、跨纪元再引种合法、重放一致性（save→load+rebuild）、
  分类正确（base/new/cumulative）、语义化报错消息、API 契约字段、边界 99/100/101、
  预沉积链回归（普通内核块不误拒）。

### 验证结果

- 全量回归：`python -m unittest discover -s tests` → **120 项全部通过，失败 0**
  （110 原有 + 10 新增；既有测试无一改动，语义变更经评估不触碰既有断言）。
- 字节码检查：`python -m compileall -q .` 退出码 0。
- 手工验证：`--fresh` 启动 → 提交激活 `-` 提案 → 推进链跨过 200 边界 →
  提交使用 `-` 的普通提案被 `UNIMPORTED_FEATURE` 拒绝 → 带 `activation=["-"]`
  的引种提案通过；`/chain-state` 新字段齐全、旧字段语义符合文档。

## v0.3 · 阶段 E（分叉兑现：休眠分支升级 / 主链重组 reorg）

> 背景：落选候选原先只存进 `sleeping_branches` 后永久沉睡，「分叉 = 语言分化」（白皮书 §9）
> 只是名词。本阶段让休眠分支**可升级为主链**，并保证语言/账本/纪元状态随之正确改写。
> 设计说明：`BRANCH_PROMOTION_DESIGN.md`；实现说明：`BRANCH_PROMOTION_IMPLEMENTATION.md`。

### 机制

- `chain_store.py`：新增 `inspect_promotion` / `branch_head_candidates` / `promote_branch`
  （S1 链回溯 → S2 结构资格 E1–E6 → S3 在**全新 scratch ChainStore** 上重放「保留前缀 →
  分支链逐块完整校验（E7）→ 休眠迁移（其余休眠 + 旧后缀按高度升序入休眠）」→
  S4 **单临界区原子换入**七个内部引用）；失败路径只丢弃 scratch，live 状态零变化（I-11）。
- `block_validator.py`：新增纯函数 `check_promotion_eligibility`（E1–E6，只读）；
  E7 由 scratch 上的既有 9 检查流水线承担，错误码（UTXO_INVALID / UNIMPORTED_FEATURE 等）原样透传。
- **冻结约束**：只在**当前未归档纪元内**重组（不触碰已归档区块与 finalized 摘要）；
  被替换的旧主链后缀**移入休眠分支、不丢失**；派生状态（账本/纪元快照/语言注册表/逐高度快照）
  **一律由新主链重放重建**，不做反向补丁。
- **`ever_active` 语义精确化**：在 append 序列上单调不减；**重组是重推导事件，允许收缩**
  （与「存档 = 主链函数」的纯重放哲学一致；未引入高水位线，`FORMAT_VERSION` 保持 `chain-v2`）。
- `server.py`：新增 `GET /branches` 与 `POST /promote-branch`（按 `head_block_hash` 定位分支）；
  新增仅保护变更类入口（`/propose`、`/promote-branch`）的状态锁；既有三个 API 只追加字段。

### 测试

- 新增 `tests/test_branch_promotion.py` 18 项：纯接续（高度 103 平票双分支）、后缀替换、
  深/收缩/延伸重组、四类资格拒绝、UTXO 与语言失效语义拒绝、`ever_active` 收缩后重激活、
  跨纪元摘要冻结与 pending 重算、**对合性**（提升分支再提升旧后缀可复原）、持久化 round-trip
  逐项等价、原子性总检与 API 契约超集兼容。

### 验证结果

- 全量回归：`python -m unittest discover -s tests` → **276 项全部通过，失败 0**；
  `python -m compileall -q .` 退出码 0。
- 监督者独立实测（不经 HTTP、直接调库）：造平票双分支 → promote 后 tip 变为分支块、
  旧块降级入休眠、**区块数与铸币量守恒**；再提升旧后缀**完全复原（对合）**；
  提升主链块 → `PROMOTION_NOT_FOUND`；伪造跨归档纪元的休眠块 →
  `PROMOTION_ARCHIVED_EPOCH` 且状态逐项不变。

## v0.3 · 上线批次（许可 / 门面 / 部署 / 静态展馆 / 分析器）

### 许可与合规（新增）

- `LICENSE`（**PolyForm Noncommercial 1.0.0**，明文禁止商业使用）、
  `LICENSE-SCOPE.md`（中文边界：允许个人/教学/研究/免费公开 hub；禁止收费、订阅、广告变现、
  商业 SaaS；部署者义务与免责重申）、`NOTICE`（署名、依赖声明仅 `ecdsa`(MIT)、非加密货币声明）。
- ✅ **三处许可占位符已于 2026-09-10 定稿填入**：版权所有人 **鹿拾（Yuanhao Lu）**、
  商业授权联络 <https://github.com/luyuanhao>、仓库 <https://github.com/luyuanhao/stratumgenesis>。
  fork 后改动署名或仓库地址时，须重新执行 `PUBLISH_CHECKLIST.md` §1.1 的残留占位符扫描。
- 修正一处合规事实错误：`ecdsa` 的许可为 **MIT**（依已安装包元数据核实），此前 `NOTICE` 误写为 Apache 2.0。

### 仓库门面与依赖（新增/修改）

- `README.md`（新）：一句话定位、30 秒原理、三种上手路径、「它不是什么」（无代币/无金融价值/
  PoI 为 mock/非生产）、测试命令、许可声明。
- `start.bat`（新，Windows 一键启动）：纯 ASCII + CRLF（避免 CP936 下注释被当命令执行导致块截断）、
  解释器探测（排除 AppInstaller 的 `python.exe` 符号链接）、缺 `ecdsa` 时提示安装、自动打开页面。
- `requirements.txt`（新）：`ecdsa>=0.19`（项目唯一第三方依赖）。
- `.gitignore`：追加 `.codebuddy/`、`.workbuddy/`（本地 AI 工具目录）与 `*.bak-*`。

### 部署与静态展馆

- `export_public.py`（新）：导出可公开的 `chain_state.json`；**写盘前断言结果不含 `private_key`**，
  否则拒绝写出并非零退出（存档含明文私钥，公开发布必须剥离）。
- `index.html`：新增**运行模式探测** —— 后端不可用时自动降级读取同目录 `chain_state.json`，
  进入「只读展馆」（禁用提案入口并给出中文说明）；正常后端模式行为不变。
- `chain_state.json`（已入库）：只读展馆的静态链快照（**已验证零私钥**）；发布前用最新代码刷新。
- `Dockerfile` / `DEPLOY.md` / `render.yaml`（新）：一键部署路径与「部署者须知」
  （服务端持私钥 = 公网可冒充、垃圾提案防护、免费层冷启动、合规义务、Actions 定时归档）。

### 离线链分析器与跨 AI 创造力指标

- `analyze_chain.py`（新）+ `EXPERIMENT_METRICS.md`：把 chain-v2 存档转成可复现的实验指标报告。
  签名重验统一走 `crypto_key.verify_block_signature`；**已移除早期内嵌的手写 ECDSA 回退**
  （未通过独立交叉校验的实现不得作为承重组件）；缺 `ecdsa` 时明确跳过并在 JSON 标注
  `skipped_no_ecdsa`，**不伪造结果**；Windows GBK 控制台经 UTF-8 容错 + 字符替换后不再崩溃。
- **跨 AI 创造力指标（`--by-model`）**：按 `blocks[].poi.model_metadata` 分组统计 —— 接受率、
  **引种留存率**（首激活特性在更晚纪元被引种的次数）、半衰期（首激活纪元 → 最后被引种纪元的
  跨度中位数）、原语偏好、组合新颖度、矿工/模型的多挂关系；样本量不足时置
  `sample_size_warning`（**n/a 是设计内合法状态，禁止为使报告好看而放宽既有断言**）。
- 测试：`tests/test_analyze_chain.py` 58 项（缺 ecdsa 走 `skipUnless` 降级、GBK 专项、
  哨兵值零泄漏、`epoch = height // 100` 口径断言）；`tests/test_builtin_pool_matrix.py` 80 项
  （15 个可激活扩展原语的正常/元数/类型/边界矩阵，只断言 `error_type` 不锁错误文案）。
- `SURVIVAL_AND_DEPLOYMENT.md`：存活与部署策略（零服务器路线、多 hub 并存机制、
  许可取舍与诚实提醒、部署者须知）。

### 未验证项（如实标注）

- `Dockerfile` 未实机构建、`render.yaml` 未上 Render 验证（本机无 Docker / 无平台账号）；
  PythonAnywhere 免费层经评估不可行（不允许长期运行自定义监听服务）。
- `chain_state.json` 由随机演示密钥生成，重新导出会产生 diff（发布前刷新即可）。
- 浏览器内 Pyodide 全功能版（Pages 上零服务器可玩）列为下一批工作，本批次未包含。

## 尚未实现（沿用 v0.2 清单，本阶段未触碰）

- 真实 LLM 纪元摘要（当前为 mock-rule-v1 规则模板）；大断层事件；
- P2P 网络、真实 tokenizer、真实 LLM；
- 增量归档、加密存档、校验和文件、密钥托管；
- **语法级语言扩展**（本阶段只做原语级注册，parser/AST 不变）；
- 同纪元内「同一原语多次引种不同实现」（单一实现池 BUILTIN_POOL）；
- 任何可交易代币或现实金融功能。
