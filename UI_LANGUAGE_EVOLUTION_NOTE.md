# StratumGenesis UI 语言地层可视化变更说明（UI_LANGUAGE_EVOLUTION_NOTE.md）

> 日期：2026-09-10
> 范围：仅修改 `index.html`（并行线 A 语言地层可视化 + 收尾修正）
> 版本：v0.3 · 阶段 D 后端契约（纪元作用域语言 + 引种）之上

## 变更声明（重要）

本文件描述 **UI 变更**，不改动 API 契约与后端行为。

- ✅ **只修改 `index.html`**；未改动任何 `.py` 文件、`server.py`、`API_SPEC.md` 或其它文档
- ✅ **未改动任何 API 请求路径与字段名**（仍为 `/chain-state`、`/propose`、`/eval-novscript`）
- ✅ 新增 DOM 一律使用新 id / class（`#lang-status`、`#langmap*`、`.epoch-open` 等），不触碰任何既有 id / class
- ✅ 全部既有交互保留：点击岩层详情、钻探考古手电筒、推演-粒子-凝聚/碎裂动画、纪元抬升、程序画廊、沙箱弹窗
- ✅ 纯 CSS / 原生 JS / 内联 SVG，无外部资源、不联网

## 本轮 UI 改动点（语言地层可视化收尾）

1. **修正「当前纪元已激活原语」字段优先级**（监督者指出的错误）：原解析链首选
   `state.current_epoch_active_features`——该字段**不存在**（上一版提示词笔误），永远走兜底。
   已改为阶段 D 权威契约的优先级链（见下「字段来源与降级策略」）。
2. **同步修正模块注释**：顶部语言地层区块的字段说明（`current_active_features` 名字
   deprecated 但值即「当前纪元内有效」；`epochs[].active_features` 是逐纪元字段，不用于推导「当前」）。
3. 清理对不存在字段的全部引用（`current_epoch_active_features` 已在全文件清零）。

## 新 UI 要素 → id / class 对照

| 要素 | id / class | 数据来源 |
|---|---|---|
| 顶部状态栏「语言版本 · 第 N 纪元」 | `#lang-status` / `#lang-status-text` / `.lang-num` | `currentEpochFeatures()`（见降级策略）+ `currentEpochEn()` |
| 失忆提示「较上一纪元失去 N 个原语」 | `#lang-memory-loss`（`.loss`） | 当前纪元集 vs `prevEpochEndSet()`（上一纪元末 `blockFeatures`） |
| 本纪元原语明细 chips（点击定位岩层） | `#lang-detail` / `.lang-chip` | 当前纪元集 + `firstActivationBlock()` |
| 纪元开篇带（核心叙事：引种/失忆） | `.epoch-open`（`.eo-title`/`.eo-line`/`.eo-loss`/`.eo-names`/`.eo-meta`/`.archived`） | `epochOpeningInfo()`：首块 `activation` + `epoch_base_features` 并集，`prevEpochEndSet()` 差集 |
| 语言地层侧栏（每原语一行：纪元活跃/失忆状态） | `#langmap` / `#langmap-close` / `.lang-row`（`.lr-head`/`.lr-name`/`.lr-desc`/`.lr-state`/`.lr-meta`）/ `.lang-bar` / `.lang-cells` / `.lang-cell`（`.on`/`.cur`） | `featureTimeline()` + `currentEpochFeatures()` + `firstActivationBlock()` |
| 原语详情（点击 .lang-row / .lang-cell） | `#langmap-detail`（`.kv`/`.warn`/`.empty`/`.lang-fill`） | 首次激活高度/纪元、本纪元状态、开篇引种、失忆清单 |
| 岩层详情「语言版本区」 | `.lang-block`（`.lang-sub`/`.lang-feats`/`.lang-act` 含 `.new` 新沉积 / `.revive` 引种 / `.empty`） | `b.activation`、`blockFeatures(state, b)`、`originEpochOfFeature()` |
| 点击原语定位岩层高亮 | `.lang-hit`（叠加于 `.layer` / `.epoch-open`） | `.lang-chip` / `.lang-cell` 点击 |
| 沙箱「未引种」人话提示 | `.sb-revive`（`.sb-revive-tag`/`.sb-note` + 按钮） | `/eval-novscript` 响应 `error_type`/`error_message` 经 `SB_UNIMPORTED_PATTERNS` 语义识别 |
| 程序画廊引种状态 | `.work .need`（`.pending` 未引种 / `.ok` 已引种）/ `.work .need-fix` / `.work .code` | 作品 `needs` 原语 vs `currentEpochFeatures()`；执行走真实 `/eval-novscript` |
| 提案示例填充闪光 | `#proposal-form.flash` | `fillProposalExample()`（不自动提交） |

## 字段来源与降级策略

权威数据 = `GET /chain-state` 的 `blocks[].activation`（本块新激活/引种）与
`blocks[].language_features`（该高度当时可用集，纪元作用域）；顶层/纪元聚合字段为
增强数据，缺失或为空一律就地推导，不报错、不白屏。

「当前纪元已激活原语」`currentEpochFeatures(state)` 的解析链（修正后）：

```js
① state.current_active_features   // 名字 deprecated，但值语义已是「当前纪元内有效」，第一优先
② 链顶块 state.blocks[tip].language_features  // 该高度当时可用集（纪元作用域）
③ state.cumulative_active_features            // 历史累计（仅兜底参考，语义为「曾经激活过」）
④ 沿主链累计全部 blocks[].activation          // 自行推导（最后兜底）
```

要点：
- **不要**依赖 `epochs[].active_features` 推导「当前」语言——它是逐纪元字段（纪元内有效）；
- **不要**新增不存在的字段名（如 `current_epoch_active_features`）；
- 某高度可用集 `blockFeatures()`：`language_features` 缺失时按「≤该高度的 activation 累计」推导；
- 纪元开篇可用集 `deriveBaseSet()`：以首块快照为准（含首块自身引种），`epoch_base_features`
  存在且非空时并入；
- 失忆数 = 上一纪元末可用集 − 本纪元开篇可用集（`prevEpochEndSet()` 第 0 纪元返回 null）。

## 视觉验收清单

1. 页面正常渲染，浏览器控制台无报错；
2. 第 1 纪元（height 100）出现「纪元开篇」带，文案正确（第 0 纪元为「创世内核」）：
   引种数取首块 activation / `epoch_base_features`，失忆数 = 上一纪元末可用集 − 本纪元开篇可用集；
3. 岩层详情显示 activation 与 language_features（预沉积块应显示「本层不改变语言」）；
4. 顶部「当前纪元已激活原语」在干净链上显示 0 个；
5. 提交提案「减法」后新岩层出现、详情显示「本层新沉积：-」、语言地层里 - 的首次激活高度更新；
6. 程序画廊作品能在沙箱弹窗真实执行（走 `/eval-novscript`，不伪造结果）；
7. 未引种原语显示「需引种」提示（`.sb-revive`，含可点击的引种提案示例）；
8. 既有交互回归：钻探手电筒、纪元抬升、粒子沉积/碎裂、纪元摘要卡、沙箱弹窗全部照常。

## 已知说明

- 预置池原语说明（`PRIMITIVE_POOL`）与后端 `BUILTIN_POOL` 对应，仅用于展示与提案示例；
  实际可用性以 `/chain-state` 返回与 `/eval-novscript` 真实执行为准；
- 沙箱「未引种」提示基于错误类型/消息的模式识别（`SB_UNIMPORTED_PATTERNS`），只做展示增强，
  不拦截、不改写任何请求；
- 本文件不登记归档索引（由监督者最后统一处理，避免多线写同一索引文件）。
