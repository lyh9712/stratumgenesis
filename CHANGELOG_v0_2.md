# StratumGenesis · v0.2 版本变更日志

> 归档版本：v0.2（前后端打通 · 单机仿真归档版）
> 归档日期：2026-09-09
> 记录范围：从最初 NovScript 沙箱到前后端打通、再到归档文档包的**全部开发阶段完成点**。

---

## 阶段 0 · 设计基础（v0.1 前身 TokenMint）

- 完成《TokenMint 设计白皮书 v0.1（完整 14 章）》，确立核心世界观：地质地层隐喻、每 100 区块 = 1 纪元、PoI 推理工作量证明、分叉即语言分化、非金融激励。
- 完成《StratumGenesis 白皮书第 X 章：共识机制与区块完整生命周期》，补充共识机制详细规格、区块合法性全部检查项、失败场景与开放工程问题清单。
- 完成《StratumGenesis 最小原型工程规范：NovScript 沙箱解释器》，冻结词法、BNF、AST、惰性求值语义、SandboxLimits/EvalResult 接口与 S/F 测试用例。

## 阶段 1 · NovScript 沙箱解释器原型

- 实现独立 `lexer → parser → AST → evaluator → sandbox` 完整链路，未使用 `eval`/`exec`。
- 实现惰性求值 + thunk 记忆化；循环 thunk 检测（`(bind x x) x` 稳定返回错误而非挂死）。
- 实现 8 类结构化错误与 `run_sandbox`、`validate_on_nodes` 对外接口。
- 全部测试通过：S-01~S-12 成功用例 + F-01~F-18 失败/边界用例（30 项）。
- 交付 `NOVSCRIPT_PROTOTYPE_IMPLEMENTATION.md` 与演示脚本 `demo.py`。

## 阶段 2 · 最小区块层原型

- 新增 `block_model.py`（不可变 Block dataclass、SHA256 区块哈希）、`chain_store.py`（内存主链 + 休眠分支）、`block_validator.py`（5 阶段校验：结构 → 创世内核兼容 → mock PoI → 解析 → 沙箱）、`mock_tokenizer.py`（确定性 mock 词元计数）。
- 新增 13 项区块层测试：合法上链、高度错误、父区块不存在、内核冲突、PoI 不足/计数不符、demo/test 语法错误、沙箱预期不匹配、休眠分支存储等。
- 交付 `BLOCK_LAYER_PROTOTYPE_IMPLEMENTATION.md` 与 `demo_block.py`。

## 阶段 3 · 候选区块池 + 历史贡献权重 + 冲突加权投票

- 新增 `candidate_pool.py`（按 (parent_block_hash, target_height) 分组）、`weight_calculator.py`（**仅主链**累计 `standard_total_tokens` 作为投票权重）、`conflict_voter.py`（单候选直通 / 加权投票 / 平票全部进休眠分支）、`miner_identity.py`（早期 mock 身份层）。
- 更新 `chain_store.py`：`apply_vote_result()` 对接投票结果（胜者入主链、落选者入休眠分支）。
- 新增 5 项投票池测试：单候选无冲突、加权投票、平票、休眠分支不计权重、分组正确。
- 交付 `VOTING_POOL_IMPLEMENTATION.md` 与 `demo_vote_conflict.py`。

## 阶段 4 · ECDSA 区块签名（替换 mock 签名）

- 新增 `crypto_key.py`：`generate_miner_keypair()`、`sign_block_payload()`、`verify_block_signature()`（NIST256p，依赖 ecdsa 库）。
- 更新 `block_model.py`：移除 `mock_signature`，新增 `signature_bytes: bytes` 与 `canonical_bytes()`；`miner_pubkey` 改为可验证公钥字节；区块哈希与签名均排除 signature 字段。
- 更新 `block_validator.py`：签名校验成为流水线**第 0 步**前置检查。
- 迁移既有演示/测试到「构造无签名区块 → 对 canonical_bytes 签名 → 生成最终区块」流程。
- 新增 4 项签名测试：正常签名、篡改内容、公私钥不匹配、空/损坏签名。
- 交付 `CRYPTO_SIGN_IMPLEMENTATION.md` 与 `demo_ecdsa_sign.py`。
- `miner_identity.py` 自此不再被任何模块引用，保留为历史遗留参考。

## 阶段 5 · UTXO 账本模块

- 新增 `utxo_model.py`（UTXO / Transaction 数据模型、交易 canonical bytes、交易哈希、`make_signed_transaction()`）与 `utxo_ledger.py`（内存账本：挖矿奖励、转账、双花检测、金额约束、交易签名校验、余额查询）。
- 更新 `block_model.py`：Block 新增 `transactions` 字段并纳入 canonical bytes 与区块哈希。
- 更新 `block_validator.py`：新增第 6 步 UTXO 交易校验。
- 更新 `chain_store.py`：**只有主链成功追加才**发放奖励并应用交易；休眠分支不触碰账本。
- 新增 6 项 UTXO 测试：奖励生成、正常转账余额、双花拒绝、错误交易签名、超额输出、休眠分支隔离。
- 交付 `UTXO_IMPLEMENTATION.md` 与 `demo_utxo.py`。

## 阶段 6 · 纪元基础框架

- 更新 `block_model.py`：Block 新增 `epoch` 字段，构造时按 `height // 100` 自动计算；显式不一致立即报错；epoch 纳入哈希与签名内容。
- 新增 `epoch_manager.py`：`EpochSnapshot`、`get_epoch_of_block()`、`scan_chain()`、`get_epoch_snapshot()`；边界（height % 100 == 0）触发归档标记；休眠分支不生成快照。
- 更新 `chain_store.py`：主链追加后自动扫描纪元快照。
- 更新 `block_validator.py`：结构阶段增加 epoch 一致性校验（`EPOCH_MISMATCH`）。
- 新增 6 项纪元测试：自动编号、构造期校验、篡改拒绝、99/100 边界、归档快照、休眠分支隔离。
- 交付 `EPOCH_BASE_IMPLEMENTATION.md` 与 `demo_epoch.py`。

## 阶段 7 · 静态 UI 原型（单文件 mock 版）

- 交付单文件 `index.html`（全部 CSS/JS/数据内嵌）：地层剖面、创世内核花岗岩层、推演粒子动画、岩层凝聚/碎裂、纪元抬升、钻探考古手电筒、详情面板、程序画廊、内置简化 NovScript 演示解释器。
- 配套《使用说明》与《mock 数据说明》，明确纯静态、不连接后端。

## 阶段 8 · 前后端打通（v0.2 核心）

- 新增 `server.py`：标准库 `http.server`，监听 `127.0.0.1:28417`（仅 localhost）；启动初始化创世链并预沉积 102 个经真实校验的演示区块。
- 实现 3 个 JSON API：`GET /chain-state`、`POST /propose`（解析文本 → 生成代码/测试 → ECDSA 签名 → 候选池 → 6 阶段校验 → 冲突加权投票 → 上链或休眠分支）、`POST /eval-novscript`（真实沙箱执行，返回中文错误类型）。
- 重写 `index.html`：删除全部硬编码链数据与前端 mock 解释器，改为调用真实后端；保留全部地层交互与动画。
- 新增 8 项 HTTP API 端到端测试；全套测试累计 **72 项全部通过**。
- 交付 `API_SPEC.md` 与更新版《使用说明》（端口 28417）。

## 阶段 8.1 · Bug 修复（index.html 404）

- **问题**：从非项目目录启动服务时，`open("index.html")` 相对路径失效，返回 404。
- **修复**：`server.py` 改为基于 `__file__` 定位 `INDEX_PATH`，不再依赖启动时的工作目录。
- **附带处理**：清理了端口 28417 上残留的两个旧服务进程（Windows 下 SO_REUSEADDR 允许重复绑定导致旧实例继续返回 404）。
- **验证**：从 `/tmp`（非项目目录）启动后 `/index.html` 返回 200；72 项测试复跑通过。

## 阶段 9 · v0.2 归档文档包

- 生成 5 份归档文档（本次归档）：
  - `ARCHIVE_v0_2_README.md`（归档总说明与入口）
  - `CHANGELOG_v0_2.md`（本文件）
  - `ARCHIVE_FILE_MANIFEST.md`（文件清单）
  - `DEMO_SCRIPT_v0_2.md`（演示操作脚本）
  - `REFERENCE_DOCS_INDEX.md`（参考文档索引）
- 归档原则：**不修改任何源码、不新增功能**，仅产出文档；反复强调本版本为单机仿真原型，非生产系统。
