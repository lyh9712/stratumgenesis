# StratumGenesis 候选区块池与历史贡献加权投票原型

## 1. 模块实现简要说明

本次新增的是单机内存仿真层：

```text
合法候选区块
    ↓
CandidatePool：按 (parent_block_hash, target_height) 分组
    ↓
WeightCalculator：只从主链区块累加 miner_pubkey 的 standard_total_tokens
    ↓
ConflictVoter：单候选直接获胜；多候选按历史权重计票；平票全部休眠
    ↓
ChainStore：winner 追加主链，losers / tie candidates 保存休眠分支
```

### 关键规则

- `miner_pubkey` 是 mock 身份字符串；`mock_sign()` 只返回字符串标记，不执行 ECDSA；
- 区块仍为 `frozen=True` dataclass，区块哈希为规范化内容的 SHA-256；
- 候选池只接收 `block_validator.validate_block()` 已通过的候选；
- 历史权重只遍历主链已确认区块，休眠分支绝不计入权重；
- 多候选权重最高者胜出；
- 权重完全相等时返回 `status="vote_tie"`、`winner=None`，全部候选进入休眠分支；
- 本阶段没有网络投票窗口，投票由单机函数同步完成。

代码注释与本文档保留项目已知局限：摘要未来会产生信息衰减和幻觉风险，摘要链仅线性低速增长；共识只适配小规模仿真网络；沙箱是教学级纯计算隔离，不是生产安全容器；非金融激励存在参与者流失风险。

## 2. 新增和更新源码

| 文件 | 作用 |
|---|---|
| `miner_identity.py` | `mock_sign(miner_pubkey, payload_hash)` 身份/签名标记层 |
| `candidate_pool.py` | `CandidatePool`、`CandidateGroupKey`，按父哈希和目标高度分组 |
| `weight_calculator.py` | `calculate_historical_weights(main_chain)` 历史贡献权重 |
| `conflict_voter.py` | `VoteTally`、`VoteResult`、`resolve_conflict()` |
| `chain_store.py` | 新增 `apply_vote_result()`，对接胜者主链追加和落选者休眠存储 |
| `block_model.py` | 保留旧版 `proposer` 兼容字段，新增 `miner_pubkey`、`mock_signature` 并纳入哈希 |
| `demo_vote_conflict.py` | 合法区块、候选池、历史权重冲突投票和休眠分支演示 |
| `tests/test_voting_pool.py` | 投票池与权重规则测试 |

## 3. 测试结果

已执行验收命令：

```bash
python demo_vote_conflict.py
python -m unittest discover -s tests -v
python -m compileall -q .
```

观察结果：

- 演示中 height=0 创世块存在；
- height=1 的矿工 A 区块通过校验并进入主链；
- height=2 的两个合法候选来自不同矿工，历史贡献更高的矿工 A 候选胜出；
- 矿工 C 候选被保存到休眠分支；
- 联合测试共 48 项全部通过：原有 43 项 + 新增投票池 5 项；
- Python compileall 检查通过。

## 4. 原型暂未实现清单

本阶段明确不实现：

- P2P 网络、节点发现、网络广播、网络投票窗口；
- 真实 ECDSA、密钥对、签名验证和身份认证；
- UTXO、转账、账户余额和可交易代币；
- 纪元、每 100 区块抬升、摘要压缩、摘要投票、引种提案；
- 真实 LLM 调用和真实标准 tokenizer；
- 磁盘持久化、数据库、区块导入导出；
- 分布式节点、拜占庭容错、网络分区和真实共识；
- 更复杂的分支升级、分支切换和跨分支合并；
- 自动候选收集窗口、超时、重同步和网络视图协调；
- 投票权重防女巫机制、身份注册和外部捐赠池。

## 5. 已知限制

1. **平票处理简单**：当前平票直接把所有候选保存为休眠分支，不重投、不延长窗口，也不自动选择分支。
2. **mock 签名不是真实密码学**：`mock_signature` 只用于展示字段，不能证明区块来源或防篡改。
3. **无网络投票窗口**：候选集合由本地调用方显式提交，不模拟消息延迟、重复消息或节点视图差异。
4. **权重依赖主链输入**：计算器只接受调用方传入的主链列表；它不会自行验证主链历史，也不会读取休眠分支。
5. **单机状态易失**：主链、候选池和休眠分支只存在内存中，进程退出即丢失。
6. **内核兼容性仍是原型规则**：当前校验器使用关键词规则，无法覆盖复杂的语义组合冲突。
7. **摘要风险尚未在本模块执行**：未来多节点 LLM 摘要仍会面临信息衰减和幻觉风险，摘要链仍可能线性增长。
8. **规模边界明确**：整体共识设计仅面向小规模仿真网络，不宣称具备商用公链扩展能力。
9. **激励风险明确**：系统无金融奖励，只有链内历史贡献权重和署名；长期参与者可能流失。
10. **沙箱安全等级有限**：复用的 NovScript 沙箱是教学级纯计算隔离，不是生产安全容器。
