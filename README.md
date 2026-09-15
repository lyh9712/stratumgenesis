# StratumGenesis · 地层创世实验

![状态](https://img.shields.io/badge/status-单机实验原型-2b6cb0)
![许可](https://img.shields.io/badge/license-PolyForm%20Noncommercial-4183c4)
![Python](https://img.shields.io/badge/python-3.13-3776ab)
![测试](https://img.shields.io/badge/tests-276%20passed-2ea043)
![依赖](https://img.shields.io/badge/deps-ecdsa%20only-8b949e)
![平台](https://img.shields.io/badge/platform-Windows%20%7C%20POSIX-555)

> **一句话定位**：StratumGenesis 是一条把"自然语言演化"当成地层来挖掘的实验链——
> 你提交一句自然语言，它在链上被解析、被验证、被投票、被签名，然后沉降成一块不可抵赖的地层。
>
> **性质**：单机仿真实验原型，无 P2P、无公网部署、无身份鉴权、**无可交易代币**；
> 摘要链为 `mock-rule-v1` 规则模板（非真实 LLM）。

---

## 1. 项目定位

StratumGenesis 想回答一个偏门但有趣的问题：**语言规则的演化，能不能被做成一条可审计的链？**

它不是又一个区块链应用，也不是一个语言学习工具。它把「语言如何被一群人一点一点扩展、
并且每次扩展都留下可验证痕迹」这件事，压缩进一个**单机就能跑完的仿真实验**里：
每个区块都是一次语言变更提案，每个纪元都是一段演化阶段，每次变更都有签名、有投票、有休眠分支。

因此本项目**同时是三种东西**：

- **一份可运行的工程**：33 个 Python 运行时模块（顶层 24 + `novscript` 包 9）+ 单页前端，
  本地秒级启动（实测：全新存档从启动到首个 `HTTP 200` 约 0.7 秒，含 102 个演示区块的签名重建）。
- **一个可复现的实验场**：`analyze_chain.py` 能把链数据变成可发布、可复现的指标
  （见 `EXPERIMENT_METRICS.md`，对应白皮书 §13 学术价值与 §14.5 长期建议）。
- **一组可讨论的设计记录**：白皮书 + 20 余篇实现说明，把每个取舍都写下来。

### 它不是什么

为避免误用，先讲清楚：

- ❌ **不是开源许可证意义上的 "open source" 项目**：代码采用 PolyForm Noncommercial 1.0.0，
  明文禁止商业使用（不是 OSI 认可的开源许可）。
- ❌ **不含任何代币、代币发行、交易或募资机制**：UTXO 只是教学用的模拟账本结构。
- ❌ **不是生产系统、不是安全容器、不是合规产品**：沙箱为教学级纯计算隔离，不支持公网部署。
- ❌ **当前没有真实 LLM**：摘要链是 `mock-rule-v1` 确定性规则模板，无幻觉风险但也无真实语义理解。
- ❌ **当前没有遗忘／信息衰减机制**：摘要链仅线性低速增长。

---

## 2. 核心机制

一次提案从输入到「变成一块地层」，走 4 步：

1. **提案（提出）** — 你输入一句自然语言（如 `给列表加一个 head 函数`），
   前端把它映射成一段 NovScript 演示代码与测试用例，打包成一个候选区块，
   由服务端用对应矿工私钥完成 **P-256 ECDSA 确定性签名**。
2. **校验（准入）** — 候选区块进入候选池，走完整 **8 步校验**：
   签名 → 结构 → 创世内核兼容 → PoI mock 计数 → NovScript 解析 → 特性激活 → 沙箱执行 → 语言正负测试 → UTXO。
   任一步失败，区块不入库。
3. **投票（共识）** — 通过校验的区块按**权重加权投票**（`weight_calculator.py`）判定主链归属；
   落选与冲突的区块进入**休眠分支**（不修改账本与纪元），随时可回看，
   并可在后续纪元被显式提升（`BRANCH_PROMOTION_DESIGN.md`）。
4. **上链与持久化（沉降）** — 胜出区块追加到主链，按纪元（`height // 100`）滚动，
   每纪元生成**摘要块**（`epoch_summary.py`），链状态自动落盘到 `data/chain_v1.json`，
   并可通过 `--export` / `persistence.export_chain()` 导出给只读展示或离线分析。

> **一句话结论**：主链是可验证的"语言地层"，休眠分支是被记录的"演化失败史"，
> 而两者的分界线由**签名 + 校验 + 加权投票**共同决定——这三件事在任何一步都不可被 UI 或调用方跳过。

---

## 3. 技术架构

**运行方式**：纯单机、单进程。后端是 Python 标准库 `http.server`（`ThreadingHTTPServer`），
监听 `127.0.0.1:28417`，**仅本机可访问**；前端是单个 `index.html`，同源加载，无构建步骤、无跨域问题。

### 模块清单（33 个运行时 `.py`：顶层 24 + `novscript` 包 9）

| 分组 | 模块 | 职责 |
|---|---|---|
| **数据模型** | `block_model.py` | Block / PoiRecord / Proposal / TestCase 数据结构 |
| | `utxo_model.py` | UTXO 模拟账本数据模型（教学用，非金融工具） |
| **校验与共识** | `block_validator.py` | 8 步校验主入口与 PoI 门槛 |
| | `candidate_pool.py` | 候选区块池（含休眠分支） |
| | `conflict_voter.py` | 冲突消解与投票 |
| | `weight_calculator.py` | 贡献权重计算 |
| | `chain_store.py` | 主链 / 休眠分支存储 |
| | `epoch_manager.py` | 纪元滚动（`EPOCH_BLOCKS=100`） |
| | `epoch_summary.py` | 纪元摘要块（`mock-rule-v1` 规则模板） |
| | `mock_tokenizer.py` | 确定性标准 token 计数 |
| **加密与身份** | `crypto_key.py` | P-256 确定性签名 / 验签（唯一第三方依赖 `ecdsa`） |
| | `miner_identity.py` | 矿工注册表与身份 |
| **持久化** | `persistence.py` | JSON 存档 / 加载 / 导出 / 旧档备份 |
| | `server.py` | HTTP 服务与前端入口 |
| | `analyze_chain.py` | 离线链分析器与实验指标（`--verify` 重验签名） |
| **账本** | `utxo_ledger.py` | UTXO 账本操作与测试 |
| **沙箱** | `novscript/`（9 模块包：`lexer` / `parser` / `ast` / `language` / `registry` / `evaluator` / `sandbox` / `errors`） | NovScript 教学级沙箱解释器（非生产安全容器） |
| **演示脚本** | `demo.py`、`demo_block.py`、`demo_vote_conflict.py`、`demo_utxo.py`、`demo_epoch.py`、`demo_evolution.py`、`demo_ecdsa_sign.py` | 各子系统的独立可跑演示 |

### HTTP API（4 个端点，详见 `API_SPEC.md`）

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/chain-state` | 读主链、纪元快照、休眠分支摘要（前端渲染地层剖面） |
| `POST` | `/propose` | 提交语言扩展提案 → 签名 → 8 步校验 → 加权投票 → 上链或入休眠分支 |
| `POST` | `/eval-novscript` | 用后端真实 NovScript 沙箱执行代码（非前端 mock） |
| `GET` | `/index.html` | 前端页面（同源，无跨域；`/` 等价） |

> **依赖面**：全项目只有 **一个第三方运行时依赖 `ecdsa==0.19.2`**（Apache 2.0）；
> HTTP 服务用标准库，**未使用 Flask / FastAPI / Pydantic**。见 `requirements.txt`。

---

## 4. 快速上手

前置：Python 3.10+（实测 3.13.7）。Windows / macOS / Linux 均可。

```bash
# 1) 进入项目目录
cd tokenmint

# 2) 安装依赖（唯一第三方依赖 ecdsa）
pip install -r requirements.txt
#    Windows 一键：双击 start.bat

# 3) 启动本地服务（监听 127.0.0.1:28417，仅本机可访问）
python server.py

# 4) 打开前端
#    http://127.0.0.1:28417/index.html
```

启动后控制台会打印主链高度与存档路径；`--fresh` 忽略存档从创世重建演示链
（旧档保留为 `.bak-<版本号>`，不删除），`--export PATH` 校验存档并导出后退出。

**离线分析链数据**（不启动服务、不占用 28417 端口）：

```bash
python analyze_chain.py <存档或导出 JSON> --verify
python analyze_chain.py --synthetic --json out.json
```

**跑测试**：

```bash
python -m unittest discover -s tests -p "test_*.py"      # 全量：276 项通过
python -m unittest discover -s tests -p "test_analyze_chain.py"  # 分析器子集（避免占用端口）
```

> ⚠️ **首次启动会生成 `data/chain_v1.json`**，其中含明文矿工私钥。
> 该目录已在 `.gitignore` 中排除，**请勿上传、请勿公开分发**；
> 导出链数据时必须先剥离 `miners` 字段（见 `LICENSE-SCOPE.md` §5）。

---

## 5. 文档索引

| 主题 | 文档 |
|---|---|
| **设计与白皮书** | `TokenMint 设计白皮书 v0.1（完整14章）.md` · `StratumGenesis_白皮书_第X章_共识机制与区块生命周期.md` · `StratumGenesis_最小原型工程规范_NovScript沙箱解释器.md` |
| **接口与契约** | `API_SPEC.md` · `EXPERIMENT_METRICS.md`（指标定义、口径、来源字段、已知局限） |
| **子系统实现** | `BLOCK_LAYER_PROTOTYPE_IMPLEMENTATION.md` · `NOVSCRIPT_PROTOTYPE_IMPLEMENTATION.md` · `CRYPTO_SIGN_IMPLEMENTATION.md` · `PERSISTENCE_IMPLEMENTATION.md` · `UTXO_IMPLEMENTATION.md` · `VOTING_POOL_IMPLEMENTATION.md` · `EPOCH_BASE_IMPLEMENTATION.md` · `EPOCH_SUMMARY_IMPLEMENTATION.md` · `EVOLUTION_IMPLEMENTATION.md` · `BRANCH_PROMOTION_DESIGN.md` · `INTRODUCTION_IMPLEMENTATION.md` |
| **运行与演示** | `ARCHIVE_v0_2_README.md`（归档总说明与架构图）· `DEMO_SCRIPT_v0_2.md` · `使用说明.md` · `mock数据说明.md` |
| **变更记录** | `CHANGELOG_v0_2.md` · `CHANGELOG_v0_3.md` · `UI_CHANGE_NOTE.md` · `UI_LANGUAGE_EVOLUTION_NOTE.md` |
| **存活与部署** | `SURVIVAL_AND_DEPLOYMENT.md`（上线路线、部署者须知、许可方案与备选取舍） |
| **资产清单** | `ARCHIVE_FILE_MANIFEST.md` · `REFERENCE_DOCS_INDEX.md` |
| **许可** | `LICENSE` · `LICENSE-SCOPE.md` · `NOTICE` · `requirements.txt` |

---

## 6. 许可声明

| 对象 | 许可 | 条文 |
|---|---|---|
| **代码**（`*.py`、`index.html`、`start.bat`、脚本与配置） | **PolyForm Noncommercial License 1.0.0** | [`LICENSE`](LICENSE) |
| **文档**（白皮书、实现说明、`README.md`、本文件等） | **CC BY-NC-SA 4.0** | 见各文档页脚 |
| **名称与标识** | 不自动授予商标权 | `LICENSE-SCOPE.md` §6 |
| **第三方依赖** | `ecdsa` → Apache License 2.0 | [`requirements.txt`](requirements.txt) |

- SPDX：代码 `SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0`；文档 `CC-BY-NC-SA-4.0`。
- ⚠️ **PolyForm NC 不是 OSI 开源许可**，本项目不应被称作 "open source"。
- **非商业用途**（个人学习、教学演示、学术研究、免费公开部署、非营利组织实验）无需申请。
- **任何商业用途**（收费服务、订阅／打赏／广告变现、打包进商业产品或 SaaS）
  一律需事先书面授权：联系方式见 `LICENSE-SCOPE.md` §7。
- 再分发时请保留 `LICENSE` / `LICENSE-SCOPE.md` / `NOTICE`、署名与免责声明，
  且**导出链数据前必须剥离 `miners` 字段**（含明文私钥）。

---

## 7. 已知边界

请务必带着这些限制看本项目：

1. **单机仿真实验原型，非生产系统**：无 P2P 网络、无公网部署、无身份鉴权、单进程串行处理。
2. **无任何可交易代币**：UTXO 是教学用模拟账本结构，不发行、不流通、不可交易；
   链内凭证（署名、投票权重、徽章）**没有现实价值**，不对应任何资产或权益。
3. **沙箱是教学级纯计算隔离**，不是生产安全容器，不承担对抗性攻击防护。
4. **存档是实验级 JSON**：无加密、**私钥明文落盘**，除校验和外没有恢复保障。
5. **摘要链为 `mock-rule-v1` 规则模板，非真实 LLM**；未来接入真实 LLM 存在信息衰减与幻觉风险，
   **当前无遗忘／信息衰减实现**，摘要链仅线性低速增长。
6. **共识仅适配小规模仿真网络**；纯非金融激励存在参与者流失风险。
7. **服务端持有全部矿工私钥，`/propose` 替用户签名 = 公网开放后任何人可冒充任何身份**。
   公开部署前必须先把签名移到客户端（WebCrypto / Pyodide），服务端只验签。
8. **免费层会冷启动／休眠**，不适合长期常驻；「多 hub + 数据归档」比「一个稳定 hub」更现实。
9. **本文件不构成法律意见**；许可解释以 `LICENSE` 英文条文为唯一约束性版本。

---

## 8. 下一步建议

按作者负担从低到高，前两项一人即可完成、零服务器成本：

1. **零服务器四件套**：README 徽章 + Pages 只读展馆（`export_chain()` 剥离私钥后放出）
   + Releases 一键包（`start.bat`）+ Codespaces 徽章 —— 详见 `SURVIVAL_AND_DEPLOYMENT.md` §2.1。
2. **浏览器原生版**：用 Pyodide 在浏览器里跑现有 Python 模块，让 Pages 变成「全功能、可玩」，
   链存在访问者自己浏览器里，**作者零运维成本**；顺带把全部测试搬进浏览器做可信度展示。
3. **可部署化**：补 `Dockerfile` + `DEPLOY.md` + `render.yaml`，配一段「谁有实力谁去部署」的 hub 注册表。
4. **签名下沉**：把签名移到客户端、服务端只验签，才谈得上公网部署；同期设计同一高度候选收集窗口规则。

---

## 9. 徽章位（待 CI 就绪后替换为真实统计）

本节的徽章目前都是**手工填写的静态标签**，不代表任何持续集成的结果。
本节徽章的真实来源（仓库：<https://github.com/lyh9712/stratumgenesis>；CI 就绪后即可生效）：

```html
<!-- 构建状态（GitHub Actions） -->
[![CI](https://github.com/lyh9712/stratumgenesis/actions/workflows/ci.yml/badge.svg)](https://github.com/lyh9712/stratumgenesis/actions)

<!-- 测试覆盖率（Codecov 等） -->
[![codecov](https://codecov.io/gh/lyh9712/stratumgenesis/branch/main/graph/badge.svg)](https://codecov.io/gh/lyh9712/stratumgenesis)

<!-- Release 版本（若将来发布上架，再补该徽章；包名未定，此处暂不列出） -->
[![Latest release](https://img.shields.io/github/v/release/lyh9712/stratumgenesis)](https://github.com/lyh9712/stratumgenesis/releases)

<!-- 许可与运行环境 -->
[![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial-4183c4)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-3776ab)](requirements.txt)
```

> 若你不用 GitHub Actions，可换成 GitLab CI / CircleCI / Read the Docs 等平台的等价徽章，
> 保持「状态 + 覆盖率 + 版本 + 许可」四类信息齐全即可。


---

## 11. 访问统计与分享物料

- **匿名访问计数**：`index.html` 会向第三方免费计数服务
  `abacus.jasoncameron.dev` 发一次请求（`/hit/stratumgenesis/pages-views`），
  并在状态区显示「已有 N 次打开」。**该请求不携带任何个人信息、不使用 Cookie**；
  若服务不可达，计数元素自动隐藏，不影响页面任何功能。不想要计数？删掉
  `index.html` 里 `visit-counter` 相关的那段 `fetch` 即可。
- **分享预览图**：仓库根目录 `og-preview.png`（1200×630），已通过
  `og:image` / `twitter:image` 引用，把链接发到社交平台时会显示标题＋简介＋缩略图。
- **推广文案与节奏**：见 `PROMOTION_KIT.md`（各平台可直接粘贴的文案、配图建议、
  「不要做什么」清单、观测指标）。
- **本站不是加密货币**：无代币、无募资、无金融功能；任何把本项目用于代币发行或
  金融中介的行为都在许可范围之外（见 `LICENSE-SCOPE.md`）。