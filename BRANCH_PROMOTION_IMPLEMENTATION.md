# StratumGenesis 休眠分支升级 / 主链重组模块实现说明

> 阶段：v0.3 · 阶段 E（分叉兑现）
> 实现依据：`BRANCH_PROMOTION_DESIGN.md`（335 行，已验收）
> 监督者裁决：D1 深重组放行（安全边界 = 不触碰已归档纪元，I-5）；
> D2 分支纪元跨度采**从严版**（分支整链位于当前未归档纪元内）；
> D3 ever_active 采**精确化措辞**（append 单调不减；重组 = 重推导允许收缩，禁高水位线，不升格式）；
> D4 降级原因确定性字符串；D5 `head_block_hash` 定位 + `GET /branches`；
> D6 变更类入口状态锁；D7 候选池防御性断言；D8 降级原因可区分展示；
> X.9-9 promote 为显式治理动作，资格 = 纯结构安全 + scratch 重放有效性，不含权重/采用率阈值。

---

## 1. 资格判定（E1–E7）

`block_validator.py::check_promotion_eligibility(chain, fork_height, store)`
纯函数（stage="promotion"，不修改 store），在 `_walk_branch` 产出 `(C, f)` 后执行：

| 编号 | 检查 | 触发条件 | 错误码 |
|---|---|---|---|
| E1 | 头在休眠链 | 头不存在 / 头在主链 / 空链 | `PROMOTION_NOT_FOUND` |
| E2 | 链线性完整 | 父链接断 / 高度不连续 / 环 / 深度超界 | `PROMOTION_CHAIN_BROKEN` |
| E3 | 分叉父锚定主链 | 首块父不在主链 / fork 高度越界 | `PROMOTION_PARENT_MISSING` |
| E4 | 旧后缀纪元局部 | 被替换后缀首块位于已归档纪元（f + 1 < epoch_start） | `PROMOTION_ARCHIVED_EPOCH` |
| E5 | 分支纪元局部（从严） | 分支任一区块 epoch ≠ 当前纪元 | `PROMOTION_EPOCH_SPAN` |
| E6 | 唯一性（防御） | C 内重复哈希 / C ∩ M ≠ ∅ | `PROMOTION_NOT_ELIGIBLE` |
| E7 | 重放语义有效性 | scratch 重放中分支块被任一校验阶段拒绝 | 透传原错误码（如 `UTXO_INVALID` / `DUPLICATE_FEATURE` / `UNIMPORTED_FEATURE`） |

E1–E6 在 `inspect_promotion`（只读预检，供 `GET /branches` 预览阻塞原因）与
`promote_branch`（S2 步骤）共用同一纯函数。E7 不在资格函数内执行——由
`chain_store.promote_branch` 在 S3 scratch 重放时逐块完整校验（`validate_block`
九阶段流水线），保证「新世界语义」而非「旧世界资格」。

## 2. 重组步骤（S1–S4，`chain_store.py::promote_branch`）

```
S1 链回溯      _walk_branch(head_block_hash) -> (C, f)        [纯只读]
S2 结构资格    check_promotion_eligibility(C, f, store)       [纯函数]
S3 scratch 重放
   S3a 保留前缀  M[1..f] 逐块 append_main 进 scratch
   S3b 分支链     C 逐块 validate_block + append_main（E7；任一失败抛 PromotionError）
   S3c 休眠迁移   S\C 按原分组顺序 + 旧后缀 M[f+1..] 按高度升序 add_sleeping_branch
S4 原子换入    单临界区整体替换七个内部引用（唯一提交点）
```

- S4 替换的七个引用：`_main_chain`、`_sleeping_branches`、`utxo_ledger`、
  `epoch_manager`、`language_registry`、`epoch_registry`、`_language_snapshots`。
- S3 全程在全新 `ChainStore()` scratch 上执行；任何异常（含 `PromotionError`
  与未预期 Exception）只丢弃 scratch，live store 零中间态（I-11）。
- 依赖注入：`validator` / `eligibility_checker` 默认延迟 `from block_validator`
  导入（避免循环导入），测试可注入替代实现。

## 3. 失败回滚点

| 失败点 | 行为 | 证据 |
|---|---|---|
| S1 walk 失败 | 返回 rejected + 错误码，live 不动 | T-06/T-07 + `_state_digest` 前后相等 |
| S2 资格失败 | 返回 rejected + 错误码，live 不动 | T-08/T-09 + 摘要链/快照逐项不变 |
| S3a/b 重放失败 | 返回 rejected + 原错误码，scratch 丢弃 | T-10/T-11 + 全量状态不变 |
| S3c 异常 | 返回 rejected（`PROMOTION_REPLAY_FAILED`） | T-16 原子性用例 |

`_state_digest`（主链哈希 / 休眠分组 / 账本余额 / 逐高度语言快照 / 纪元快照）
是失败路径「前后逐项相等」的统一断言工具（I-11）。

## 4. 不变量与对应用例

| 不变量 | 内容 | 用例 |
|---|---|---|
| I-1 | 主链连续父链（promote 后重验） | T-03 |
| I-2 | 全店区块守恒（promote 不复制不销毁） | T-04 |
| I-3 | 对象原样搬运（被提升/降级块全字段不变） | T-02 |
| I-5 | 已归档纪元摘要字节冻结（summary_chain 逐项不变） | T-08/T-13 |
| I-7 | 账本 ≡ 重放（余额随新链重算） | T-01/T-02/T-10 |
| I-8 | 语言快照逐高度覆盖（重组后重建） | T-03/T-15 |
| I-11 | 失败路径全量状态不变（原子性） | T-06…T-11/T-16 |
| I-12 | 对合性：提升(C) 后再提升(旧后缀链) 恢复原主链 | T-14 |

## 5. 语言层与纪元层一致性

- **语言回滚 = 不重放**：不写反向补丁。分支激活经既有 `append_main` 逻辑
  按新链重新判定「新特性 vs 引种」；旧后缀携带的唯一激活记录离开主链后，
  `ever_active_features()` 收缩（D3 精确化措辞，T-12）。
- `branch_active_features` 仍是休眠只读视图（按分组首块父哈希定位），
  不进主链态；被降级块的分组视图保留其激活记录（T-12）。
- 纪元层：只允许在当前未归档纪元内重组（E4/E5，I-5）；当前纪元摘要为
  pending 时按新链重算（`end_height` / `block_hashes` 更新），已归档纪元
  summary_chain 前缀不变（T-13）。

## 6. API 契约（阶段 E 追加）

- `GET /branches`（新增端点，只读）：`{branches: [{branch_id, blocks: [...]}], sleeping_count}`；
  每块含 height/epoch/miner_label/feature_name/description/demo_code/test_cases/
  block_hash_b64/**reason**（降级块为 `reorg: demoted by promote(head=…)`，与校验拒绝
  原因以 `reorg:` 前缀区分，D8）/promotion_status/promotion_error_code/promotion_message/
  fork_height/new_tip_height（inspect 预览，D5）。
- `POST /promote-branch`（新增端点）：body `{head_block_hash}`（D5 定位方式，
  空参/头不存在返回 success=false + error_code）；成功返回
  success/is_promoted/chain_height/fork_height/old_tip_height/new_tip_height/
  promoted_hashes/demoted_hashes（b64）。
- 三个既有端点（/chain-state、/propose、/eval-novscript）只追加字段，未改名删除；
  `/propose` 与 `/promote-branch` 共享 `_STATE_LOCK`（D6，锁顺序 _STATE_LOCK 外 →
  _SAVE_LOCK 内）；`api_promote_branch` 前置候选池防御断言（D7，池非空即拒）。

## 7. 已知限制

- 单机内存仿真：promote 是同步库调用，无网络投票窗口、无拜占庭容错。
- 资格不含权重/采用率阈值（X.9-9）：promote 是显式治理动作，策略层演进钩子
  已留（`eligibility_checker` 依赖注入）。
- 分支纪元跨度取 D2 从严版（分支整链在当前未归档纪元内）；宽版（跨纪元重组）
  留待 v2，本版不实现。
- 休眠分组按首块父哈希聚合；同父多分支共组，promote 用 `head_block_hash`
  精确到链头（D5），组内其余链保持休眠。
- 重组后 `rejection_reasons` 记账：提升块删旧记录、降级块写确定性 reorg 原因；
  存档 round-trip 后记账随 state 持久化（T-15 覆盖链侧，记账字段由既有
  save/load 契约承载）。
- 性能：重组为 O(店)，对 100 块级预沉积链无压力；未做增量优化（非目标）。
