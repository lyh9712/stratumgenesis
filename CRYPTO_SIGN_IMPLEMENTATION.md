# StratumGenesis ECDSA 区块签名原型实现说明

## 1. 实现摘要

本次将原有 `mock_signature` 替换为实验级 ECDSA 签名：

```text
ECDSA 私钥 + Block.canonical_bytes()
        ↓
signature_bytes
        ↓
miner_pubkey + canonical_bytes + signature_bytes
        ↓
第 0 步签名校验
        ↓
结构 / 内核 / PoI / 解析 / 沙箱校验
```

`canonical_bytes()` 明确排除 `signature_bytes` 和 `block_hash`，因此签名不会自引用；区块哈希也基于同一份无签名规范化字节计算。

## 2. 新增与更新文件

| 文件 | 内容 |
|---|---|
| `crypto_key.py` | `generate_miner_keypair()`、`sign_block_payload()`、`verify_block_signature()` 和公钥导出辅助函数 |
| `block_model.py` | 移除 mock 签名字段，新增 `miner_pubkey: bytes`、`signature_bytes: bytes`、`canonical_bytes()` |
| `block_validator.py` | 新增第 0 步 ECDSA 签名校验；失败立即拒绝，不进入后续流水线 |
| `demo_ecdsa_sign.py` | 正常签名、篡改内容、错误私钥/公钥组合演示 |
| `tests/test_crypto_sign.py` | 正常签名、内容篡改、密钥不匹配、空/损坏签名测试 |
| `demo_block.py` | 迁移到真实 ECDSA 签名区块构造 |
| `demo_vote_conflict.py` | 迁移到真实 ECDSA 签名区块构造 |
| `tests/test_block_layer.py` | 迁移测试构造器并纳入签名阶段 |
| `tests/test_voting_pool.py` | 同一矿工复用同一 ECDSA 密钥，以正确计算历史权重 |

## 3. 签名与哈希规则

- `miner_pubkey` 保存为 ecdsa NIST256p 公钥原始字节；
- `signature_bytes` 保存为 ECDSA 签名字节；
- `Block.canonical_bytes()` 使用排序键、紧凑分隔符和 UTF-8 输出确定性 JSON；
- 公钥以 hex 形式进入 canonical payload，避免 bytes 无法 JSON 序列化；
- `signature_bytes` 不进入 canonical payload；
- `block_hash = SHA256(canonical_bytes())`；
- 签名校验在结构、高度、PoI 和沙箱检查之前执行。

## 4. 验收结果

已安装并使用：

```text
ecdsa 0.19.2
```

应运行：

```bash
python demo_ecdsa_sign.py
python -m unittest discover -s tests -v
python -m compileall -q *.py tests/*.py
```

ECDSA 测试覆盖：

- 正常签名与验证通过；
- 篡改 proposal 内容后签名校验失败；
- 使用 B 私钥签名但填 A 公钥失败；
- 空签名、随机损坏签名失败；
- 签名成功后完整区块进入后续合法性校验。

## 5. 原型暂未实现清单

本阶段仍不实现：

- P2P 网络、节点发现、广播和网络重传；
- 磁盘持久化、密钥库存储和密钥轮换；
- UTXO、账户、转账和可交易代币；
- 纪元、摘要压缩、摘要投票和引种提案；
- 真实 LLM 调用和真实 tokenizer；
- 网络投票窗口、分布式时钟和拜占庭共识；
- 生产级证书、身份注册、撤销列表和硬件密钥保护。

## 6. 已知安全限制

1. 本项目的 ECDSA 仅用于单机实验原型，不是生产级密码学系统。
2. 私钥目前由调用方以内存 bytes 持有，没有安全存储、轮换或撤销机制。
3. 使用 NIST256p 和 `ecdsa` 库能够验证签名，但不等于完成现实网络中的身份认证。
4. 区块仍然只在内存中存在，缺少持久化恢复和重放审计。
5. 沙箱仍是教学级纯计算隔离，不是生产安全容器。
6. 共识仍只适配小规模仿真网络；没有 P2P 投票窗口。
7. 未来 LLM 摘要仍会存在信息衰减与幻觉风险，摘要链仍可能线性低速增长。
8. 无金融激励可能导致参与者流失；ECDSA 签名不改变这一实验性风险。
