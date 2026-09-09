# StratumGenesis · v0.3 版本变更日志

> 版本：v0.3（阶段 A：git 基线 + 磁盘持久化与链数据导出）
> 日期：2026-09-09
> 基线：v0.2（前后端打通 · 单机内存仿真 · 72 项测试）

## v0.3 · 阶段 A

### 版本控制基线

- 在 `E:\my-code\tokenmint` 建立本项目独立 git 仓库（父目录为无关项目的 monorepo，不在此仓库内混入其他项目文件）。
- 新增 `.gitignore`：忽略 `__pycache__/`、`*.pyc`、`server.log`、`data/`、`*.tmp`。
- 提交 v0.2 归档基线并打标签：`git tag v0.2`（commit `59bfe1b`）。
- 已在 `CHANGELOG_v0_2.md` 末尾追加基线记录行。

### 磁盘持久化与链数据导出

- 新增 `persistence.py`：
  - 确定性 JSON 存档格式（`format_version=chain-v1`）；
  - 落盘最小权威状态：主链全部区块 + 休眠分支（分支标识 + 区块序列）+ 矿工注册表（含私钥）+ 拒绝原因；
  - UTXO 账本与纪元快照**不序列化**，加载时从主链按既有规则确定性重建（防漂移 + 天然校验）；
  - 原子写入（临时文件 + `os.replace`）；
  - 逐区块 SHA-256 哈希校验；损坏/版本不匹配拒绝加载；
  - `save_state` / `load_state` / `rebuild_store` / `export_chain` / `miners_to_list` / `miners_from_list` / CLI `python persistence.py export <path>`。
- `server.py` 接入：
  - 启动策略：有存档则加载继续（不再预沉积）；无存档维持创世 + 预沉积 102 并立即落盘；
  - `--fresh` 忽略存档重建演示链；`--export <path>` 校验并导出存档后退出；
  - 每次链状态变更（成功上链 / 候选入休眠分支）自动保存，失败仅打印中文警告不影响操作；
  - 存档缺失/损坏/版本不匹配：中文明确报错并拒绝启动，提示 `--fresh`；
  - 三个既有 API 响应契约不变；`chain-state.miners` 数组改为按公钥稳定排序输出。
- 新增 `tests/test_persistence.py` 8 项测试（roundtrip 等值、HTTP 一致性、损坏拒绝、--fresh、导出）。

### 文档

- 新增 `PERSISTENCE_IMPLEMENTATION.md`：格式、format_version、保存/恢复策略、为何账本与快照重建而非序列化、私钥持久化安全边界、已知限制。
- 新增 `CHANGELOG_v0_3.md`（本文件）。
- 更新 `API_SPEC.md`、`使用说明.md`：存档路径、`--fresh`、导出方式。
- 更新 `ARCHIVE_FILE_MANIFEST.md`、`REFERENCE_DOCS_INDEX.md` 登记新文件。

### 验证结果

- 全量回归：`python -m unittest discover -s tests -v` → **80 项全部通过，失败 0**（72 原有 + 8 新增）。
- 字节码检查：`python -m compileall -q *.py tests/*.py` 通过。
- 手工验证：首次启动 102 → `/propose` 后 103 → 停止重启加载存档仍为 103（提案仍在）→ `--fresh` 回到 102；导出 CLI 产出 `chain-v1` 完整副本。

## 尚未实现（沿用 v0.2 清单，本阶段未触碰）

- 纪元 LLM 摘要 / 摘要投票；引种提案；大断层事件；
- P2P 网络、真实 tokenizer、真实 LLM；
- 增量归档、加密存档、校验和文件、密钥托管；
- 任何可交易代币或现实金融功能。
