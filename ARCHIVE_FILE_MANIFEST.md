# StratumGenesis · v0.2 归档文件清单

> 归档版本：v0.2　归档日期：2026-09-09
> 本清单完整罗列归档包内全部源码、测试、演示与文档文件，每项附一句话用途说明。
> 目录结构以归档时的项目根目录 `E:\my-code\tokenmint` 为准。

---

## 一、后端源码（Python）

### 1.1 NovScript 沙箱解释器包 `novscript/`

| 文件 | 用途 |
|---|---|
| `novscript/__init__.py` | 包公共入口，导出 `run_sandbox`、`evaluate`、`parse`、`SandboxLimits`、`EvalResult`、`ValidationReport` 等 |
| `novscript/errors.py` | 8 类结构化错误定义（LexError/ParseError/NameError/TypeError/ArityError/RecursionError/ResourceLimitError/SandboxError） |
| `novscript/ast.py` | 不可变 AST 数据类（IntLiteral/Symbol/Lambda/Bind/Call/Program） |
| `novscript/lexer.py` | 字符级词法分析器（整数、标识符、括号、`+` 原语、`;;` 注释） |
| `novscript/parser.py` | 递归下降解析器，按最小 BNF 构建 Program AST |
| `novscript/evaluator.py` | 惰性求值器：环境、闭包、thunk 记忆化、循环 thunk 检测、资源计数 |
| `novscript/sandbox.py` | 对外沙箱入口：`run_sandbox`、`evaluate`、`validate_on_nodes`、`SandboxLimits`/`EvalResult`/`ValidationReport` |

### 1.2 区块与共识层（项目根目录）

| 文件 | 用途 |
|---|---|
| `block_model.py` | 不可变区块数据模型：`Block`/`Proposal`/`PoiRecord`/`TestCase`，SHA256 区块哈希、`canonical_bytes()`、创世块构造 |
| `mock_tokenizer.py` | PoI mock 标准分词器：确定性词元计数（`mock-tokenizer-v1`），不调用外部模型 |
| `block_validator.py` | 6 阶段区块合法性校验流水线（签名→结构→内核→PoI→解析→沙箱→UTXO），返回 `ValidationResult` |
| `candidate_pool.py` | 候选区块池：按（父区块哈希，目标高度）分组，只接收已通过校验的候选 |
| `weight_calculator.py` | 历史贡献权重计算：仅遍历主链，按 miner_pubkey 累加 `standard_total_tokens` |
| `conflict_voter.py` | 冲突加权投票：单候选直通、多候选按权重计票、平票标记（winner=None） |
| `chain_store.py` | 内存链存储：主链 + 休眠分支集合；聚合 UTXO 账本与纪元管理器；`apply_vote_result()` |
| `crypto_key.py` | ECDSA（NIST256p）密钥生成、区块/交易签名与验签 |
| `miner_identity.py` | ⚠️ 历史遗留：早期 mock 矿工身份/签名层，ECDSA 阶段后已无引用，保留仅作参考 |
| `utxo_model.py` | UTXO / Transaction 数据模型、交易 canonical bytes、交易哈希、`make_signed_transaction()` |
| `utxo_ledger.py` | UTXO 内存账本：挖矿奖励、交易验证/应用、双花检测、输入输出金额约束、余额查询 |
| `epoch_manager.py` | 纪元基础框架：`EpochSnapshot`、`height//100` 编号、主链扫描、归档只读标记 |

### 1.3 HTTP 服务

| 文件 | 用途 |
|---|---|
| `server.py` | 本地 HTTP 服务（标准库 http.server，127.0.0.1:28417）：静态 index.html + 3 个 JSON API；启动初始化创世链并预沉积 102 个演示区块 |

## 二、前端

| 文件 | 用途 |
|---|---|
| `index.html` | 单文件前端页面（CSS/JS 内嵌）：地层剖面、推演动画、岩层详情、钻探考古、程序画廊、沙箱弹窗；数据全部来自真实后端 API |

## 三、演示脚本（Python）

| 文件 | 用途 |
|---|---|
| `demo.py` | NovScript 沙箱演示：单次运行 + 单机三节点模拟验证 |
| `demo_block.py` | 区块层演示：合法/非法候选校验、主链追加、休眠分支 |
| `demo_vote_conflict.py` | 候选池与历史贡献加权投票演示（ECDSA 版） |
| `demo_ecdsa_sign.py` | ECDSA 签名流程演示：正常签名、篡改、公私钥不匹配 |
| `demo_utxo.py` | UTXO 账本端到端演示：奖励、转账、余额、双花拒绝 |
| `demo_epoch.py` | 纪元基础框架演示：102 区块、纪元边界、归档快照、休眠分支 epoch |

## 四、单元测试 `tests/`

| 文件 | 用例数 | 用途 |
|---|---|---|
| `tests/test_novscript.py` | 30 | NovScript 沙箱 S-01~S-12 / F-01~F-18 全套回归 |
| `tests/test_block_layer.py` | 13 | 区块结构、父区块、内核冲突、PoI、解析、沙箱、休眠分支 |
| `tests/test_voting_pool.py` | 5 | 候选池分组、加权投票、平票、休眠分支不计权重 |
| `tests/test_crypto_sign.py` | 4 | ECDSA 正常/篡改/公私钥不匹配/空损坏签名 |
| `tests/test_utxo.py` | 6 | 奖励、转账、双花、错误签名、超额输出、休眠分支隔离 |
| `tests/test_epoch.py` | 6 | 纪元编号、构造校验、99/100 边界、归档快照、休眠分支 |
| `tests/test_http_api.py` | 8 | HTTP API 端到端：chain-state/propose/eval/index.html |
| **合计** | **72** | 全部通过 |

## 五、归档文档（本次新增，均为 Markdown）

| 文件 | 用途 |
|---|---|
| `ARCHIVE_v0_2_README.md` | 归档总说明与入口：简介、快速启动、架构图、完成/未完成清单、风险、路线 |
| `CHANGELOG_v0_2.md` | 版本变更日志：按开发阶段记录全部完成点与 Bug 修复 |
| `ARCHIVE_FILE_MANIFEST.md` | 本文件：完整文件清单 |
| `DEMO_SCRIPT_v0_2.md` | 人工演示操作脚本（给演示者照着执行） |
| `REFERENCE_DOCS_INDEX.md` | 全部历史设计文档索引 |

## 六、历史设计文档（保留供参考）

| 文件 | 用途 |
|---|---|
| `TokenMint 设计白皮书 v0.1（完整14章）.md` | 原始世界观与全量设计草案（v0.1） |
| `StratumGenesis_白皮书_第X章_共识机制与区块生命周期.md` | 共识机制详细规格、区块生命周期、失败场景、开放问题 |
| `StratumGenesis_最小原型工程规范_NovScript沙箱解释器.md` | NovScript 沙箱的工程规范：接口、BNF、语义、测试清单 |
| `NOVSCRIPT_PROTOTYPE_IMPLEMENTATION.md` | 沙箱原型实现说明（阶段 1） |
| `BLOCK_LAYER_PROTOTYPE_IMPLEMENTATION.md` | 区块层原型实现说明（阶段 2） |
| `VOTING_POOL_IMPLEMENTATION.md` | 候选池/权重/投票实现说明（阶段 3） |
| `CRYPTO_SIGN_IMPLEMENTATION.md` | ECDSA 签名实现说明（阶段 4） |
| `UTXO_IMPLEMENTATION.md` | UTXO 账本实现说明（阶段 5） |
| `EPOCH_BASE_IMPLEMENTATION.md` | 纪元基础框架实现说明（阶段 6） |
| `API_SPEC.md` | HTTP API 接口规范（阶段 8，端口 28417） |
| `使用说明.md` | 前后端打通版使用说明（阶段 8 更新） |
| `mock数据说明.md` | 历史文档：说明静态 mock 版前端数据；已被前后端打通版本取代，保留作阶段记录 |

## 七、说明

- 目录下 `__pycache__/` 为 Python 运行时缓存，不属于归档内容。
- 本归档不包含任何外部依赖清单之外的第三方库：运行时仅需 `ecdsa`（项目既有依赖）。
- 全部状态为内存仿真：无磁盘持久化、无 P2P、无公网访问、无鉴权、无任何可交易资产。
