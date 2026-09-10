# StratumGenesis HTTP API 接口规范

- 服务：`server.py`（Python 标准库 `http.server`）
- 监听：`http://127.0.0.1:28417`（仅 localhost，不支持公网）
- 返回：统一 JSON（UTF-8）
- 全部状态保存在内存，服务关闭即清空；无 P2P、无磁盘持久化、无鉴权、无 HTTPS

启动方式：

```bash
python server.py
```

启动时自动初始化创世链，并预沉积 102 个合法演示区块（真实经过完整校验流水线、UTXO 奖励与纪元快照），因此打开页面即可看到完整地层剖面。

---

## 1. GET /chain-state

读取主链、纪元快照与休眠分支摘要，用于前端渲染地层剖面。

示例：

```
GET http://127.0.0.1:28417/chain-state
```

响应示例：

```json
{
  "chain_height": 102,
  "epoch_blocks": 100,
  "blocks": [
    {
      "height": 0,
      "epoch": 0,
      "miner_label": "创世者",
      "miner_pubkey_b64": "Z2VuZXNpcw==",
      "feature_name": "novscript-genesis-kernel",
      "description": "创世内核……",
      "demo_code": "(+ 1 2)",
      "test_cases": [{"program": "(+ 1 2)", "expected": 3}],
      "block_hash_b64": "……"
    }
  ],
  "epochs": [
    {"epoch_number": 0, "start_height": 0, "end_height": 99, "block_count": 100, "archived": true,
     "summary": {"status": "finalized", "method_label": "mock-rule-v1", "final_text": "本纪元高频主题……",
                  "winner_candidate_id": "mock-rule-v1:keyword-top", "winner_producer_label": "地层匠·沧石",
                  "tie_occurred": false,
                  "candidates": [{"candidate_id": "mock-rule-v1:keyword-top", "text": "……",
                                   "producer_label": "地层匠·沧石", "weight": 3420}]},
     "summary_status": "finalized"},
    {"epoch_number": 1, "start_height": 100, "end_height": 102, "block_count": 3, "archived": false,
     "summary": null, "summary_status": "pending"}
  ],
  "summary_chain": [ /* 与已归档纪元的 summary 同构，按纪元顺序排列 */ ],
  "sleeping_branches": [
    {
      "height": 103,
      "epoch": 1,
      "miner_label": "沉积者·阿砚",
      "feature_name": "内核算术扩展",
      "description": "修改创世内核并启用严格求值",
      "demo_code": "(bind x (+ 1 2))\nx",
      "test_cases": [{"program": "(+ 1 2)", "expected": 3}],
      "block_hash_b64": "……",
      "reason": "kernel_compatibility: GENESIS_KERNEL_CONFLICT"
    }
  ],
  "miners": [
    {"label": "沉积者·阿砚", "miner_pubkey_b64": "……", "balance": 3400}
  ]
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `chain_height` | 主链末端高度 |
| `blocks` | 主链全部区块（高度升序）；`miner_label`、`miner_pubkey_b64`、`feature_name`、`description`、`demo_code`、`test_cases`、`block_hash_b64` 供前端渲染 |
| `epochs` | 纪元快照；`archived=true` 表示已归档（前端显示为半透明古岩层）。v0.3 阶段 B 追加：`summary`（已归档纪元为 finalized 摘要对象，未封口为 null）、`summary_status`（pending/finalized） |
| `summary_chain` | v0.3 阶段 B 追加：按纪元顺序的已确定摘要数组（与 `epochs[i].summary` 同构，为「大断层事件」预留） |
| `sleeping_branches` | 休眠/落选区块摘要，含拒绝原因 `reason` |
| `miners` | 可用矿工身份与链内 UTXO 余额（仅演示查询；余额与投票权重完全隔离） |

---

## 2. POST /propose

提交语言扩展提案。服务端执行：提案文本解析 → 生成演示代码与测试用例 → 构造候选区块并用矿工私钥完成 ECDSA 签名 → 送入候选池 → 完整 6 阶段校验（签名/结构/创世内核兼容/PoI mock/解析/沙箱/UTXO）→ 冲突加权投票 → 成功上链；失败或落选存入休眠分支（不修改账本与纪元）。

请求：

```
POST http://127.0.0.1:28417/propose
Content-Type: application/json

{
  "proposal_text": "函数增量扩展",
  "miner_pubkey_b64": "<来自 /chain-state 的 miners 字段>"
}
```

响应示例（成功）：

```json
{
  "success": true,
  "reason": "校验通过，已写入主链",
  "block_hash_b64": "……",
  "is_sleeping_branch": false,
  "chain_height": 103
}
```

响应示例（校验失败 / 平票 / 落选）：

```json
{
  "success": false,
  "reason": "校验未通过（kernel_compatibility）",
  "block_hash_b64": "……",
  "is_sleeping_branch": true,
  "chain_height": 102
}
```

说明：

- `miner_pubkey_b64` 必须是 `/chain-state` 返回的矿工身份；服务端持有一一对应的私钥并完成签名，前端无法伪造身份；
- 提案文本含「修改内核 / 严格求值 / 可变绑定」等与创世内核冲突的关键词时，会被真实校验流水线第 2 阶段拒绝；
- 由于本原型内核仅支持整数、函数与 `+` 加法，服务端会把提案文本映射为内核语法范围内的演示代码（详见下节），映射是简化的 mock 行为；
- `is_sleeping_branch=true` 表示该候选未进入主链，被保存为休眠分支；
- 同高度冲突时执行历史贡献加权投票；平票时所有候选进入休眠分支。

### 提案文本 → 演示代码映射

| 关键词 | 生成的演示代码 | 测试用例 |
|---|---|---|
| 函数 / lambda / 增量 | `(bind inc (lambda (x) (+ x 1)))` + `(inc 41)` | `((lambda (x) (+ x 1)) 41)` → 42 |
| 绑定 / bind / 变量 | `(bind a 1)` + `(bind b 2)` + `(+ a b)` | `(+ 1 2)` → 3 |
| + / 求和 / 加法 | `(+ 3 4)` | `(+ 3 4)` → 7 |
| 注释 | `;; <提案文本>` + `(+ 2 3)` | `(+ 2 3)` → 5 |
| 其他（默认） | `(bind x (+ 1 2))` + `x` | `(+ 1 2)` → 3 |

> 注意：NovScript 创世内核只支持整数与函数、不可变 bind、惰性求值和 `+` 加法。生成代码必须落在内核语法范围内，否则会在真实解析/沙箱校验阶段被拒绝——这正是本原型刻意保持的“内核不可修改”约束的体现。

---

## 3. POST /eval-novscript

调用后端真实 NovScript 沙箱解释器执行代码（非前端 mock）。

请求：

```
POST http://127.0.0.1:28417/eval-novscript
Content-Type: application/json

{"code": "(+ 1 2)"}
```

响应示例（成功）：

```json
{
  "ok": true,
  "value": 3,
  "error_type": null,
  "error_message": null,
  "steps": 5
}
```

响应示例（失败）：

```json
{
  "ok": false,
  "value": null,
  "error_type": "语法错误",
  "error_message": "line 1, column 7: expected ), got EOF",
  "steps": 0
}
```

`error_type` 中文取值：`词法错误`、`语法错误`、`未绑定名称`、`类型错误`、`参数数量错误`、`递归超限`、`资源限制`、`沙箱错误`。

---

## 4. GET /index.html

返回前端页面（同源，无跨域问题）。也可访问 `/`。

---

## 5. 磁盘持久化与链数据导出（v0.3 新增）

### 存档路径

- 默认存档：`data/chain_v1.json`（项目根目录下，已在 .gitignore 中排除）；
- 格式：JSON，`format_version=chain-v1`；内容为主链全部区块、休眠分支（分支标识 + 区块序列 + 拒绝原因）、矿工注册表（含私钥）；
- UTXO 账本与纪元快照不在存档中序列化，加载时从主链按既有规则确定性重建；
- 写入采用临时文件 + 原子替换，逐区块 SHA-256 哈希校验。

### 启动 / 复位

```bash
# 有存档则加载继续；无存档则预沉积 102 演示块并立即落盘
python server.py

# 忽略存档，从创世重建演示链（演示复位用）
python server.py --fresh

# 指定存档路径
python server.py --archive data/my_chain.json
```

- 每次链状态变更（成功上链 / 候选入休眠分支）后自动保存；保存失败打印中文警告，不影响本次操作。
- 存档缺失/损坏/format_version 不匹配：中文明确报错并**拒绝启动**，提示使用 `--fresh`。

### 导出

```bash
# 校验当前存档并导出到指定路径（与存档相同格式），导出后退出不启动服务
python server.py --export data/chain_v1_export.json

# 等价 CLI
python persistence.py export data/chain_v1_export.json
```

### 安全边界

矿工私钥为原型本地演示密钥，明文保存在本机存档中；无加密、无生产安全承诺，仅限本机实验使用。

## 测试

```bash
# 先停止手动启动的 server.py（端口 28417 会被测试占用）
python -m unittest discover -s tests -v
python -m compileall -q .
```

测试覆盖：chain-state 结构、合法提案上链、内核冲突进休眠分支、未知矿工拒绝、沙箱执行成功/语法错误/未绑定名称、index.html 可访问。

---

## 已知限制

1. 无 P2P、无公网部署、无身份鉴权、无 HTTPS、无数据库；持久化仅为实验级 JSON 存档（默认 data/chain_v1.json，无加密，服务关闭后仅存档保留，内存候选池等易失状态丢失）。
2. ECDSA 仅为实验原型签名，不是生产级密码学。
3. 沙箱是教学级纯计算隔离，不是生产安全容器。
4. LLM 摘要（未来模块）存在信息衰减与幻觉风险；摘要链仅线性低速增长。
5. 共识仅适配小规模仿真网络。
6. 无任何可交易代币或现实金融功能；UTXO 余额与投票权重完全隔离。
