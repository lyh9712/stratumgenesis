# StratumGenesis v0.3 阶段 B · mock 纪元摘要模块实现说明

> 版本：v0.3 阶段 B　日期：2026-09-10
> 范围：新增 `epoch_summary.py`；`epoch_manager.py` 追加摘要字段与摘要链；`server.py` 的 `/chain-state` 追加摘要字段；`persistence.py` 加载时逐块验签（阶段 A 遗留小修）；`index.html` 已归档纪元可折叠摘要卡；新增 `tests/test_epoch_summary.py`（10 项）。

## 1. 设计目标

实现设计白皮书 §7.2–7.4（多节点并行压缩与摘要投票）的单机仿真版：

- 纪元边界（主链追加使 `height % 100 == 0`）确定该纪元的官方摘要；
- 用 2–3 套确定性规则模板生成摘要候选，按历史贡献权重加权投票选出胜者；
- 全程 mock：**不调用任何真实 LLM 或网络**；同一状态可复现；
- 摘要确定即不可变；为「大断层事件」维护摘要链钩子；
- 摘要流程绝不触碰区块合法性、UTXO 账本、休眠分支逻辑。

## 2. 数据模型（epoch_summary.py）

```python
SummaryCandidate: candidate_id / text / producer_label / producer_pubkey / weight
EpochSummary:     epoch_number / method_label / status / candidates /
                  winner_candidate_id / winner_producer_label / final_text / tie_occurred
```

- `method_label = "mock-rule-v1"`（未来真实 LLM 接入时改为如 `llm-summary-v1`）；
- 三套模板名（即候选 id）：`keyword-top`（特性关键词词频 Top3）、`contributor-distribution`（贡献者分布）、`first-last-narrative`（首末特性串讲）；
- `EpochSnapshot` **追加**两个字段（既有字段不删不改）：
  - `summary: EpochSummary | None`（未封口为 None）；
  - `summary_status: str`（`pending` / `finalized`）；
- `EpochManager` 追加 `_summary_chain`（按纪元顺序的已确定摘要链）与 `summary_chain()` 读取方法。

## 3. 确定性生成与投票规则

1. **生成**：纯函数 `generate_candidates(epoch_number, epoch_blocks, method_label)`，只读该纪元主链区块（proposal 文本、生产者、高度），产出 3 份候选；
2. **生产者**：该纪元内去重矿工（公钥, 标签）按公钥字节排序，候选轮流归属（确定性）；
3. **投票**：`vote_summary()` 用 `calculate_historical_weights(主链截止纪元末块前缀)` 计票，权重仅来自主链（休眠分支无权重）；
4. **平票**：按候选 id（模板名）排序取首，`tie_occurred=True` 显式记录；
5. **触发**：`EpochManager.scan_chain()` 仅在主链已越过纪元边界（存在 `height >= (epoch+1)*100` 的区块）时对已归档纪元确定摘要。

### 为什么重放可复现（与阶段 A 持久化的协同）

摘要输入只有两份**恒定数据**：该纪元自身区块（主链只追加不可变），以及截止该纪元末块的主链前缀。因此：

- save → load 重放得到的摘要与保存前**逐字段一致**（候选、得票、胜者、finalized 状态、方法标签）；
- finalized 后继续追加区块，旧纪元摘要不再变化；
- **不引入第二套序列化**：EpochSnapshot/摘要仍不落盘，全部由主链重放重建，杜绝与主链漂移。

## 4. 接口与前端

### GET /chain-state（追加字段，不删旧字段）

- `epochs[i].summary`：已归档纪元为 finalized 摘要对象（含 `status/method_label/final_text/winner_candidate_id/winner_producer_label/tie_occurred/candidates[]`）；未封口纪元为 `null`；
- `epochs[i].summary_status`：`"pending"` / `"finalized"`；
- 顶层追加 `summary_chain`：按纪元顺序的已确定摘要数组（大断层事件钩子）。

### index.html

- 已归档且已确定摘要的纪元，在纪元标签下方追加原生 `<details class="epoch-summary">` 可折叠摘要卡（胜者、最终摘要文本、三份候选与权重、平票标记）；
- 纯追加式：不修改既有地层动画、钻探考古、详情面板、程序画廊任何逻辑与样式。

## 5. 未来替换为真实 LLM 摘要的接口点

1. 保留 `SummaryCandidate` / `EpochSummary` 数据模型与投票/归档语义；
2. 将 `generate_candidates()` 内的三套规则模板替换为「统一压缩提示词 + 真实 LLM 并行生成」：输入旧纪元完整语言规范，输出不超过 2000 token 的摘要候选；每个候选仍带 template 名与生产者标签；
3. 投票输入仍为 `calculate_historical_weights` 的历史贡献权重，语义不变；
4. `METHOD_LABEL` 切换为 `llm-summary-v1`；若 LLM 不可复现，需将生成的候选/结果**序列化进存档**（届时才需要扩展 format_version 与存档结构，阶段 B 刻意不做）。

### 风险提示（必须保留）

- 真实 LLM 摘要存在**信息衰减与幻觉风险**：若某节点压缩时幻觉出不存在特性，只能靠多数派投票淘汰；
- 摘要链**线性低速增长**，未来需「大断层事件」主动上限（白皮书 §7.5）；
- 落选候选按白皮书 §7.3 永久归档为「备选摘要」供考古参考（`candidates` 全量保留即此语义）；
- 当前 mock 模板只能做词频/分布/串讲式统计摘要，不代表语言规范级压缩质量。

## 6. 阶段 A 遗留小修（随本阶段一并提交）

1. **加载验签**：`persistence.load_state()` 在既有哈希校验之外，用 `crypto_key.verify_block_signature` 逐块补验 ECDSA 签名（创世块跳过）；仅篡改签名的存档现在会被拒绝加载（错误含「签名校验失败」）。
2. **编译命令统一**：全部文档中的编译检查命令统一为 `python -m compileall -q .`（PowerShell 不展开 `*.py` 通配符的兼容性修复），已实测退出码 0。

## 7. 测试

新增 `tests/test_epoch_summary.py` 10 项：边界触发时机（99 未封口 / 100 封口）、确定性（同参数两次构建逐字段一致）、历史权重生效（贡献最多矿工胜出）、平票确定性回退（单矿工全等权 → 模板名取首 + tie 标记）、finalized 后不可变、休眠分支不产生摘要、摘要链有序、`/chain-state` 追加字段存在、save→load 摘要逐字段一致、篡改签名拒绝加载。

全量回归：**90 项全部通过**（80 原有 + 10 新增）；`python -m compileall -q .` 退出码 0。

## 8. 已知限制与取舍

1. mock 模板摘要不是语言规范级压缩，仅为演示与链路验证；
2. 单机仿真：无真实多节点并行、无广播、无真实投票网络；
3. 权重仅累计主链，休眠分支不参与（与全局共识语义一致）；
4. 平票回退按模板名排序，规则简单但已显式记录 tie_occurred；
5. 摘要仍未序列化进存档，完全依赖确定性重放——这是刻意的设计取舍（防漂移），代价是未来接真实 LLM 时必须扩展存档格式。
