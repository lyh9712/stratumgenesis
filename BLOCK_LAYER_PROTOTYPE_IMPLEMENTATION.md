# StratumGenesis 最小区块层原型实现说明

## 1. 简要模块实现说明

本阶段实现单机内存区块层，不实现 P2P 网络或完整共识。模块链路为：

```text
Proposal + PoI material
        ↓
Block dataclass + canonical JSON + SHA-256
        ↓
BlockValidator（五阶段顺序校验）
        ↓
ChainStore（主链 / 休眠分支）
```

校验顺序严格为：

1. 结构、父区块和高度一致性；
2. 创世内核兼容性；
3. mock tokenizer PoI 重计数和门槛；
4. demo/test_cases 的 NovScript 解析；
5. demo/test_cases 的 `run_sandbox()` 执行和预期值比较。

所有区块、提案、PoI 记录、测试用例和校验结果数据类均使用 `frozen=True`。`ChainStore` 也使用 frozen dataclass，并通过受控内部快照更新方法维护单机内存状态。

## 2. 源码文件列表

| 文件 | 职责 |
|---|---|
| `block_model.py` | `TestCase`、`Proposal`、`PoiRecord`、`Block` 数据类；规范化 JSON；SHA-256 区块哈希；创世区块 |
| `mock_tokenizer.py` | 确定性的 `mock-tokenizer-v1`；返回 input/output/total token 计数 |
| `chain_store.py` | 主链和休眠分支的内存存储；父区块查找；显式主链追加和分支保存 |
| `block_validator.py` | 五阶段完整区块合法性校验，返回 `ValidationResult` |
| `demo_block.py` | 合法/非法候选和合法休眠分支的端到端演示 |
| `tests/test_block_layer.py` | 区块层核心场景的单元测试 |

## 3. 运行验证结果

已执行：

```bash
python -m unittest discover -s tests -v
```

区块层测试全部通过，覆盖：

- 合法区块追加主链；
- 高度错误；
- 父区块不存在；
- 违反创世内核；
- PoI token 不足；
- PoI 声明计数不一致；
- demo 语法错误；
- 测试程序语法错误；
- 沙箱测试预期不匹配；
- 沙箱测试运行失败；
- 合法候选存入休眠分支；
- 区块不可变性；
- 创世区块与父哈希关联。

也应执行：

```bash
python -m unittest discover -s tests
python demo_block.py
```

## 4. 原型暂未实现清单

本模块明确不实现：

- P2P 网络、网络广播、节点发现和网络重传；
- ECDSA 签名、密钥对和身份认证；
- UTXO、转账、账户余额和任何可交易代币；
- 加权投票、冲突投票窗口和自动主链选择；
- 纪元、每 100 区块抬升、摘要压缩、摘要投票和引种提案；
- 真实 LLM 调用和真实标准 tokenizer；
- 磁盘持久化、数据库、区块导入导出；
- 分布式节点、拜占庭节点、网络分区和真实共识；
- 语言扩展的动态注册与执行；
- 列表、字符串、布尔值、`if`、循环、宏和模块系统。

休眠分支在本阶段只保存为内存候选集合，不实现分支投票、分支升级或分支切换。

## 5. 已知限制

- mock tokenizer 只是流程测试替身，不代表最终协议的标准分词器；
- 创世内核兼容性检查当前使用明确关键词规则，无法覆盖复杂隐性语义冲突；
- 沙箱是教学级纯计算隔离，不是生产安全容器；
- 共识相关设计仅适配小规模仿真网络；本模块甚至尚未实现真实节点通信；
- 未来纪元摘要会出现信息衰减和幻觉风险，摘要链也只是线性低速增长；本模块不实现摘要机制，但这些风险必须在后续模块中保留；
- 纯非金融激励可能导致参与者流失，本区块层不提供任何金融激励。
