# StratumGenesis v0.3 · 阶段 E 设计说明：休眠分支升级 / 主链重组（Branch Promotion / Reorg）

> 性质：第一阶段交付物（**仅设计说明，不含任何实现代码**）
> 日期：2026-09-10 · 状态：待监督者放行后进入第二阶段
> 关联：设计白皮书 §9《分叉与语言宇宙》、`ARCHIVE_v0_2_README.md` §6「分支升级/切换」、开放问题 X.9-9（分支选择规则）
> 代码基线：本文所有论断基于对 `chain_store.py` / `block_validator.py` / `epoch_manager.py` / `epoch_summary.py` / `persistence.py` / `server.py` / `candidate_pool.py` / `conflict_voter.py` / `weight_calculator.py` / `utxo_ledger.py` 的逐行阅读。

---

## 0. 背景与术语

**现状问题**：落选候选经 `chain_store.apply_vote_result()` 进入 `sleeping_branches` 后**永久沉睡**，没有任何翻身机制。白皮书 §9 主张「分叉 = 语言分化」，但当前实现里分叉只是垃圾桶。本阶段引入「休眠分支升级（promote）」：把一条休眠分支链替换上主链（reorg），并保证语言 / 账本 / 纪元全部派生状态随之正确改写。

**既有事实（决定本设计的关键约束来源）**：

1. 休眠分支按 `branch_id = 区块.parent_hash` 分组（`chain_store.py` `add_sleeping_branch`，L166–174）。**同一分组的区块是兄弟（同父），不保证自身成链**；链式分支（A 落选、B 以 A 为父再落选）在库级调用下可形成——`_check_structure` 的 `store.get_block()` 检索范围含休眠区块（`block_validator.py` L73–75）。
2. 经 HTTP `/propose` 产生的休眠块恒为「深度 1、父=当时主链 tip」：服务端只在 tip 上构造区块（`server.py` L407），校验失败与落选两条路径都进休眠（L413–419、L434–442）。
3. **休眠分支可含非法块**：校验失败（含结构错误如高度不匹配）的块也会入休眠。
4. 全部派生状态（UTXO 账本、纪元快照/摘要、语言三层：`epoch_registry` / `language_registry` / `_language_snapshots`）都是**主链重放的纯函数**——这是 `persistence.rebuild_store()`（L350–383）在每次加载时已经践行的语义。
5. 语言作用域为纪元内有效：`append_main` 在 `height % 100 == 0` 时重置纪元层（失忆），activation 中「历史层无 → 新特性、历史层有 → 引种」（`chain_store.py` L94–117）。

**术语**：

| 记号 | 含义 |
|---|---|
| `M = (m_0 … m_H)` | 当前主链，`m_i.height == i`，`tip = m_H`，`H = store.height` |
| `e*` | tip 所在纪元 `= H // 100`；`s = 100·e*`（纪元起始高度）；`t = 100·(e*+1) − 1`（纪元末高度） |
| `S` | 全部休眠区块集合（跨全部分组的并集）；全店区块 = `M ∪ S`，块哈希全店唯一 |
| `C = (b_1 … b_k)` | 待提升的分支链：`b_1` 为分支首块（父在主链），`b_k` 为分支头（head） |
| `f` | 分叉高度 = `b_1.parent.height`（分叉父块 `m_f` 保留在主链上） |
| 旧后缀 | `M[f+1 … H]`（被替换下来、将降级入休眠的主链区块） |

---

## 1. 升级规则：三条冻结约束的落实

### R1 纪元局部性（只允许当前未归档纪元内重组）

**规则**：被替换的旧后缀必须整体位于 tip 所在纪元 `e*`（每块 `epoch == e*`）；同时（本设计从严补充，见 §9-D2）待提升分支链也必须整体位于 `e*`。已归档纪元的任何区块与 finalized 摘要**字节不动**。

**落实**：资格判定 E4/E5（§2）+ 重放构建只从 `f ≥ s − 1` 之后截断（§3）。§5 给出「finalized 摘要不可侵犯」的构造性证明。

### R2 无数据丢失

**规则**：被替换下来的主链区块必须移入休眠分支，保留全部字段与拒绝原因记录位。

**落实**：`Block` 是 frozen dataclass 且哈希排除签名字段——降级块是**同一不可变对象的整体搬运**（主链元组 → 休眠分组），全部字段零损耗，天然满足。每个降级块在 `rejection_reasons`（既有 dict，`persistence.serialize_state` 已落盘）写入一条**确定性**降级原因（格式见 §6.4，无时间戳）。提升块若有旧拒绝记录（如「落选」「校验失败」）则删除——它已不在休眠集合中，`/chain-state` 的休眠渲染只遍历休眠集合（`server.py` L309–322），记录不再可见，删除防止语义陈旧。

### R3 派生状态一律重建（不做增量反向补丁）

**规则**：账本、纪元快照、语言快照/注册表由「新主链重放」重新推导。

**落实**：重组算法在**全新 scratch `ChainStore`** 上按「保留前缀 → 分支链」顺序重放（复用 `append_main` 与 `epoch_manager.scan_chain` 既有路径，零旁路代码）。「回滚旧后缀的贡献」=「不重放它们」，不存在任何反向补丁逻辑。

### 红线自查：不升 `FORMAT_VERSION`

promote 只改变区块在存档两个**既有**数组（`blocks` 与 `sleeping_branches`）之间的成员归属：不新增/修改 `Block` 字段、不触碰 `canonical_bytes()`、不新增持久化集合。哈希与 ECDSA 签名逐块不变（对象原样搬运）。**结论：`chain-v2` 无需升版**，重组后的存档是既有格式的一个合法实例。

---

## 2. 候选资格判定（精确判定式）

### 2.1 链回溯（walk，纯只读函数）

给定请求头哈希 `h*`：

1. `b_k` = 全店中 `block_hash == h*` 的区块，且必须 `b_k ∈ S`（休眠块才可提升；主链块不可）。
2. 自 `b_k` 沿 `parent_hash` 逐级回溯：父块在 `M` 中 → **终止**，该父即分叉父 `m_f`；父块在 `S` 中 → 继续；父块不存在于全店 → 失败。
3. 防御上界：回溯步数 ≤ `H + 1`；途中出现重复哈希（环）→ 失败。

输出 `C = (b_1 … b_k)` 与 `f = b_1.parent.height`。

### 2.2 判定式（全部为真才可升级）

| # | 判定式 | 理由 |
|---|---|---|
| **E1** | `h* ∈ S`（头存在且休眠） | 只有休眠块才是「落选候选」；主链块已在位，无提升语义 |
| **E2** | 链线性完整：`∀ i: b_{i+1}.parent_hash == b_i.block_hash ∧ b_{i+1}.height == b_i.height + 1`，且 `b_1.height == f + 1` | 回溯按父指针天然给出父链接；但**高度线性必须显式检查**——休眠分支含结构非法块（背景事实 3），如 `HEIGHT_MISMATCH` 的废块也可能被回溯穿过。非线性链拼接进主链会破坏不变量 I-1 |
| **E3** | 分叉父锚定主链：`b_1.parent ∈ M`（即 `M[f].block_hash == b_1.parent_hash`，`f ≤ H`） | 分支必须锚定在当前主链上才构成「重组同一台账本的另一条历史」；锚在休眠空间深处的链是不可达的孤儿链 |
| **E4** | 旧后缀纪元局部（冻结约束 R1）：`∀ j ∈ (f, H]: m_j.epoch == e*`（等价 `f + 1 ≥ s`） | 已归档纪元的区块与 finalized 摘要不可改写（§5 证明的前提）。若后缀探入 `e < e*` 的区块，截断点将低于纪元边界，violates R1 |
| **E5** | 分支纪元局部（v1 从严版，见 §9-D2）：`∀ i: b_i.epoch == e*`（等价 `b_1.height ≥ s ∧ b_k.height ≤ t`） | (a) 保证新 tip 高度 `f + k ≤ t`，重组**既不会归档 `e*`（触发摘要 finalize）也不会解档 `e*`**，纪元层唯一变化 = pending 快照重算；(b) 重组内部不触发失忆重置，避开「由重组自己制造纪元边界」这一最难语言场景；(c) 任务示例「分支不得包含已归档纪元的区块」只禁过去纪元，本条同时禁未来纪元——从严的理由是证明面最小，宽版留作 v2 演进 |
| **E6** | 唯一性（防御式复查）：`C` 内哈希互异，`C ∩ M = ∅`，`C ∩ (S \ C) = ∅` | 由全店哈希唯一性（`append_main` / `add_sleeping_branch` 均查重）天然成立；复查是为防御未来引入的旁路写入 |
| **E7** | 重放语义有效：scratch 重放中每个 `b_i` 通过完整 9 检查校验流水线（`validate_block`） | **语义资格**（非结构）：休眠块当初是对着**旧世界状态**（旧 tip 的 UTXO 集、旧纪元语言层）校验的；截断后上下文改变——分支块可能花旧后缀创造的 UTXO（应拒）、可能引用仅旧后缀激活过的原语（应拒）、可能是当初就校验失败的废块（永远不可提升）。逐块对新世界重校验是唯一正确的语义 |

**判定式的三个直接推论**：

- `f == H` 允许（空后缀、纯接续）——**正是监督者在提示词 E 中给出的最小规则特例**（平票后主链停滞、分支头 `height == H+1` 接续上链）。
- `f + k < H`（收缩重组）、`f + k > H`（延伸重组，仍限 `≤ t`）均允许：promote 是**显式治理动作**而非自动分叉选择，不做「新链必须更长/更重」要求（取舍论证见 §9.1）。
- 重组永远不跨越纪元边界：新 tip ∈ `[s, t]`，`e*` 前后均为未归档。

**错误码映射**（详见附录 B）：E1 → `PROMOTION_NOT_FOUND`；E2 → `PROMOTION_CHAIN_BROKEN`；E3 → `PROMOTION_PARENT_MISSING`；E4 → `PROMOTION_ARCHIVED_EPOCH`；E5 → `PROMOTION_EPOCH_SPAN`；E6 → `PROMOTION_NOT_ELIGIBLE`；E7 → 透传该块的既有语义错误码（附块高度上下文）。

---

## 3. 重组算法

**总原则：scratch 构建 + 原子换入（archive-reachability by construction）**。不在 live store 上做「截断—重放—出错再回补」：任何失败路径只需丢弃 scratch，live store 从未被触碰。

### 3.1 步骤与失败回滚点

| 步骤 | 内容 | 失败回滚点 |
|---|---|---|
| **S0** | 解析请求（`head_block_hash`）；获取状态串行锁（与 `/propose` 互斥，见 §9-D6） | 参数缺失/格式错 → 立即返回 400，**零状态改动** |
| **S1** | 链回溯 walk（§2.1），产出 `(C, f)` | `PROMOTION_NOT_FOUND` / `PROMOTION_CHAIN_BROKEN` / `PROMOTION_PARENT_MISSING`；**全程只读** |
| **S2** | 结构资格判定 E1–E6：纯函数 `check_promotion_eligibility(C, f, store)` → `ValidationResult(stage="promotion", …)` | 语义化错误码（附录 B）；**全程只读** |
| **S3** | **scratch 构建**（全新 `ChainStore`，live 不动）： | 任意失败 → **丢弃 scratch，整体失败**，live 状态比特不变 |
| S3a | 重放保留前缀 `M[1 … f]`：逐块 `append_main`（与 `rebuild_store` 加载路径**完全同源**；不跑完整 9 检查——既成主链区块与磁盘加载一样只重放不重校验） | 理论不可失败（同一确定性代码重放同一序列）；若失败 = 内部一致性错误，整体失败 |
| S3b | 逐块完整校验并追加分支链：`for b in C: validate_block(b, scratch).accepted` 才 `append_main(b)`（E7） | 透传该块 `stage`/`error_code`（如 `UTXO_INVALID` / `UNIMPORTED_FEATURE` / `DUPLICATE_FEATURE`），附 `height` 上下文；scratch 丢弃 |
| S3c | 休眠迁移：把 `S \ C` 按「原分组顺序（`sleeping_branches()` 已按 branch_id 排序、组内保持插入序）跳过被提升块」逐块 `add_sleeping_branch` 到 scratch；再把旧后缀按高度升序逐块 `add_sleeping_branch` | 哈希冲突 = 内部错误（全店唯一性下不可达）；整体失败 |
| **S4** | **原子换入（唯一提交点）**：单临界区内把 live store 的六个内部引用（`_main_chain` / `_sleeping_branches` / `utxo_ledger` / `epoch_manager` / `language_registry` / `epoch_registry` / `_language_snapshots`）整体替换为 scratch 对应对象；同步更新 `rejection_reasons`（提升块删旧记录、降级块写 `reorg: …` 记录） | 临界区内纯引用赋值，无中间可观测态 |
| **S5** | 落盘 `save_state`（原子写 .tmp + `os.replace`） | 失败仅中文警告、不影响内存权威状态——与既有自动保存纪律一致（`server.py` `_auto_save`） |
| **S6** | 返回 `PromotionResult`：`status ∈ {promoted, rejected}`、`promoted`/`demoted` 哈希列表、`fork_height`、`old_tip_height`、`new_tip_height`、失败时 `error_code`+`message` | — |

### 3.2 原子性论证

「要么整体成功、要么完全不改状态」由构造保证：S0–S2 纯只读；S3 全部副作用 confined 在 scratch（失败即丢弃）；S4 是唯一提交点且在锁内一次完成引用交换；S5 best-effort（磁盘最多落后内存一次变更，与 `/propose` 既有崩溃窗口语义一致）。**不存在「半重组」状态**。

### 3.3 为何不走「live 上截断 + undo log」路线

- 逐块撤销账本/语言/纪元三层状态需要为每层写反向操作——正是冻结约束 R3 明令禁止的「增量反向补丁」；
- 失败恢复路径的测试组合爆炸；scratch 路径的失败恢复是平凡的「丢弃」；
- 成本：全量重放 O(H)（`append_main` 每次触发 `scan_chain` 全扫，整体 O(H²)）——原型 H ≤ 数百，与每次 `load_state` 同量级，可接受。

### 3.4 与候选池的关系

promote 不触碰 `CandidatePool`：服务流程中池仅在单次 `/propose` 请求内非空（submit → 立即 remove_group 投票，`server.py` L425–433），请求间恒空。库级调用若残留同高度分组，属调用方误用；可加防御性断言（§9-D7）。

### 3.5 相邻既有隐患（本阶段不改，仅登记）

库级多级分支场景下，若直接对「父在休眠块上」的候选组调 `apply_vote_result`，`append_main` 会因「不接 tip」抛 `ValueError`（`chain_store.py` L85–86）——promote 的 S3b 顺序追加天然规避此问题（每块都接 scratch tip）。该隐患的修复（投票前检查 winner 连通性）不在本阶段范围。

---

## 4. 语言层影响（本阶段最难的部分）

### 4.0 总原则：语言状态 = 主链的纯函数；「回滚」=「不重放」

语言三层状态全部由 `append_main` 重放派生（`chain_store.py` L94–120）：纪元层 `epoch_registry`（纪元作用域、边界失忆）、历史层 `language_registry`（provenance → `ever_active`）、逐高度快照 `_language_snapshots`。**一致性锚点（存档可达性原则）**：promote 的终态必须与「一份 `blocks = 新主链` 的 chain-v2 存档经 `load_state + rebuild_store` 重建」逐项等价。所有语言层决策只需回答一个问题：**重放会产出什么？**

### 4.1 被移除区块的语言贡献如何「回滚」

- 旧后缀激活过的原语 F：若保留前缀与分支链均未激活，则重组后 `F ∉ ever_active` 且 `F ∉ epoch_active`。F 的存在仅体现在休眠记录（`branch_active_features` 视图）与降级原因里。
- 逐高度语言快照：高度 ∈ `(f, f+k]` 的快照由分支块重放重推导；高度 ≤ f 的快照与重组前**逐字节相同**（同一前缀、同一确定性代码重放）→ 历史区块的「版本化重放」（当时的代码按当时的语言求值）不受影响。
- `first_activation_epoch(F)` 可能改变（若 F 的首激活块被降级）→ `UNIMPORTED_FEATURE` 报错中的纪元号随之更新，语义自洽。

### 4.2 分支 activation 如何作为「引种或新特性」重新纳入

scratch 重放走的完全是既有 `append_main` 逻辑：

- `F ∉ language_registry`（历史层无）→ **新特性**：注册历史层 + 纪元层；
- `F ∈ language_registry`（历史层有）→ **引种**：只注册纪元层。

关键认识：「新特性 vs 引种」是**上下文相关的判定，重组后按新链重判**。例：旧后缀首激活了 `-`、分支没激活 → 重组后历史层无 `-`；此后若有区块再激活 `-`，在新世界里它是**新特性**而非引种。这是重放语义的自然结果，无需任何特判代码。

### 4.3 `ever_active` 单调性的精确化（⚠ 需监督者裁决，§9-D3）

- **既有语义（由持久化层冻结）**：`ever_active = f(主链)`；`rebuild_store` 每次加载都从主链重放重derive。若维持「重组后 ever_active 不缩」的高水位线语义，必须把额外集合序列化进存档 → 违反 R3 与「账本/纪元快照/语言注册表全部由主链重放重建」的既有持久化不变量，且必须升 `FORMAT_VERSION`。
- **本设计的精确不变量**（I-9）：`ever_active` **在任意 `append_main` 序列上单调不减**；**重组是重推导事件**，重组后 `ever_active = f(新主链)`，**可能收缩**（仅当某原语的唯一激活记录在被移除后缀中）。
- 收缩的语义正确性：该原语在这个世界线上从未激活过——后续提案引用它要么被沙箱以「未绑定名称」拒绝、要么（若曾在保留前缀激活）按 `UNIMPORTED_FEATURE` 失忆语义拒绝，两种报错都真实反映新世界状态。
- 若监督者坚持字面「任何时刻只增不减」：需高水位线 + 存档格式变更，本设计**反对**，列为裁决点 D3。

### 4.4 分支自身 `branch_active_features` 与主链作用域的边界

- `branch_active_features(branch_id)` 是休眠分组的**只读视图**（组内区块 activation 的并集），不是主链语言态、不落盘（由休眠区块对象自身携带，存档天然保全）。
- 重组后的成员变化：提升块离开休眠（其语言贡献转由主链重放体现）；降级块进入以其 `parent_hash` 为键的分组（既有 `add_sleeping_branch` 语义）。
- **深层边界**：(a) 被提升块的「休眠子孙」（以被提升块为父的其他休眠块）保留在休眠——它们将来可再走同一条 walk 规则升级（链终止于现已上主链的父块）；(b) 被降级后缀可通过其休眠子孙被「再提升」——promote 具有**对合性**（I-12 / 测试 T-14）：提升分支链 C、再提升旧后缀链，即恢复原主链。

### 4.5 重组中的语言边界情形（全部由「完整重放校验」统一吸收，无旁路）

| 情形 | 重放结果 | 语义解释 |
|---|---|---|
| 分支块激活保留前缀本纪元已激活的原语 | `DUPLICATE_FEATURE` → promote 拒绝 | 新世界该高度此特性已在纪元层，重复激活非法 |
| 分支块在 demo/test 中引用「仅旧后缀激活过」的原语且不在自身 activation | `UNIMPORTED_FEATURE`（若在保留历史层）或沙箱 `NameError` → promote 拒绝 | 截断后该原语在那个高度不可用——分支块的合法性本来就是上下文相关的 |
| 分支块花费旧后缀创造的 UTXO | `UTXO_INVALID` → promote 拒绝 | 新世界那笔钱不存在 |
| 休眠的校验失败废块 | 原错误码重现 → 永不可提升 | promote 顺带充当休眠垃圾桶的过滤器 |
| `f = s − 1`（分叉父是上一纪元末块） | 分支首块（height = s）成为新纪元首块：`append_main` 既有 `height%100==0` 分支先清空纪元层再注册 activation → 新纪元基线 = 分支首块引种集 | 与 `scan_chain` 的 `base = blocks[0].activation` 完全一致；`epoch_base_features` / `epoch_new_features` / `cumulative_*` 全部由重扫重derive |

E5 保证分支链整体在 `e*` 内 ⇒ 重组过程内部**不触发**失忆重置与摘要 finalize，上表最后一行是唯一的（跨）边界情形且已被既有代码覆盖。

---

## 5. 纪元摘要一致性

**定理（finalized 摘要不可侵犯）**：在 E4/E5 下，promote 前后：`∀ e < e*`：`snapshot_e` 与 `summary_e` 逐字段不变、归档状态不变；`e*` 恒为 pending 且快照按新主链重算；`summary_chain` 逐项不变。

**证明**（`epoch_manager.scan_chain` L58–112、`epoch_summary.finalize_epoch_summary` 的确定性）：

1. **`e*` 恒 pending**：归档条件 = 主链存在高度 ≥ `100(e*+1)` 的区块。重组前 `H ≤ t < 100(e*+1)`；重组后新 tip 高度 `f + k ≤ t`（E5）。故前后均未归档，`summary = None`、`status = pending`。
2. **`∀ e < e*` 的主链区块不变**：纪元 `e` 的区块高度 ∈ `[100e, 100(e+1)) ⊆ [0, s)`；被移除后缀从 `f + 1 ≥ s` 开始（E4），故这些区块全部落在保留前缀内，逐块不变。
3. **归档状态不变**：`e` 归档 ⟺ 主链含高度 ≥ `100(e+1)` 的区块。新 tip 高度 `f + k ≥ s = 100·e* ≥ 100(e+1)`（因 `e ≤ e* − 1`）⇒ 前后均归档。
4. **摘要输入恒定**：`finalize_epoch_summary(e, epoch_blocks, prefix)` 的两个输入——纪元 `e` 自身区块（由 2 不变）与「主链中高度 ≤ `end_height(e)` 的前缀」。`end_height(e) < s ≤ f + 1` ⇒ 该前缀 ⊆ 保留前缀，不变。两输入恒定 + 函数确定性 ⇒ `summary_e` 字节不变。∎
5. **`summary_chain` 不变**：由 4，已确定摘要逐项不变；由 1，无新增项。

**当前纪元 pending 摘要的重算**：无需任何专门代码——scratch 重放中每次 `append_main` 都调用 `epoch_manager.scan_chain`（既有路径），最后一次扫描即以新主链为输入产出 `e*` 的新快照（`block_hashes` / `active_features` / `epoch_base_features` / `epoch_new_features` / `cumulative_active_features` / `end_height` 全部重derive）。若重组把纪元首块也换掉了（`f = s − 1` 情形），`epoch_base_features` = 新首块引种集，同样由重扫得出。

**为什么「只允许当前纪元内重组」就足够**：白皮书与监督者冻结的不可变对象是「已归档纪元的区块 + finalized 摘要」。上表第 4 步揭示了本质——摘要输入 = (纪元自身区块, 截止纪元末的前缀)，两者都被「截断点不早于 `s`」钉死在保留前缀内；而摘要函数是纯函数。因此纪元局部性 ⇒ 摘要冻结，不需要任何额外的「摘要保护」代码。

---

## 6. 持久化一致性

### 6.1 存档可达性原则（promote 终态的合法性判据）

promote 产出的 `(M', S')` 必须满足：存在一份 chain-v2 存档（`blocks = M'`、`sleeping_branches = groupby(S')`、miners、rejection_reasons），使 `load_state + rebuild_store` 重建出与内存终态**逐项等价**的 store。

**由构造成立**：S3a 与 `rebuild_store` 的主链重放**完全同路径**（同一 `append_main` 序列）；S3c 的休眠回填与 `rebuild_store` 的分支回填同路径（`add_sleeping_branch` + branch_id 一致性校验）。差别仅是 promote 对分支块多跑了完整校验——校验不改变重放产物的派生态。

### 6.2 逐项等价论证

| 比较项 | save → load + rebuild 后 | promote 后的内存态 | 等价理由 |
|---|---|---|---|
| 主链高度与全部哈希 | `M'` | `M'` | 存档直接存 `M'`，重放同序列 |
| 账本（UTXO 集合/余额） | 对 `M'` 逐块 `append_main`（奖励+交易） | scratch 同一代码路径产物 | 同一代码、同一输入序列 |
| 纪元快照与摘要 | `scan_chain(M')` 确定性纯函数 | 同左 | 同上 |
| 语言三层（快照/纪元层/历史层） | `append_main` 重放派生 | 同左 | 同上 |
| 休眠分支集合与分组 | 逐块 `add_sleeping_branch`，`branch_id` 由块自身 `parent_hash` 重derive 并与存档比对（既有检查，`persistence.py` L369–382） | S3c 以同一函数写入 | 组键恒 = 组内首块 parent_hash；组内顺序 = 确定性写入顺序（原分组序 + 降级块按高度升序），round-trip 保形 |
| `rejection_reasons` | 纯字典落盘/回读 | S4 更新后的字典 | 同一字典 |
| 矿工注册表 | 不变 | 不变 | promote 不触碰 |

### 6.3 `rejection_reasons` 记账规则（确定性，无时间戳）

- 降级块 `d`：`reason = "reorg: demoted by promote(head=<head_hash 前 12 hex>)"`（最终格式以第二阶段实现冻结为准，唯一要求：**纯函数于输入、可重放**）。
- 提升块：删除其旧拒绝记录（如有）。
- 键为块哈希、全店唯一，无冲突可能。

### 6.4 崩溃窗口

S4 之前崩溃 → 磁盘内存皆无变化；S4 与 S5 之间崩溃 → 内存丢失、磁盘为旧档，重启回到 pre-promote 状态（磁盘最多落后内存一次变更——与 `/propose` 自动保存的既有崩溃窗口语义完全一致）。

---

## 7. 不变量清单（可测试断言形式）

> 以下 12 条均为可在 `tests/test_branch_promotion.py` 中直接断言的谓词；I-1、I-7、I-8、I-9 同时是「任意时刻」不变量（不限于重组前后）。

- **I-1 主链连续父链**：任意时刻 `main_chain()` 满足 `m_0` 为创世块 ∧ `∀ i>0: m_i.height == i ∧ m_i.parent_hash == m_{i-1}.block_hash`。（重组后必须成立；load 后亦然）
- **I-2 全店区块守恒**：promote 前后 `|M ∪ S|`（按 `block_hash` 的多重集）不变，且 `M' ∩ S' = ∅`。
- **I-3 成员转移正确**：`M' = M[0..f] + C`；`S' = (S \ C) ∪ 旧后缀`；`C ∩ 旧后缀 = ∅`。
- **I-4 保留前缀不动点**：`M'[0..f]` 与 `M[0..f]` 逐块 `block_hash` 相同。
- **I-5 已归档摘要冻结**：`∀ e < e*`：promote 前后 `summary_e` 的序列化字节相同；`summary_chain` 前缀逐项相同。
- **I-6 纪元归属稳定**：promote 后 `tip.epoch == e*`（不跨越纪元边界）；全部主链块 `epoch == height // 100`。
- **I-7 账本 ≡ 重放**：任意时刻 `utxo_ledger ≡` 对 `main_chain()` 逐块 `append_main` 重放所得账本（奖励 + 交易）。
- **I-8 语言快照全覆盖**：`∀ h ∈ [0, height]: language_snapshot_at(h) ≠ None` 且等于 `f(main[0..h])`（纪元作用域语义）。
- **I-9 语言层 ≡ 重放**：`epoch_active_features() / ever_active_features() / first_activation_epoch()` ≡ 由 `main_chain()` 重放派生；且 `ever_active` 在任意 `append_main` 序列上单调不减（重组 = 重推导事件，见 §4.3 与裁决点 D3）。
- **I-10 休眠分组一致性**：每个 `(branch_id, blocks)` 分组满足 `branch_id == 组内首块的 parent_hash`；`rebuild_store` 能复现同一分组与组内顺序。
- **I-11 原子性**：任何失败路径（E1–E7 任一不满足 / 重放校验失败 / 内部错误）之后，store 的全部可观测状态（主链、休眠、账本、纪元、语言、reasons）与调用前逐项相同。
- **I-12 promote 对合可逆性**：`promote(C)` 成功后再对旧后缀链执行 promote（其作为休眠链可达且重放校验通过），恢复 `M = 原主链`；共识态（主链/账本/语言/纪元/休眠集合）与初始态逐项相同（`rejection_reasons` 的历史记录除外——纯展示元数据，见 T-14）。

---

## 8. 测试计划（`tests/test_branch_promotion.py`，16 项）

> 构造工具：沿用 `tests/test_epoch_scope.py` 模式（`make_extension_block` + `fill_to`）；跨纪元主链用 `fill_to(100+n)` 真实校验填充。每项失败用例都附带 I-11 原子性断言（状态摘要前后相等）。

| # | 用例 | 关键断言 |
|---|---|---|
| T-01 | **纯接续（监督者验收场景）**：平票双分支（等权双矿工）后主链停滞于 H，promote 其中一支 | 新高度 `H+1`；`M' = M + [b]`；另一支保留休眠；账本含 b 的奖励 UTXO；`/chain-state` 字段兼容（HTTP 层复测） |
| T-02 | **落选者翻身（经典 reorg）**：胜者上链、败者休眠，promote 败者 | `M' = M[0..H] + [败者]`；胜者降级入休眠且 `reason` 以 `reorg:` 开头；两矿工余额互换（I-7）；胜者块全字段不变（I-2/I-3） |
| T-03 | **多级分支深重组**：分支链深度 ≥ 2（败者→其子→其孙），promote 头 | 整链按序上主链；被提升块的休眠子孙仍在休眠；中间高度语言/账本快照逐块正确（I-1/I-8） |
| T-04 | **收缩重组**：新链比原主链短（`f + k < H`） | 新 tip 高度 = `f+k`；多余旧块全部降级入休眠；I-2 守恒 |
| T-05 | **延伸重组**：新 tip 超原高度但仍在本纪元（`H < f+k ≤ t`） | 新 tip 高度正确；后续 `/propose` 可正常接续新 tip |
| T-06 | **资格拒绝：头不存在 / 孤儿链**（walk 终点在休眠空间或父缺失） | `PROMOTION_NOT_FOUND` / `PROMOTION_PARENT_MISSING`；零状态变化 |
| T-07 | **资格拒绝：结构断裂**（休眠废块高度非线性 / 环防御） | `PROMOTION_CHAIN_BROKEN`；零状态变化 |
| T-08 | **资格拒绝：后缀含已归档纪元块**（跨纪元主链，fork < s−1） | `PROMOTION_ARCHIVED_EPOCH`；已归档摘要字节不变；零状态变化 |
| T-09 | **资格拒绝：分支越出当前纪元**（含 `t+1` 高度块，或 tip 在纪元末位时接续） | `PROMOTION_EPOCH_SPAN`；零状态变化 |
| T-10 | **语义拒绝：UTXO 失效**：分支块花旧后缀创造的 UTXO | 透传 `UTXO_INVALID`（附高度）；零状态变化（I-11） |
| T-11 | **语义拒绝：语言失效**：分支块引用仅旧后缀激活过的原语（未引种）/ 重复激活保留前缀已激活原语 | 透传 `UNIMPORTED_FEATURE` / `DUPLICATE_FEATURE`；零状态变化 |
| T-12 | **语言重建正确性**：旧后缀含某原语的唯一激活记录，分支不含 | 重组后 `ever_active` 收缩（该原语移出）；`branch_active_features`（降级分组）仍含它；随后再激活该原语的提案按「新特性」路径通过校验（负测试重新成立） |
| T-13 | **纪元摘要不变 + pending 重算**：跨纪元主链（≥1 个已归档纪元）内重组 | I-5 全量断言（`summary_chain` 逐字节）；`e*` 快照 `block_hashes`/`active_features` 按新链重算 |
| T-14 | **对合性**：promote(C) 后再 promote(旧后缀链) | 主链/账本/语言/纪元/休眠集合恢复初始态（I-12）；`rejection_reasons` 允许元数据差异（断言共识态等价 + reasons 差异符合记账规则） |
| T-15 | **持久化 round-trip**：promote → save → load → rebuild | §6.2 表逐项等价（高度、哈希、余额、语言三层、休眠分组、摘要链）；`format_version == chain-v2` |
| T-16 | **原子性总检 + API 契约**：全部失败路径（T-06~T-11）状态摘要不变；三旧端点（`/chain-state` `/propose` `/eval-novscript`）响应字段超集兼容；`POST /promote-branch` 成功/失败响应形状符合附录 A | I-11；`API_SPEC` 兼容性 |

回归要求：`python -m unittest discover -s tests` 全量通过（跑前确认 28417 端口空闲）；`python -m compileall -q .` 通过。

---

## 9. 风险与开放问题

### 9.1 开放问题 X.9-9（分支选择规则）的取舍

**白皮书问题原文**：落选分支在什么可验证条件下可以成为活跃分支？「累计贡献」「节点支持」和「语言采用率」各自如何定义？

**本设计的取舍**：v1 把 promote 定义为**显式治理动作**（单机操作者显式触发；未来可换成多签/投票门槛），资格 = **纯结构安全性条件（E1–E6）+ 重放有效性（E7）**，不含任何权重/支持率/采用率阈值。

**理由**：

1. **可验证性优先**（项目最高准则）：结构条件是精确可判定的确定性谓词，测试可穷举、重放可复现；而「累计贡献」需要给休眠块定义权重语义（`weight_calculator` 现为**仅主链**累计 PoI——给休眠块计权等于改共识度量，属协议级变更），「语言采用率」当前无任何既定义指标（BUILTIN_POOL 仅 15 原语、无使用统计）。
2. **监督者最小规则是本设计的特例**：提示词 E 建议「仅当分支头 `height == 主链高度 + 1` 时允许切换/接续」——本设计 E1–E7 在 `f == H` 时恰好退化为该规则，可平滑演进，不冲突。
3. **单机仿真无自动分叉选择的场景**：无并发出块者，自动规则（最长链/最重链）既无意义也不可测；显式动作让「谁在何时切换」成为可审计的实验变量。
4. **演进钩子**：资格判定将实现为纯函数 `check_promotion_eligibility(...)`——未来插入策略层（如「分支累计 PoI ≥ 被替换后缀累计 PoI」「头高度必须 > 主链高度」）无需动重组执行机构。

### 9.2 需要监督者裁决的问题（逐条）

- **D1 重组深度**：是否放行「分叉点低于当前 tip」的深重组？本设计**放行**（本任务冻结约束已给出安全边界：纪元局部 + 无丢失 + 重放重建）；监督者旧提示词 E 只要求纯接续特例。若裁决收紧为「仅 f == H」，算法与不变量全部不变，只删 E4/E5 中深重组分支。
- **D2 分支纪元跨度**：E5 从严（分支整链 ∈ `e*`）vs 任务示例宽版（只禁已归档纪元、允许跨入未来纪元）。本设计推荐**从严**：证明面最小（§5）、重组内部不触发失忆/归档；宽版（允许分支带头跨入 `e*+1`，重组即封口 `e*`）重放路径本可支持，作为 v2 演进项。
- **D3 `ever_active` 单调性语义**（最重要）：精确化措辞「**append 序列上单调不减；重组 = 重推导，可能收缩**」（本设计推荐，与纯重放持久化天然一致）vs 字面「任何时刻只增不减」（需高水位线集合 + 升 `FORMAT_VERSION` + 重写持久化证明，违反 R3）。任务原文以「任何时刻只增不减」为示例不变量——**需监督者二选一**。
- **D4 降级原因字符串**：提议 `"reorg: demoted by promote(head=<hash 前 12 hex>)"`；请冻结格式或指定。
- **D5 API 形态**：`POST /promote-branch` 请求体 `{"head_block_hash": "…"}`（唯一精确标识——`branch_id` 组内多兄弟时有歧义）+ 新增 `GET /branches`（分组详情 + 可提升链预览 + 阻塞原因）；是否需要同时接受 `branch_id` 交叉校验。三个既有端点不动。
- **D6 并发纪律**：ThreadingHTTPServer 下 `/propose` 现状无全局状态锁（仅 `_SAVE_LOCK` 保护写盘）。建议第二阶段为 promote 加 `_STATE_LOCK` 并让 propose 复用（改动极小）；是否纳入。
- **D7 候选池防御**：promote 前断言池内无「父在受影响高度区间」的残留分组（服务流程下恒空，纯防御）；是否需要。
- **D8 展示层**：降级块的 `reason` 在 `/chain-state` 休眠列表中与「校验拒绝」类同屏展示（字符串可区分，无需新字段）；是否需要前端（线 A）额外区分样式。

### 9.3 其他风险登记

- **性能**：scratch 全量重放 O(H²)（每块 `scan_chain` 全扫）——原型 H ≤ 数百可忽略，与 `load_state` 同量级；若未来链长增长，可为 promote 单次构建做一次性批扫优化（不改变语义）。
- **复杂度集中点**：语言语义重判已由「完整校验流水线逐块重放」统一吸收（§4.5），无旁路、无特判——这是本设计最重要的简化决策。
- **测试成本**：跨纪元用例需 `fill_to(100+)` 真实校验填充（每块跑沙箱），沿用 `test_epoch_scope.py` 既有模式，预计单测总时长增加可控。
- **前端依赖**：本阶段后端先行；分支列表/对比 UI 由线 A 决定是否接入（`GET /branches` 数据已就绪）。
- **相邻隐患**（不属本阶段）：`apply_vote_result` 在库级「winner 不接 tip」时抛 `ValueError`（§3.5）；建议另行小修或登记为已知限制。

---

## 附录 A：第二阶段实现映射（预告，本阶段不实现）

| 模块 | 改动（全部为受控追加） |
|---|---|
| `chain_store.py` | 新增 `promote_branch(head_block_hash, validator=validate_block) -> PromotionResult`：walk + scratch 构建 + 原子换入；新增只读 `branch_head_candidates()` / walk 辅助；`append_main` / `add_sleeping_branch` / `apply_vote_result` 语义零改动 |
| `block_validator.py` | 新增纯函数 `check_promotion_eligibility(chain, fork_height, store)`（`stage="promotion"`，不进常规 9 检查流水线）+ 语义化错误码（附录 B） |
| `epoch_manager.py` / `novscript/*` | **零改动**（重放路径复用） |
| `server.py` | 只追加：`POST /promote-branch`、`GET /branches`；`_STATE_LOCK`（若 D6 通过）；既有三端点契约不变 |
| `tests/test_branch_promotion.py` | §8 的 16 项 |
| 文档 | `BRANCH_PROMOTION_IMPLEMENTATION.md`、白皮书 §9 落地说明、`API_SPEC.md` 追加章节 |

## 附录 B：升级错误码总表（stage = `promotion`）

| 错误码 | 触发条件（对应判定式） |
|---|---|
| `PROMOTION_NOT_FOUND` | E1：头哈希不在休眠集合 |
| `PROMOTION_CHAIN_BROKEN` | E2：链高度非线性 / 中间父缺失 / 环 / 深度超界 |
| `PROMOTION_PARENT_MISSING` | E3：链未锚定主链（根在休眠空间） |
| `PROMOTION_ARCHIVED_EPOCH` | E4：旧后缀越入已归档纪元 |
| `PROMOTION_EPOCH_SPAN` | E5：分支越出当前纪元（含未来纪元块） |
| `PROMOTION_NOT_ELIGIBLE` | E6：唯一性防御检查失败（兜底） |
| （透传）`UTXO_INVALID` / `UNIMPORTED_FEATURE` / `DUPLICATE_FEATURE` / … | E7：重放期逐块完整校验失败，外层附块高度与「第几块」上下文 |
