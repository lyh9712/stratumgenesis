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
| `EVOLUTION_IMPLEMENTATION.md` | v0.3 阶段 C | **语言真实演化**实现说明：特性注册表、求值器派发、语言快照版本化重放、8 步流水线与正负测试原理（阶段 D 修订：作用域改为纪元内） |
| `INTRODUCTION_IMPLEMENTATION.md` | v0.3 阶段 D | **引种提案**实现说明：两层注册表（历史层/纪元层）、作用域校验、UNIMPORTED_FEATURE 错误码、API 契约变更、已知限制 |
| `BRANCH_PROMOTION_IMPLEMENTATION.md` | v0.3 阶段 E | **分叉兑现**实现说明：资格判定 E1–E7、scratch 重放 + 原子换入、失败回滚点、不变量与用例、reorg API |
| `EXPERIMENT_METRICS.md` | v0.3 上线批次 | **实验指标口径**：语言演化/链与共识/账本/PoI 指标定义、**跨 AI 创造力指标**（接受率、引种留存率、半衰期、原语偏好、组合新颖度）、数据来源纪律与样本量警示 |

## 三、接口与使用类（告诉「怎么用」）

| 文档 | 作用 |
|---|---|
| `API_SPEC.md` | HTTP API 接口规范：`GET /chain-state`、`POST /propose`、`POST /eval-novscript` 的请求/响应结构、提案文本→代码映射、测试方式；全部示例地址使用端口 28417 |
| `使用说明.md` | 前后端打通版使用说明：启动服务、交互点表格、提案映射说明、测试命令、已知限制（端口 28417） |
| `mock数据说明.md` | ⚠️ 历史文档：说明静态 mock 版前端的链数据与演示解释器；已被「前后端打通版」取代，保留仅作阶段记录 |

## 四、归档类

| 文档 | 作用 |
|---|---|
| `ARCHIVE_v0_2_README.md` | **归档入口**：项目简介、快速启动、架构总览、已完成/未完成清单、风险重申、路线建议 |
| `CHANGELOG_v0_2.md` | v0.2 版本变更日志（阶段 0–9） |
| `ARCHIVE_FILE_MANIFEST.md` | 完整文件清单（源码/测试/演示/文档，含 v0.3 阶段 A–E 与上线批次登记） |
| `DEMO_SCRIPT_v0_2.md` | 人工演示操作脚本 |
| `CHANGELOG_v0_3.md` | v0.3 版本变更日志（阶段 A 持久化 → B 纪元摘要 → C 语言演化 → D 引种 → E 分叉兑现 → 上线批次） |
| `PERSISTENCE_IMPLEMENTATION.md` | v0.3 阶段 A：持久化实现说明（存档/恢复/导出/验签/`.bak` 非破坏策略） |
| `EPOCH_SUMMARY_IMPLEMENTATION.md` | v0.3 阶段 B：mock 纪元摘要实现说明（模板/投票/重放/LLM 替换点） |
| `EVOLUTION_IMPLEMENTATION.md` | v0.3 阶段 C：语言真实演化实现说明（注册表/快照重放/正负测试；阶段 D 修订作用域、阶段 E 修订 ever_active 措辞） |
| `INTRODUCTION_IMPLEMENTATION.md` | v0.3 阶段 D：引种提案实现说明（两层注册表/作用域校验/错误码/契约变更） |
| `BRANCH_PROMOTION_DESIGN.md` | v0.3 阶段 E：分叉兑现**设计说明**（资格判定式 E1–E7、重组算法 S0–S6、12 条不变量、测试计划、X.9-9 取舍） |
| `BRANCH_PROMOTION_IMPLEMENTATION.md` | v0.3 阶段 E：分叉兑现**实现说明**（实现映射、原子性、语言/纪元一致性、API、限制） |
| `EXPERIMENT_METRICS.md` | v0.3：实验指标口径（语言演化/链与共识/账本/PoI + 跨 AI 创造力指标、数据纪律、样本量警示） |
| `SURVIVAL_AND_DEPLOYMENT.md` | v0.3：存活与部署策略（零服务器路线、多 hub、许可取舍、部署者须知、免责） |

## 五、上线与合规类

| 文档 | 作用 |
|---|---|
| `README.md` | 仓库门面与第一入口：定位句、原理、三种上手路径、「它不是什么」、测试与依赖、许可摘要 |
| `LICENSE` | **PolyForm Noncommercial 1.0.0**（禁止商业使用）；版权所有人：鹿拾（Yuanhao Lu）；仓库 https://github.com/luyuanhao/stratumgenesis |
| `LICENSE-SCOPE.md` | 中文许可边界（允许/禁止/部署者义务/商业授权联络：GitHub 主页） |
| `NOTICE` | 署名与性质声明（依赖仅 `ecdsa` MIT；非加密货币、无代币、无金融价值） |
| `DEPLOY.md` | 部署指南与部署者须知（Render/Fly/Docker；持私钥可冒充；合规义务；冷启动） |
| `requirements.txt` | 运行时依赖（`ecdsa>=0.19`） |

## 六、文档与实现的对应关系速查

| 想了解什么 | 先看哪个文档 |
|---|---|
| 项目整体是什么 | `README.md` → `ARCHIVE_v0_2_README.md` → `TokenMint 设计白皮书 v0.1` |
| 共识与区块怎么设计 | `StratumGenesis_白皮书_第X章_共识机制与区块生命周期.md` |
| 沙箱怎么实现/测试 | `StratumGenesis_最小原型工程规范_NovScript沙箱解释器.md` + `NOVSCRIPT_PROTOTYPE_IMPLEMENTATION.md` |
| 区块/投票/签名/账本/纪元各模块 | 对应模块实现说明（见第二节） |
| 语言怎么演化（新原语如何上链） | `EVOLUTION_IMPLEMENTATION.md` + `demo_evolution.py` |
| 失忆与引种（纪元作用域语言） | `INTRODUCTION_IMPLEMENTATION.md` + 白皮书 §7.6.1 |
| **分叉怎么翻身（休眠分支升级 / reorg）** | `BRANCH_PROMOTION_DESIGN.md` → `BRANCH_PROMOTION_IMPLEMENTATION.md` |
| **怎么衡量不同 AI 的创造力** | `EXPERIMENT_METRICS.md`（接受率 / 引种留存率 / 半衰期 / 原语偏好 / 组合新颖度） |
| 怎么测量与复现实验数据 | `analyze_chain.py` + `EXPERIMENT_METRICS.md` |
| **怎么上线、怎么让别人接手部署** | `DEPLOY.md` + `SURVIVAL_AND_DEPLOYMENT.md` |
| 能不能商用 / 怎么授权 | `LICENSE` + `LICENSE-SCOPE.md` + `NOTICE` |
| 前后端怎么对接 | `API_SPEC.md` + `使用说明.md` |
| 怎么演示给别人看 | `DEMO_SCRIPT_v0_2.md` |
| 有哪些文件 | `ARCHIVE_FILE_MANIFEST.md` |

## 七、提醒

所有文档描述的均为**单机仿真实验原型**：状态保存在内存与实验级 JSON 存档中（`data/chain_v2.json` 这类存档
**含明文私钥**，公开分发前必须剥离）；无 P2P、无真实 LLM（PoI 为 mock）；**无任何可交易代币或现实金融价值**；
沙箱为教学级纯计算隔离（非安全容器）；未来 LLM 摘要存在信息衰减与幻觉风险；共识仅适配小规模仿真网络。
**任何阅读者不应据此认为 StratumGenesis 是可投产的生产系统。**
