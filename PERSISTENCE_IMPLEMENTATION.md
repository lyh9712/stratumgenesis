# StratumGenesis v0.3 · 磁盘持久化与链数据导出实现说明

> 版本：v0.3 阶段 A　日期：2026-09-09
> 范围：新增 `persistence.py`；`server.py` 接入存档加载/自动保存/`--fresh`/导出；新增 `tests/test_persistence.py`（8 项）。

## 1. 设计目标

对应 ARCHIVE_v0_2_README.md §6「磁盘持久化」与设计白皮书 §14.5「定期导出完整链数据」：

- 链状态可落盘、可恢复、可导出；
- 恢复后的状态与保存前**完全一致**（含矿工身份与私钥，重启后仍可继续用既有矿工为 `/propose` 签名）；
- 存档损坏/版本不匹配时**明确报错并拒绝启动**，绝不静默用空链顶替；
- 导出格式与存档格式一致，供存档/研究使用。

## 2. 存档格式（data/chain_v1.json）

```json
{
  "format_version": "chain-v1",
  "blocks": [ {区块对象…} ],
  "sleeping_branches": [ {"branch_id": "<父区块哈希>", "blocks": [ {区块对象…} ]} ],
  "miners": [ {"label": "沉积者·阿砚", "public_key_b64": "…", "private_key_b64": "…"} ],
  "rejection_reasons": { "<区块哈希hex>": "kernel_compatibility: GENESIS_KERNEL_CONFLICT" }
}
```

- **区块对象**包含：height、parent_hash、proposer、prototype_version、miner_pubkey_b64、signature_bytes_b64、epoch、block_hash、proposal（kind/feature_id/specification/demo_code/test_cases）、poi（全部词元计数字段）、transactions（inputs/outputs/tx_signature_b64）。
- **bytes 一律 base64** 编码；JSON 采用 `sort_keys=True`、紧凑分隔符，输出确定性可复现。
- `format_version = "chain-v1"`：后续格式演进时递增；加载时版本不匹配直接拒绝。

## 3. 保存 / 恢复策略

### 保存

- 落盘最小权威状态：主链全部区块（含创世块）+ 休眠分支（分支标识 + 区块序列）+ 矿工注册表（**含私钥**）+ 拒绝原因表。
- 写入采用「临时文件 + 原子替换」：先写 `chain_v1.json.tmp`，`os.replace` 覆盖正式文件，中断不会留下半截存档。
- 多线程下用锁串行化自动保存，避免并发写同一 tmp 文件。

### 恢复

- 读取 JSON → 校验 `format_version` 与必要字段 → **逐区块重建并校验 SHA-256 哈希**（存储哈希与重算哈希不一致即判定损坏）。
- 用 `ChainStore.append_main` 按序重放主链：挖矿奖励、交易应用、纪元扫描全部走既有代码路径，确定性重建 **UTXO 账本与纪元快照**。
- 休眠分支经 `add_sleeping_branch` 回填并校验分支标识，不触碰账本/纪元。

### 为什么账本与快照采用「重建」而非「序列化」

1. **防漂移**：账本/快照是主链的派生状态；直接序列化缓存可能引入与主链不一致的陈旧数据，重放则保证「账本 ≡ 主链重放结果」。
2. **天然校验**：重放过程中任何缺失/重复/断链都会立即暴露（`append_main` 校验父区块与双花），等于免费的一致性检查。
3. **代码单一来源**：重建复用运行时同一条路径，不需要维护两套状态机。

## 4. server.py 接入行为

| 场景 | 行为 |
|---|---|
| 首次启动（无存档） | 创世 + 预沉积 102 演示块，**立即落盘**（维持 v0.2 演示行为） |
| 启动（有存档） | 加载并校验后继续，**不再预沉积**，主链高度与保存前一致 |
| `python server.py --fresh` | 忽略存档，从创世重建演示链（回到 102）并覆盖存档（演示复位用） |
| 每次链状态变更（成功上链 / 候选入休眠分支） | 自动保存；保存失败打印中文警告，**不影响本次内存操作结果** |
| `python server.py --export <path>` | 校验当前存档并导出到指定路径后退出（不启动服务） |
| `python persistence.py export <path>` | 等价 CLI：`persistence.py` 自带的导出命令 |
| 存档缺失/损坏/版本不匹配 | 中文明确报错并**拒绝启动**，提示使用 `--fresh` |

三个既有 API（`/chain-state`、`/propose`、`/eval-novscript`）响应契约保持不变；仅 `chain-state` 中 `miners` 数组改为按公钥字节稳定排序输出（只影响顺序，不影响字段与含义，保证「保存前/加载后」响应逐字节一致）。

## 5. 矿工私钥持久化的安全边界（必须如实声明）

- 矿工注册表**连同私钥**一起写入 `data/chain_v1.json`，否则重启后无法用既有矿工身份为 `/propose` 签名；
- 私钥为**原型本地演示密钥**：明文存于本机 JSON 存档，无加密、无密码保护；
- **无生产安全承诺**：本模块不是密钥管理系统；不用于任何真实资产、不对外部公开；
- `data/` 目录已加入 `.gitignore`，不会进入版本库。

## 6. 测试

新增 `tests/test_persistence.py` 8 项：

- 保存→加载 roundtrip 等值（主链高度、全部区块哈希、矿工注册表含私钥、休眠分支数及拒绝原因、重放账本余额与纪元快照一致）；
- 加载后 `GET /chain-state` 与保存前**逐字节一致**（HTTP 级）；
- 损坏 JSON / format_version 不匹配 / 篡改区块哈希 → 均拒绝加载；
- 存档缺失 → 自动创建并落盘（102 块）；
- `--fresh` 忽略存档回到 102，并覆盖存档；
- `export_chain` 导出与存档同格式。

全量回归：**80 项全部通过**（72 原有 + 8 新增）；`python -m compileall -q *.py tests/*.py` 通过。

## 7. 已知限制与取舍

1. JSON 全量快照：每次变更保存整个状态，区块量大时写盘成本线性增长（原型可接受，非生产存储）。
2. 无增量/追加式归档、无校验和文件、无加密；私钥明文落盘（见 §5）。
3. 原子替换依赖同一文件系统；`os.replace` 在 Windows 上可用。
4. 存档加载时的重放成本随链长线性增长。
5. 导出为「当前存档的完整副本」，不包含运行时的候选池暂存（候选池是易失的中间态，未纳入权威状态）。
6. 服务仍为单机仿真：无 P2P、无公网、无鉴权；任何文档与代码均不构成生产系统承诺。
