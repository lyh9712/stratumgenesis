# StratumGenesis 纪元基础框架实现说明

## 1. 模块目标

本次实现只覆盖纪元基础设施：

- `height // 100` 的纪元编号计算；
- 区块构造时自动计算并校验 `epoch`；
- 主链到达纪元边界时生成内存 `EpochSnapshot`；
- 旧纪元通过 `archived=True` 做逻辑只读标记；
- 休眠分支区块可以计算自身 epoch，但不会生成或修改主链纪元快照。

原始区块仍保存在主链内存结构中，不会被删除或压缩。

## 2. 关键规则

```text
EPOCH_BLOCKS = 100
epoch = height // 100
```

边界语义：

- height 0–99 属于 epoch 0；
- height 100 属于 epoch 1，并触发 epoch 0 的结束/归档标记；
- height 100–199 属于 epoch 1；
- 只有主链追加 height=100、200、300……时，才触发纪元快照扫描；
- 休眠分支不触发纪元快照。

## 3. 源码变更

### `epoch_manager.py`

新增：

- `EpochSnapshot`
- `EpochManager.get_epoch_of_block()`
- `EpochManager.scan_chain()`
- `EpochManager.get_epoch_snapshot()`
- `EpochManager.snapshots()`

### `block_model.py`

`Block` 新增 `epoch` 字段：

- 默认由 `height // 100` 自动计算；
- 显式传入不一致的 epoch 时构造立即抛出 `ValueError`；
- epoch 纳入 `canonical_bytes()`；
- epoch 也因此纳入区块 SHA-256 哈希和 ECDSA 签名内容。

### `block_validator.py`

结构校验阶段增加：

```text
block.epoch == block.height // 100
```

不一致时返回：

```text
stage = structure
error_code = EPOCH_MISMATCH
```

### `chain_store.py`

主链区块成功追加并完成 UTXO 更新后，调用 `epoch_manager.scan_chain()`。

休眠分支 `add_sleeping_branch()` 不调用纪元管理器，因此不会产生纪元结束快照。

## 4. 演示与测试

演示脚本：

```bash
python demo_epoch.py
```

演示实际输出包含：

- height=1、99、100、101、102 的 epoch 编号；
- epoch 0 快照范围 `0-99`；
- epoch 0 的 `archived=True`；
- epoch 1 的 `archived=False`；
- 休眠 height=103 区块的 epoch=1，以及快照数量不变。

单元测试：

```bash
python -m unittest discover -s tests -v
```

测试覆盖：

- 自动纪元编号；
- 构造时不一致 epoch 拒绝；
- 结构校验阶段 epoch 篡改拒绝；
- height=99/100 边界；
- 主链到达边界生成归档快照；
- 休眠分支只计算 epoch、不生成快照。

## 5. 验收结果

已执行：

```bash
python demo_epoch.py
python -m unittest discover -s tests -v
python -m compileall -q *.py tests/*.py
```

结果：

```text
Ran 64 tests
OK
```

其中包含原有 NovScript、区块、ECDSA、UTXO、候选池/投票测试以及新增纪元测试。

## 6. 本版本暂未实现

本模块明确不实现：

- LLM 纪元摘要生成；
- 摘要候选投票和官方摘要选择；
- 跨纪元引种提案；
- 大断层事件；
- 摘要链压缩或摘要替代原始区块；
- P2P 网络和分布式纪元协调；
- 磁盘归档和持久化恢复；
- 真实 LLM 或 tokenizer；
- 可交易代币和现实金融功能。

## 7. 已知限制

- 快照是单机内存元数据，进程退出后丢失；
- `archived=True` 是逻辑只读标记，不是操作系统文件权限；
- `EpochSnapshot.block_hashes` 当前按规范使用列表，调用方应视为只读快照，不应修改；
- 当前扫描采用主链完整重扫，未做增量索引；
- 未来 LLM 摘要可能发生信息衰减和幻觉，摘要链仍可能线性低速增长；
- 整体共识仅适合小规模仿真网络；
- 纯非金融激励存在参与者流失风险；
- 复用的 NovScript 沙箱是教学级纯计算隔离，不是生产安全容器。
