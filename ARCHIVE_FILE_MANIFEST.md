# StratumGenesis · 文件清单（v0.2 归档 + v0.3 追加登记）

> 起始归档版本：v0.2（2026-09-09）；本文档持续追加登记 v0.3 各阶段文件（阶段 A–E 与上线批次）。
> 本清单罗列全部源码、测试、演示与文档文件，每项附一句话用途说明。
> 目录结构以项目根目录 `E:\my-code\tokenmint` 为准。
> 当前测试总数：**298 项全部通过**（监督者独立复跑确认）。

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
| `persistence.py` | v0.3 新增：确定性 JSON 存档/加载/导出（format_version=chain-v2；v0.3 阶段 C 因区块新增 `activation` 字段、canonical 序列化变化而由 chain-v1 升级，旧档加载被拒），原子写入、哈希+签名校验、账本/纪元快照/语言注册表重放重建 |
| `epoch_summary.py` | v0.3 阶段 B 新增：mock 纪元摘要——确定性规则模板（keyword-top/contributor-distribution/first-last-narrative）+ 历史贡献加权投票 + 平票确定性回退 |
| `block_model.py` | 不可变区块数据模型：`Block`/`Proposal`/`PoiRecord`/`TestCase`，SHA256 区块哈希、`canonical_bytes()`、创世块构造 |
| `mock_tokenizer.py` | PoI mock 标准分词器：确定性词元计数（`mock-tokenizer-v1`），不调用外部模型 |
| `block_validator.py` | 9 检查阶段区块校验流水线（签名→结构→内核→PoI→解析→特性激活→沙箱→语言正负测试→UTXO，v0.3 阶段 C 起），返回 `ValidationResult` |
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
| `tests/test_persistence.py` | 11 | v0.3 新增：存档 roundtrip 等值、HTTP 一致性、损坏拒绝、--fresh、导出、旧存档 .bak 保留/不覆盖/拒绝加载不触碰原文件（收尾 E 追加 3 项） |
| `tests/test_epoch_summary.py` | 10 | v0.3 阶段 B：边界触发、确定性、历史权重、平票回退、finalized 不可变、休眠分支无摘要、chain-state 追加字段、save→load 摘要一致、篡改签名拒绝 |
| `tests/test_evolution.py` | 12 | v0.3 阶段 C：注册后可调用、未激活 NameError、激活名校验、重复激活拒绝、正负测试、历史块版本化重放、休眠分支隔离 |
| `tests/test_sandbox_limits.py` | 4 | v0.3 阶段 C 收尾：输出上限超限 ResourceLimitError / 恰好等于上限成功；长列表不泄露宿主递归 / 宿主递归稳定归类 |
| `tests/test_persistence_evolution.py` | 1 | v0.3 阶段 C 收尾 F：save→load+rebuild 后高度/哈希、逐高度语言快照、激活能力可用、未激活高度 NameError 全一致 |
| `tests/test_epoch_scope.py` | 10 | v0.3 阶段 D：跨纪元失忆、引种成功、同纪元重复拒绝、跨纪元再引种、重放一致性、分类正确、语义化报错、API 契约、边界 99/100/101、预沉积回归 |
| `tests/test_branch_promotion.py` | 18 | v0.3 阶段 E：纯接续/后缀替换/深·收缩·延伸重组、四类资格拒绝、UTXO 与语言失效拒绝、ever_active 收缩后重激活、跨纪元摘要冻结与 pending 重算、对合性、持久化 round-trip、原子性总检、API 契约超集 |
| `tests/test_builtin_pool_matrix.py` | 80 | 15 个可激活扩展原语的矩阵测试：正常/元数错误/类型错误/边界（除零、非 proper list、if 惰性）+ 未激活 NameError + 沙箱上限（只断言 `error_type`，不锁错误文案） |
| `tests/test_analyze_chain.py` | 58 | v0.3 上线批次：离线分析器 CLI/指标/`--by-model` 创造力指标/私钥零泄漏/哨兵值零泄漏/`epoch=height//100` 口径/**缺 ecdsa 的 skipUnless 降级与 GBK 控制台专项** |
| **合计** | **276** | 全部通过（监督者独立复跑确认） |

## 五、归档文档（本次新增，均为 Markdown）

| 文件 | 用途 |
|---|---|
| `ARCHIVE_v0_2_README.md` | 归档总说明与入口：简介、快速启动、架构图、完成/未完成清单、风险、路线 |
| `CHANGELOG_v0_2.md` | 版本变更日志：按开发阶段记录全部完成点与 Bug 修复 |
| `ARCHIVE_FILE_MANIFEST.md` | 本文件：完整文件清单 |
| `DEMO_SCRIPT_v0_2.md` | 人工演示操作脚本（给演示者照着执行） |
| `REFERENCE_DOCS_INDEX.md` | 全部历史设计文档索引 |
| `CHANGELOG_v0_3.md` | v0.3 版本变更日志（阶段 A：git 基线 + 磁盘持久化） |
| `PERSISTENCE_IMPLEMENTATION.md` | v0.3 持久化实现说明：格式、恢复策略、私钥安全边界、已知限制 |
| `EPOCH_SUMMARY_IMPLEMENTATION.md` | v0.3 阶段 B：mock 纪元摘要实现说明（模板/投票/确定性重放/未来 LLM 替换点/风险提示） |

### 1.4 v0.3 阶段 C 语言演化追加登记

| 文件 | 用途 |
|---|---|
| `novscript/registry.py` | 特性注册表：`PrimitiveSpec`/`FeatureRegistry`/`BUILTIN_POOL`（15 预置原语）/`KERNEL_PRIMITIVES` 内核守卫 |
| `novscript/language.py` | 语言快照：`LanguageSnapshot` + `from_registry`/`build_registry` 版本化重建 |
| `demo_evolution.py` | 语言演化端到端演示：激活 `-`/`list`、历史块版本化重放、重复激活拒绝 |
| `tests/test_evolution.py` | 12 项语言演化回归（见四节） |
| `tests/test_sandbox_limits.py` | 4 项输出上限与递归归类回归（见四节） |
| `tests/test_persistence_evolution.py` | 1 项持久化×语言演化耦合回归（见四节） |
| `EVOLUTION_IMPLEMENTATION.md` | 阶段 C 实现说明：设计图、9 检查阶段表、正负测试原理、变更清单 |

### 1.5 v0.3 阶段 D 引种机制追加登记

| 文件 | 用途 |
|---|---|
| `tests/test_epoch_scope.py` | 10 项纪元作用域/引种回归（见四节） |
| `INTRODUCTION_IMPLEMENTATION.md` | 阶段 D 实现说明：两层注册表、作用域校验、错误码表、API 契约变更、已知限制 |

### 1.6 v0.3 阶段 E 分叉兑现追加登记

| 文件 | 用途 |
|---|---|
| `chain_store.py`（修改） | 新增 `PromotionResult`/`PromotionError`、`_walk_branch`、`inspect_promotion`、`branch_head_candidates`、`promote_branch`（scratch 重放 + S4 单临界区原子换入） |
| `block_validator.py`（修改） | 新增纯函数 `check_promotion_eligibility`（资格判定 E1–E6，只读）；E7 复用既有 9 检查流水线 |
| `server.py`（修改） | 新增 `GET /branches`、`POST /promote-branch`、变更类入口状态锁；既有 API 只追加字段 |
| `tests/test_branch_promotion.py` | 18 项重组回归（见四节） |
| `BRANCH_PROMOTION_DESIGN.md` | 阶段 E 设计说明：资格判定式、重组算法与回滚点、12 条不变量、测试计划、开放问题取舍 |
| `BRANCH_PROMOTION_IMPLEMENTATION.md` | 阶段 E 实现说明：实现映射、原子性、语言/纪元一致性、API 契约、已知限制 |

### 1.7 v0.3 上线批次追加登记（许可 / 门面 / 部署 / 静态展馆 / 分析器）

| 文件 | 用途 |
|---|---|
| `LICENSE` | **PolyForm Noncommercial 1.0.0**（禁止商业使用）；版权所有人：鹿拾（Yuanhao Lu，https://github.com/lyh9712） |
| `LICENSE-SCOPE.md` | 中文许可边界：允许项/禁止项/部署者义务/商业授权联络（GitHub 主页）/免责重申 |
| `NOTICE` | 署名与性质声明：依赖仅 `ecdsa`(MIT)、非加密货币、无代币、无金融价值 |
| `README.md` | 仓库门面：一句话定位、30 秒原理、三种上手路径、「它不是什么」、测试命令、许可声明 |
| `requirements.txt` | 运行时依赖清单：`ecdsa>=0.19`（项目唯一第三方依赖） |
| `start.bat` | Windows 一键启动（纯 ASCII + CRLF；解释器探测；缺依赖提示；自动开页面） |
| `.gitignore` | 忽略 `__pycache__/`、`*.pyc`、`server.log`、`data/`、`*.tmp`、`.codebuddy/`、`.workbuddy/`、`*.bak-*` |
| `export_public.py` | 导出可公开的只读展馆数据（**写盘前断言无 `private_key`**，否则拒绝写出并非零退出） |
| `chain_state.json` | 只读展馆静态链快照（已剥离私钥；发布前用最新代码刷新） |
| `Dockerfile` | 容器镜像：`python:3.12-slim` + `requirements.txt` + 暴露 28417 + 容器内 HEALTHCHECK |
| `DEPLOY.md` | 部署指南（Render/Fly 逐步）+「部署者须知」（持私钥可冒充、垃圾提案防护、冷启动、合规义务、Actions 归档） |
| `render.yaml` | Render 一键部署蓝图（含 127.0.0.1 绑定的转发方案与风险标注） |
| `analyze_chain.py` | 离线链分析器：指标报告 + `--verify` 签名重验（走 `crypto_key`）+ `--by-model` 跨 AI 创造力指标 |
| `EXPERIMENT_METRICS.md` | 实验指标口径文档（含跨 AI 创造力指标定义、数据来源纪律、样本量警示、未验证项） |
| `tests/test_analyze_chain.py` | 58 项分析器回归（见四节） |
| `tests/test_builtin_pool_matrix.py` | 80 项扩展原语矩阵回归（见四节） |
| `SURVIVAL_AND_DEPLOYMENT.md` | 存活与部署策略：零服务器路线、Pyodide 可玩路径、多 hub 机制、许可取舍、诚实提醒 |

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
- 依赖：运行时仅需 `ecdsa`（详见 `requirements.txt`，MIT 许可，纯 Python）。缺该依赖时签名/验签相关功能
  与离线分析器的验签路径会明确跳过并提示（不得伪造结果）。
- **状态存储**：内存仿真 + 实验级 JSON 存档（如 `data/chain_v2.json`）。⚠️ 存档**含明文矿工私钥**，
  公开分发或部署前必须剥离（参见 `export_public.py` 的私钥剥离断言）。
- 仍不提供：P2P 网络、公网鉴权、数据库、HTTPS、密钥托管；**无任何可交易代币或现实金融价值**。
- `data/` 目录整体被 `.gitignore` 忽略；`data/chain_v1.json` 为 chain-v1 旧格式样本，仅用于验证
  「旧版本存档被拒」行为，**不得删除或改写**。
