# StratumGenesis · v0.2 参考文档索引

> 归档版本：v0.2　归档日期：2026-09-09
> 本文档索引全部历史设计文档与模块实现说明，供回溯设计与实现依据时快速定位。
> 文档按「设计规范 → 模块实现说明 → 接口与使用 → 归档」分层组织。

---

## 一、设计规范类（定义「应该是什么」）

| 文档 | 作用 |
|---|---|
| `TokenMint 设计白皮书 v0.1（完整14章）.md` | **项目总纲（v0.1 前身）**：完整世界观（地质隐喻）、PoI 机制、区块结构、纪元分代、分叉宇宙、角色与激励、UI 叙事、已知风险、路线图。设计讨论时的最高级参考 |
| `StratumGenesis_白皮书_第X章_共识机制与区块生命周期.md` | **共识规格补充**：区块合法性全部检查项、候选集合规则、历史贡献加权投票、失败场景表、开放工程问题清单。区块/投票/失败处理实现的对齐依据 |
| `StratumGenesis_最小原型工程规范_NovScript沙箱解释器.md` | **沙箱工程规范**：NovScript 词法、BNF 语法、AST 数据类、thunk 惰性求值语义、SandboxLimits/EvalResult 接口、S-01~S-12 与 F-01~F-18 测试清单、安全约束。实现与测试的对齐基准 |

> 对齐优先级约定（来自历史任务）：当文档冲突时，工程规范优先于白皮书草案；行为以实际代码与测试为准。

## 二、模块实现说明类（记录「实际做了什么」）

| 文档 | 对应阶段 | 作用 |
|---|---|---|
| `NOVSCRIPT_PROTOTYPE_IMPLEMENTATION.md` | 阶段 1 | NovScript 沙箱原型实现说明：分层文件职责、固定歧义、运行结果、暂未实现清单 |
| `BLOCK_LAYER_PROTOTYPE_IMPLEMENTATION.md` | 阶段 2 | 区块层实现说明：数据模型、mock tokenizer、校验流水线、内存链与休眠分支 |
| `VOTING_POOL_IMPLEMENTATION.md` | 阶段 3 | 候选池/权重/投票实现说明：分组规则、仅主链计权、平票处理、已知限制 |
| `CRYPTO_SIGN_IMPLEMENTATION.md` | 阶段 4 | ECDSA 签名实现说明：canonical_bytes、签名前置校验、实验级密码学边界 |
| `UTXO_IMPLEMENTATION.md` | 阶段 5 | UTXO 账本实现说明：奖励、转账、双花、余额与投票权重隔离、休眠分支隔离 |
| `EPOCH_BASE_IMPLEMENTATION.md` | 阶段 6 | 纪元基础实现说明：自动编号、边界事件、快照归档标记、暂未实现（摘要/引种/大断层） |
| `PERSISTENCE_IMPLEMENTATION.md` | v0.3 阶段 A | 磁盘持久化实现说明：存档格式、保存/恢复策略、为何账本与快照重建而非序列化、私钥安全边界 |
| `EPOCH_SUMMARY_IMPLEMENTATION.md` | v0.3 阶段 B | mock 纪元摘要实现说明：规则模板、加权投票、确定性重放、未来 LLM 替换点、风险提示 |

## 三、接口与使用类（告诉「怎么用」）

| 文档 | 作用 |
|---|---|
| `API_SPEC.md` | HTTP API 接口规范：`GET /chain-state`、`POST /propose`、`POST /eval-novscript` 的请求/响应结构、提案文本→代码映射、测试方式；全部示例地址使用端口 28417 |
| `使用说明.md` | 前后端打通版使用说明：启动服务、交互点表格、提案映射说明、测试命令、已知限制（端口 28417） |
| `mock数据说明.md` | ⚠️ 历史文档：说明静态 mock 版前端的链数据与演示解释器；已被「前后端打通版」取代，保留仅作阶段记录 |

## 四、归档类（本次新增）

| 文档 | 作用 |
|---|---|
| `ARCHIVE_v0_2_README.md` | **归档入口**：项目简介、快速启动、架构总览、已完成/未完成清单、风险重申、路线建议 |
| `CHANGELOG_v0_2.md` | 版本变更日志：按开发阶段记录全部完成点与 Bug 修复 |
| `ARCHIVE_FILE_MANIFEST.md` | 完整文件清单（源码/测试/演示/文档） |
| `DEMO_SCRIPT_v0_2.md` | 人工演示操作脚本 |
| `CHANGELOG_v0_3.md` | v0.3 版本变更日志（阶段 A + 阶段 B） |
| `PERSISTENCE_IMPLEMENTATION.md` | v0.3 持久化实现说明（存档/恢复/导出/验签） |
| `EPOCH_SUMMARY_IMPLEMENTATION.md` | v0.3 阶段 B：mock 纪元摘要实现说明（模板/投票/重放/LLM 替换点） |

## 五、文档与实现的对应关系速查

| 想了解什么 | 先看哪个文档 |
|---|---|
| 项目整体是什么 | `ARCHIVE_v0_2_README.md` → `TokenMint 设计白皮书 v0.1` |
| 共识与区块怎么设计 | `StratumGenesis_白皮书_第X章_共识机制与区块生命周期.md` |
| 沙箱怎么实现/测试 | `StratumGenesis_最小原型工程规范_NovScript沙箱解释器.md` + `NOVSCRIPT_PROTOTYPE_IMPLEMENTATION.md` |
| 区块/投票/签名/账本/纪元各模块 | 对应模块实现说明（见第二节） |
| 前后端怎么对接 | `API_SPEC.md` + `使用说明.md` |
| 怎么演示给别人看 | `DEMO_SCRIPT_v0_2.md` |
| 有哪些文件 | `ARCHIVE_FILE_MANIFEST.md` |

## 六、提醒

所有文档描述的均为**单机仿真实验原型**：无磁盘持久化、无 P2P、无真实 LLM、无任何可交易资产；沙箱为教学级纯计算隔离；未来 LLM 摘要存在信息衰减与幻觉风险，共识仅适配小规模仿真网络。任何阅读者不应据此认为 StratumGenesis 是可投产的生产系统。
