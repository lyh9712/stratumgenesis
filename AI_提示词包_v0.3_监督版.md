# StratumGenesis（TokenMint）v0.3 迭代 · AI 提示词包（监督模式）

> 用途：本文件是为「AI 编程助手」准备的**逐条提示词**。使用者（人）把某一条提示词原文喂给 AI 助手执行，执行完把结果按文末「阶段完成回传格式」带回来给**监督者（本次会话的 agent）**审阅验收，通过后再执行下一条。
> 当前基线：v0.2 归档（2026-09-09，前后端打通 · 单机内存仿真，72 项测试全过）。参考：`ARCHIVE_v0_2_README.md`、`REFERENCE_DOCS_INDEX.md`、`CHANGELOG_v0_2.md`、`API_SPEC.md`。

---

## 0. 全局约束（以下每条提示词都必须附带本段，供被执行的 AI 遵守）

1. **项目性质红线**：单机仿真实验原型，非生产系统。链内 UTXO 仅为实验内部记账；**禁止**引入任何可交易代币/现实金融语义、公网部署、身份鉴权、HTTPS 要求、真实 P2P。
2. **沙箱与 LLM 边界**：NovScript 沙箱为教学级纯计算隔离，不得改成安全容器；PoI 保持 mock 确定性分词；**默认不调用任何真实 LLM/外部网络**（如需 Ollama 类演示，必须是显式开关且与链状态严格隔离，且先经监督者确认）。
3. **文档对齐优先级**（沿用项目约定）：工程规范 > 白皮书草案；**行为以实际代码与测试为准**。任何与设计文档冲突的实现决策，必须在交付文档中如实说明并给出理由。
4. **兼容性纪律**：
   - `GET /chain-state`、`POST /propose`、`POST /eval-novscript` 三个既有 API 的**响应契约不得破坏**，只允许**追加**字段或新增端点。
   - 已归档区块的哈希、`canonical_bytes()`、签名内容**不得变更**（一旦开始持久化，任何 Block 数据模型改动都会破坏可重放性；确需改模型必须先与监督者讨论）。
   - 端口固定 28417；前端 `index.html` 仍由 `server.py` 提供，不许用 `file://`。
5. **测试纪律**：每阶段结束必须 `python -m unittest discover -s tests -v` 全绿（原有 72 项 + 新增用例），且 `python -m compileall -q *.py tests/*.py` 通过。新增功能必须配测试，禁止删改既有用例去「迁就」新行为。
6. **文档纪律**（项目文化）：实现类阶段必须新增/更新 `*_IMPLEMENTATION.md`；行为变化必须更新 `使用说明.md`、`API_SPEC.md`、`CHANGELOG_v0_3.md`（若尚无则新建并登记到 `ARCHIVE_FILE_MANIFEST.md`、`REFERENCE_DOCS_INDEX.md`）。禁止删除任何历史文档/历史遗留模块。
7. **依赖纪律**：保持纯标准库 + `ecdsa`，不引入新第三方库（确需引入须经监督者批准）。
8. **编码前必读**：动手前先读 `server.py`、`chain_store.py`、`block_model.py`、`epoch_manager.py`、`utxo_ledger.py` 及相关测试，以代码现状为准，提示词中的命名仅为建议。
9. **先归档再动手**：执行任何阶段前，若尚未 `git init`，先执行提示词 P0；每阶段完成后做一次提交，保证可回退。

---

## 提示词 P0 —— v0.2 收尾：纳入版本控制（5 分钟内完成）

**角色与任务**：你是资深 Python 工程师，为项目做版本控制收尾，**不改任何功能代码**。

**必做**：
1. 在项目根目录 `git init`，写 `.gitignore`：忽略 `__pycache__/`、`*.pyc`、`server.log`、`data/`（若阶段 A 后出现）、临时文件。
2. 提交当前 v0.2 状态为基线：`git add -A && git commit -m "archive: v0.2 前后端打通单机仿真归档基线"`，并打标签 `v0.2`。
3. 在 `CHANGELOG_v0_2.md` 末尾追加一行：`- 版本控制基线：git tag v0.2（监督模式迭代起点）。`

**禁止**：改动任何 `.py`/`index.html` 业务代码；不要删除归档文档。

**验收**：`git log --oneline` 显示一条基线提交与标签 `v0.2`；`git status` 干净。

---

## 提示词 A —— 磁盘持久化与链数据导出（P0，最先做，v0.3 第 1 个功能阶段）

**角色与任务**：为 StratumGenesis 单机原型增加「可落盘、可恢复、可导出」能力。目标来自 `ARCHIVE_v0_2_README.md` §6 未实现清单「磁盘持久化」与白皮书 §14.5「定期导出完整链数据」。

**必读**：`server.py`、`chain_store.py`、`block_model.py`、`epoch_manager.py`、`utxo_ledger.py`、`crypto_key.py`、`tests/test_http_api.py`、`API_SPEC.md`、`ARCHIVE_v0_2_README.md`。

**需求**：
1. 新增 `persistence.py`，提供**确定性、可校验**的状态保存/恢复：
   - 保存内容：主链全部区块、休眠分支（含拒绝原因）、矿工注册表、纪元快照（含归档标记）；候选池为瞬时状态可不持久化。
   - 保存格式建议 JSON（含 `format_version` 字段，预留演进），默认路径 `data/chain_v1.json`；写入用「临时文件 + 原子替换」，避免中断损坏。
   - 恢复必须**保持区块哈希/顺序/账本余额/快照完全一致**。UTXO 账本优先采用「从创世块起重放主链交易与奖励重建」，而不是序列化账本内部缓存（纯函数重建、天然防漂移；若实现中必须落缓存则要加校验和对比）。
   - 提供 `export_chain(path)`（或等价 CLI/接口）导出与持久化相同格式的完整数据，供存档与外部研究使用。
2. 接入 `server.py`：
   - 启动时：若 `data/chain_v1.json` 存在则加载并继续（不再预沉积 102 演示块，除非存档为空）；不存在则维持现行为（创世 + 预沉积 102 块）并落盘。
   - 新增启动参数 `--fresh`：忽略存档，从创世重建（用于演示复位）。
   - 每次链状态变更（成功上链/落选入休眠分支）后自动保存；保存失败要打印明确错误但**不影响**本次内存操作结果。
   - `GET /chain-state` 等既有 API 契约不变。
3. 健壮性：存档缺失/损坏/`format_version` 不匹配时给出中文明确报错并**拒绝启动**（不允许静默用空链顶替）；提示可用 `--fresh`。
4. 测试：新增 `tests/test_persistence.py`，至少覆盖：roundtrip 等值（高度、全部区块哈希、余额、休眠分支数、纪元快照 archived 标记）、重启加载后与保存前 `GET /chain-state` 内容一致、损坏文件拒绝启动、`--fresh` 重置。**既有 72 项全部保持通过**。

**禁止**：改动 Block/UTXO/Transaction 的既有字段与 `canonical_bytes()`；引入第三方库；改动三个既有 API 的响应字段名。

**交付**：新代码 + 新测试 + `PERSISTENCE_IMPLEMENTATION.md`（记录格式、版本字段、恢复策略、已知限制）+ 更新 `使用说明.md`、`API_SPEC.md`（说明存档与 `--fresh`）、`CHANGELOG` 追加 v0.3 条目。

**验收**：跑通第 5 节命令；`python server.py` → 提交 1 个合法提案 → 重启 → 高度与区块连续、提案仍在；`python server.py --fresh` 回到高度 102。

---

## 提示词 B —— mock 纪元摘要模块（P1，v0.3 第 2 个功能阶段，依赖 A 完成）

**角色与任务**：实现白皮书 §7.2–7.4 / 路线图 §14.4 的「纪元摘要」仿真版：在纪元边界用**确定性规则模板**生成若干摘要候选并加权投票，胜者写入该纪元快照。为未来真实 LLM 摘要预留清晰接口与数据模型（`ARCHIVE_v0_2_README.md` §6「纪元 LLM 摘要」、§9.2）。

**必读**：`epoch_manager.py`、`chain_store.py`、`weight_calculator.py`、`conflict_voter.py`、`block_model.py`、`server.py`、`tests/test_epoch.py`、`EPOCH_BASE_IMPLEMENTATION.md`、白皮书第 7 章。

**需求**：
1. 数据模型（建议放在 `epoch_manager.py` 或新 `epoch_summary.py`）：
   - 为 `EpochSnapshot` **追加**（不可删除旧字段）`summary` 相关字段：候选列表（含文本、生成模板名、生成者矿工标签）、各候选得票、胜者、最终摘要文本、方法标签（如 `mock-rule-v1`）、状态（`pending/finalized`）。
   - 摘要**只在纪元边界确定**（某高度使 `height % 100 == 0` 的主链追加触发），一旦选定即不可变（与归档只读语义一致）；后续区块不得改写。
2. 确定性生成与投票（全部 mock、无 LLM）：
   - 用 2–3 套不同规则模板从该纪元主链区块生成摘要候选（例如：按「特性关键词词频 Top」模板、按「贡献者分布」模板、按「首末特性串讲」模板），同一存档下结果必须可复现。
   - 复用 `weight_calculator` 的历史贡献权重（仅主链、截止纪元边界）对候选加权投票；平票用**确定性规则**（如模板名排序取首）但须记录平票发生。
   - 投票只影响摘要选择，**不触碰**区块合法性、UTXO、休眠分支逻辑。
3. 接口与前端：
   - `GET /chain-state` 的 `epochs[]` 中**追加**摘要字段（不删旧字段）；已归档纪元返回 `summary` 与状态，未封口纪元返回空/`pending`。
   - `index.html`：在已归档纪元的标签/考古区域以**可折叠摘要卡**展示纪元摘要（纯追加式改动；不得破坏既有地层动画、钻探、详情面板交互）。
4. 测试：新增 `tests/test_epoch_summary.py`：边界触发时机、确定性（同状态两次运行候选与结果一致）、权重生效、平票回退、finalized 后不再变化、休眠分支不产生摘要、API 字段存在。既有 72+（含 A 新增）全部通过。
5. 文档：`EPOCH_SUMMARY_IMPLEMENTATION.md`（含未来接真实 LLM 的替换点说明）+ 更新 `API_SPEC.md`、`使用说明.md`、`CHANGELOG`。
6. **与阶段 A 持久化的协同（监督者于阶段 A 验收后追加）**：`EpochSnapshot` **不在存档中序列化**，加载时由主链重放重建 —— 因此摘要候选与投票结果必须**完全确定性**：`save → load` 后摘要字段（候选列表、得票、胜者、`finalized` 状态、方法标签）必须与保存前逐字段一致，并新增测试断言该等值。**不得**为摘要单独引入第二套序列化或旁路状态（会与主链漂移）。

**禁止**：调用任何真实 LLM/网络；改动既有 API 字段名；改 Block/账本语义；让摘要流程影响上链/投票主逻辑。

**验收**：预沉积 102 块后启动，`/chain-state` 中纪元 0 快照含 finalized 摘要、纪元 1 为 pending；再提交合法提案使高度跨过 200 边界时，纪元 1 自动 finalized；两次 `--fresh` 启动结果逐字节一致。

---

## 附：阶段 A 遗留小修（监督者验收发现，随阶段 B 一并提交即可）

1. **加载时未校验区块签名**：`block_hash` 与签名内容在设计上互斥（区块哈希排除 `signature_bytes`），因此存档中仅篡改签名的数据目前能通过 `load_state`。二选一处理：
   - 推荐：加载时用既有 `crypto_key.verify_block_signature` 对每个区块验签（成本低），签名不符即拒绝加载；
   - 或退一步：在 `PERSISTENCE_IMPLEMENTATION.md` §7「已知限制」中如实写明「加载仅校验区块哈希，不重新验签」。
2. **文档中的编译检查命令在 PowerShell 下不生效**：`python -m compileall -q *.py tests/*.py` 的通配符不会被 PowerShell 展开（Python 收到字面量 `*.py`，静默失败且退出码仍为 0）。请在 `ARCHIVE_v0_2_README.md`、`PERSISTENCE_IMPLEMENTATION.md` 等处以 `python -m compileall -q .` 为准（或在文档中标注该命令应按 cmd 语法执行）。

---

## 提示词 C —— 跨纪元引种提案原型（P1，v0.3 第 3 阶段，依赖 A 完成；建议 B 之后做）

**角色与任务**：实现白皮书 §7.6 / 开放问题 X.9-11 的「跨纪元引种提案」仿真：旧纪元已沉淀特性可在新纪元被显式「引种」，并校验其**依赖闭包**。原型只做记账与流程机制，**不改变 NovScript 运行语义**。

**必读**：`chain_store.py`、`block_model.py`、`block_validator.py`、`server.py`、`epoch_manager.py`、白皮书 §7.6、`ARCHIVE_v0_2_README.md` §9.3。

**需求**：
1. 特性注册表：从主链区块的 `feature_name` 与纪元归属建立「每纪元已沉淀特性 + 从哪个区块/纪元来」的只读注册表（从主链派生，不新增 Block 字段，避免哈希变更）。
2. 引种记录模型：独立于主链区块的 `IntroductionRecord`（引种特性名、被引种来源特性哈希列表=依赖声明、目标纪元、提案矿工、时间序、结果），存放于 ChainStore/EpochManager 的内存注册区（**不上主链哈希链**，交付文档里说明该取舍）。
3. 校验流程：依赖闭包校验（目标纪元中：所有声明依赖要么属于创世内核特性、要么已被本纪元引种/沉淀，且**无环**）、名称冲突（同纪元重复引种/与既有特性同名→拒绝并记录原因）、与创世内核兼容性。通过后写入目标纪元注册表并记入引种历史；冲突/非法进入「引种失败记录」。
4. 接口（纯追加）：`GET /introductions`（历史+失败原因）与 `POST /introduce`（提交引种提案）；`GET /chain-state` 不变。前端可选不接（交付文档说明即可），或做最小展示。
5. 测试：新增 `tests/test_introduction.py`：依赖闭包通过/缺依赖拒绝/环拒绝/同纪元重名拒绝/成功后注册表可见。全量回归通过。
6. 文档：`INTRODUCTION_IMPLEMENTATION.md` + `API_SPEC.md` + `CHANGELOG`。

**禁止**：新增 Block 字段或改动 canonical bytes；让引种改变 NovScript 解释器语义；引入真实网络/LLM。

**验收**：演示脚本或测试展示：从纪元 0 引种某特性到纪元 2 成功；缺依赖的引种被拒并给出原因；失败记录可查询。

---

## 提示词 D —— 大断层事件原型（P1，v0.3 第 4 阶段，依赖 B；可作为扩展项）

**角色与任务**：实现白皮书 §7.5 / `ARCHIVE_v0_2_README.md` §6「大断层事件」的可配置仿真：摘要链长度达到阈值时可触发「社区投票重置」，重置后开启新地质纪元。

**必读**：B 阶段的摘要实现、`epoch_manager.py`、`conflict_voter.py`、白皮书 §7.5。

**需求**（最小可验证版，幅度需与监督者对齐后再展开）：
1. 阈值配置（如 `FAULT_CAP = None` 默认关闭，保证预沉积演示链不会自触发）。
2. 触发检测与候选投票：达阈值时生成「大断层事件」候选，复用 mock 加权投票；通过后产生 `EraReset` 记录：旧纪元全部归档、新纪元序号延续或重置由配置决定。
3. 测试与文档同前各阶段纪律。

**验收**：关闭阈值时行为与 B 完全一致；开启小阈值（如 2）时按测试脚本可触发一次重置并正确归档。

---

## 提示词 E —— 休眠分支升级/切换 + 分叉可视化（P1/P2，v0.3 第 5 阶段，依赖 A）

**角色与任务**：对应 `ARCHIVE_v0_2_README.md` §6「分支升级/切换」与 §9.4、白皮书 §9「分叉可视化」。

**必读**：`chain_store.py`、`server.py`、`index.html`（地层剖面渲染与滚动结构）、`API_SPEC.md`。

**需求**：
1. 先冻结**分支选择规则**（参考开放问题 X.9-9）并在文档中写明，原型建议采用最简可验证规则：仅当某休眠分支头 `height == 主链高度 + 1`（即它在某高度投票落选、而主链尚未继续延伸）时，允许显式「切换/接续」——因为当前单机流程里投票胜者立即上链，分支想翻身只能在主链停滞时发生；规则可后续演进。
2. 后端（纯追加）：`POST /promote-branch`（按 `branch_id` 尝试接续，校验规则后把该分支整段并入主链尾，账本按合并后主链重放重建，纪元快照重扫）；`GET /chain-state` 保持兼容（可追加分叉详情端点或字段）。
3. 前端：休眠分支列表视图 + 分支岩层对比/预览（不得破坏现有页面布局与动画；如改动过大可先做后端+测试+最小 UI，UI 详化单独一条提示词）。
4. 测试：新增 `tests/test_branch_promotion.py`：规则拒绝（分支不满足条件）、接续成功、接续后账本/快照一致、既有的平票双分支场景。全量回归通过。
5. 文档纪律同前。

**禁止**：破坏既有 API 契约；静默丢弃任何分支数据。

**验收**：构造「高度 103 平票双分支」后主链不延伸，对其中一支 `promote` 成功、另一支保留在休眠列表；`/chain-state` 前后字段兼容。

---

## 提示词 F —— 提案映射模板化与 UI 打磨（P2，可随时穿插）

**角色与任务**：两件独立小任务，任选其一即可单独成条执行。

1. **提案→代码映射模板化**：现状是 `server.py` 内按关键词 mock 映射（见 `ARCHIVE_v0_2_README.md` §7.5 风险）。抽出为可扩展配置（如 `proposal_mapping.json` + 加载器）：正则/关键词 → 特性名 + demo 代码 + 测试用例；默认兜底模板；保持确定性。更新 `API_SPEC.md` 的映射说明。
2. **UI 打磨**（对应 `ARCHIVE_v0_2_README.md` §9.1）：移动端适配、千层性能（DOM 复用/虚拟化）、地层纹理增强。只改 `index.html` 的 CSS/JS，**不动** API 契约与 DOM 语义结构（参考 `UI_CHANGE_NOTE.md` 的做法与表述，产出同类变更说明）。

**验收**：任务 1 增改 `tests/test_http_api.py` 或新测试；任务 2 提供变更说明文件与肉眼验收清单。

---

## 监督与验收协议（给「人」用，监督者会照此执行）

### 每阶段执行顺序
1. 按提示词 P0 打好基线（一次性）→ 执行 **A** → 回传验收 → 再执行 **B** → C → D/E/F 顺序由人+监督者按现场情况定（依赖：A 是 B/C/E 的前置，B 是 D 的前置；F 可随时）。

### 阶段完成回传格式（执行方把以下内容带回给监督者）
```text
阶段：提示词 X（名称）
变更文件：<新增/修改文件清单>
测试：python -m unittest discover -s tests -v  → 共 N 项，失败 0
编译：python -m compileall -q *.py tests/*.py  → 通过/报错
手工验证：<启动 server.py 后的关键观察，如高度、API 样例返回、摘要字段>
文档：<更新了哪些 md>
已知取舍/偏离设计之处：<如实列出，特别是任何与白皮书冲突的决策>
疑问：<需要监督者裁决的问题>
```

### 监督者（本会话 agent）收到后做什么
1. 复核变更文件（重点：是否触碰 Block/canonical bytes、是否破坏三 API 契约、是否引入新依赖）。
2. 复跑/抽查测试输出与关键 diff；必要时要求补测试或修正。
3. 对照设计文档确认取舍是否可接受；裁决「疑问」项。
4. 验收通过后发放下一条提示词 / 指示修复项。

### 快捷命令（监督复验用）
```bash
python -m unittest discover -s tests          # 全量测试
python -m compileall -q .                     # 字节码编译检查（PowerShell 下不要用 *.py 通配符）
python server.py                              # 启动（端口 28417）
netstat -ano | findstr 28417                  # 查占用，先停旧进程再测
```

---

## 附：阶段 C（语言演化）验收补丁清单 —— 监督者独立检查发现（2026-09-10）

以下问题为监督者复核阶段 A/B 与未提交的演化改动时**实测复现**，建议随阶段 C 一并修复并补测试：

1. **【P1】`SandboxLimits.max_output_chars` 声明但未强制**：`novscript/sandbox.py` 仅在 `_validate_limits` 中校验其类型与正数，`LimitsState` 不接收该值，`echo` 原语（`novscript/registry.py` 的 `_impl_echo`）无上限追加 `state.output_buffer`，`evaluate()` 直接 `"\n".join(...)`。实测：500 条 `(echo 1234567890)` 产出 **5499 字符**，超出声明的 4096 上限。修法建议：把 `max_output_chars` 传入 `LimitsState`，在写入处累计字符数、超限即 `ResourceLimitError`；补回归测试断言上限生效。
2. **【P2】宿主递归泄漏为 `SandboxError`**：`_public_value`/`display_value` 对 `Pair` 递归展开。实测 `(list 1 … 1)`（2000 个元素）返回 `ok=False, error_type=SandboxError, msg="maximum recursion depth exceeded"` —— 这是宿主（Python）级的递归错误被兜底 `except Exception` 捕获后当作沙箱错误上报，违反「只返回稳定类型与诊断文字」的规范。修法建议：改为迭代展开，或捕获 `RecursionError` 并映射为 `ResourceLimitError("maximum structure depth exceeded")`；补一条长列表用例。
3. **【P2】`PrimitiveSpec.arity` 为装饰性字段**：`novscript/registry.py` 中全部规格都写 `arity=(0, None)`，且全项目无任何读取点（实际 arity 由各实现自查）。建议要么填真实 arity 并在激活/调用处校验，要么删掉该字段，避免未来校验逻辑误信。
4. **【P2】文档漂移**：
   - `PERSISTENCE_IMPLEMENTATION.md` 第 19、29 行仍写 `format_version=chain-v1`，实际已是 `chain-v2`；`ARCHIVE_FILE_MANIFEST.md` 第 27 行同样仍写 `chain-v1`。
   - `BLOCK_LAYER_PROTOTYPE_IMPLEMENTATION.md` 仍称「五阶段校验」，实际流水线已是 9 个检查阶段（signature → structure → kernel_compatibility → poi → parse → **activation** → sandbox → **language_evolution** → utxo）。
5. **【P2】旧存档处置建议**：`chain-v1` 存档现被正确拒绝（实测报「存档格式版本不匹配：期望 chain-v2，实际 chain-v1」并 exit 1），但提示语引导使用 `--fresh`，而 `--fresh` 会**覆盖**旧存档、不可逆。建议：拒绝时先提示改用 `--archive <新路径>`，或在 fresh 重建前把旧档案重命名为 `chain_v1.json.bak`；如实现 `--migrate`（按新 canonical 重新计算哈希/签名），需在文档中明确「迁移会改变区块哈希」。
