# StratumGenesis 单机 UTXO 账本模块实现说明

## 1. 模块定位

本模块实现单机内存版 UTXO 账本、区块奖励、交易签名、双花检测和余额查询。它属于 StratumGenesis 的学术实验原型，不是商用公链，也不是加密货币系统。

链内 UTXO 凭证只用于实验内部记账，不存在现实货币价值，不支持现实资产兑换。UTXO 余额与投票权重完全隔离：投票权重仍然只由主链已确认区块的 `standard_total_tokens` 累计得到，余额不会增加或减少投票权重。

## 2. 数据与处理流程

```text
Transaction(inputs, outputs, tx_signature)
        ↓
对去掉 tx_signature 的 canonical transaction bytes 签名
        ↓
Block.transactions 纳入区块 canonical_bytes / SHA-256 哈希
        ↓
第 6 步 UTXO 校验：未花费、所有权签名、输入金额 >= 输出金额
        ↓
只有主链成功追加时：发放挖矿奖励 + 原子应用交易
```

### UTXO 和交易

- `UTXO(tx_hash, output_index, pubkey, amount)` 表示一个可花费输出；
- `Transaction` 的输入引用账本中已有 UTXO；输出生成新的 UTXO；
- 当前原型一笔交易使用一个 `tx_signature`，要求所有输入属于同一公钥；多签/聚合签名暂不实现；
- 允许零手续费，但输入总金额不得小于输出总金额；差额在本原型中不自动作为手续费扣除，演示交易显式创建找零输出；
- 输出的交易哈希由交易无签名规范化内容确定，输出索引构成 UTXO 唯一键。

### 区块与账本

`Block.transactions` 纳入区块规范化序列化，因此会影响区块 SHA-256 哈希；`signature_bytes` 仍排除在区块签名和哈希输入之外。区块成功追加主链时，`ChainStore.append_main()` 会先验证交易，再更新主链、生成矿工奖励并应用交易。休眠/落选区块只可保存到分支集合，不会触碰 UTXO 账本，也不会生成奖励。

## 3. 文件列表

| 文件 | 作用 |
|---|---|
| `utxo_model.py` | `UTXO`、`Transaction`、交易 canonical bytes、交易哈希和交易签名构造辅助函数 |
| `utxo_ledger.py` | 内存未花费集合、奖励生成、交易验证/应用、双花检测、余额查询 |
| `block_model.py` | Block 新增 transactions，并把交易内容纳入 canonical bytes 与区块哈希 |
| `block_validator.py` | 在沙箱之后增加第 6 步 UTXO 交易校验 |
| `chain_store.py` | 主链追加时更新 UTXO；休眠分支不更新；新增 `apply_vote_result` 仍只对胜者应用主链逻辑 |
| `demo_utxo.py` | 奖励、转账、余额和双花完整演示 |
| `tests/test_utxo.py` | UTXO 模块测试 |

## 4. 安全与实验边界

- 使用现有 `ecdsa` 模块验证交易签名；
- 私钥只由演示/调用方以内存变量持有，本模块不做密钥存储；
- 无 P2P、无磁盘持久化、无账户系统、无现实资产兑换；
- 无手续费；
- 无 UTXO 余额参与投票权重的路径；
- 休眠和落选区块不生成奖励、不消费输入、不生成输出；
- 沙箱仍是教学级纯计算隔离，不是生产安全容器；
- 共识整体仍只适配小规模仿真网络；
- 未来纪元摘要可能发生信息衰减和幻觉，摘要链只会线性低速增长；
- 纯非金融激励可能导致参与者流失。

## 5. 验收结果

已执行：

```bash
python demo_utxo.py
python -m unittest discover -s tests -v
python -m compileall -q *.py tests/*.py
```

观察到：

- height=1 区块成功生成 100 单位矿工奖励；
- A 向 B 转账 40，并生成 A 的 60 找零，余额变为 A=160、B=40；
- 重复消费已花费 UTXO 时，第 6 步返回 `UTXO_INVALID`，主链高度不变；
- 联合测试共 58 项全部通过。

## 6. 原型暂未实现清单

- P2P 网络和网络广播；
- 磁盘持久化和账本恢复；
- UTXO Merkle 结构、数据库索引和大规模性能优化；
- 多输入多所有者的多签/聚合签名；
- 手续费、找零自动推导和费率市场；
- ECDSA 密钥存储、轮换、撤销和硬件保护；
- UTXO 与现实资产兑换；
- 纪元、摘要、引种提案；
- 真实 LLM、真实 tokenizer；
- 完整加权投票窗口和分布式共识；
- 任何可交易代币或金融功能。
