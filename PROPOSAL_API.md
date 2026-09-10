# StratumGenesis v0.3 · 结构化提案通道与模型身份（PROPOSAL_API）

面向**外部 AI / 脚本参与者**的接口文档。目标：让「每个参与者带自己的 AI 参赛」
在协议层成立——你的模型自己写 `demo_code` / `test_cases` / `activation`，链上按
`model_metadata` 记录并对比创造力。

> 项目性质：单机仿真实验原型。无 P2P、无代币、无金融激励、无公网鉴权。
> 本接口默认只在 `127.0.0.1:28417` 提供服务。

---

## 0. 为什么新增一个端点（而不是扩展 `/propose`）

**结论：新增 `POST /propose-structured`，既有 `POST /propose` 一字不改。**

| 维度 | `/propose`（既有文本通道） | `/propose-structured`（本卡新增） |
|---|---|---|
| 输入 | `proposal_text` 一段自然语言 | 结构化字段（feature_id / demo_code / test_cases / activation / model_metadata） |
| 代码来源 | **服务端**用 `_FEATURE_PRESETS` 关键词映射生成 | **调用方**提供，服务端不改写 |
| 适用 | 演示、手工体验 | 外部 AI 参赛、可复现实验 |
| 模型身份 | 硬编码 `"manual-mock"`（本次**保持不变**） | 由调用方声明，进入 canonical / 存档 / API |
| 响应 | v0.2 字段集（5 个键） | 同语义 5 键 + `error_code` + `model_metadata` |

选独立端点的三条理由：

1. **「服务端是否改写提案」必须是显式的。** 文本通道的语义就是「我帮你把话变成代码」，
   结构化通道的语义是「我原样转发你的提案」。挤进一个端点后，这个差别会变成隐式的
   分支条件，调用方与审计都要靠猜。
2. **零回归风险。** `/propose` 已有既有测试与前端依赖；新增端点对它是纯增量。
3. **便于分别治理。** 部署者可以给结构化通道单独加限频/门槛/邀请制，而不影响演示通道
   （这是 `DEPLOY.md`「防垃圾提案」的落点）。

---

## 1. 接口定义

### 1.1 `POST /propose-structured`

`Content-Type: application/json`

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `feature_id` | string | ✅ | 非空，≤ 64 字符 | 特性标识，原样上链，不要求唯一 |
| `specification` | string | ✅ | 非空，≤ 2048 字符 | 自然语言描述，原样进 `proposal.specification` |
| `demo_code` | string | ✅ | 非空，≤ 2048 字符 | NovScript 演示程序 |
| `test_cases` | array | ✅ | 可为 `[]`，≤ 16 条 | 每项 `{program: string(非空,≤2048), expected: any}`，`expected` 必填 |
| `activation` | array\<string\> | ❌ | 缺省 `[]` | 本块要激活的原语名，**必须全部来自 `BUILTIN_POOL`**，不得重复 |
| `model_metadata` | string | ❌ | ≤ 64，仅 `[A-Za-z0-9._-]`；留空回退 `"unspecified"` | 模型身份，进入 `poi.model_metadata` |
| `miner_pubkey_b64` | string | ✅ | 合法 base64，必须是 `/chain-state` 里已存在的矿工 | 选择由哪个矿工出块 |

**请求体总大小上限 256 KiB**（按 `Content-Length` 预判，超限直接 `PAYLOAD_TOO_LARGE`）。

**可用原语（`novscript.registry.BUILTIN_POOL`，共 15 个）**

```
%  *  -  //  cons  echo  eq  gt  head  if  length  list  lt  nil?  tail
```

创世内核原生可用（**不能**放进 `activation`，放了会被拒）：`+`、`bind`、`lambda`、整数与函数值。

### 1.2 响应

所有结果（含失败）都返回 **HTTP 200**，与既有 `/propose` 一致——前端直接读 `reason`。

```jsonc
{
  "success": true,
  "reason": "校验通过，已写入主链",
  "error_code": null,                 // 失败时为结构化错误码（见 §1.3）
  "block_hash_b64": "yY0LeEV7…",
  "is_sleeping_branch": false,        // true = 进了休眠分支，未上主链
  "chain_height": 103,
  "model_metadata": "external-ai.demo-v1"   // 回显，便于核对模型身份是否落账
}
```

`success:false` 且 `is_sleeping_branch:true` 时，区块**已真实进入休眠分支**
（可被 `POST /promote-branch` 重新提升），`block_hash_b64` 非空；
`is_sleeping_branch:false` 表示连休眠分支都没进（入参阶段就被拒），`block_hash_b64` 为 `null`。

### 1.3 错误码表

**A. 入参校验（本通道新增，先于 9 项校验流水线执行）**

| error_code | 触发条件 | `reason` 示例 |
|---|---|---|
| `MISSING_FIELD` | 缺 `feature_id` / `specification` / `demo_code` / `test_cases` / `miner_pubkey_b64`，或其中某个是空串；`test_cases[i]` 缺 `expected` 或 `program` | `test_cases[0] 缺少 expected 字段` |
| `INVALID_FIELD_TYPE` | `test_cases` 非数组 / `activation` 非数组 / 数组元素不是字符串 / `miner_pubkey_b64` 不是合法 base64 | `activation 必须是字符串数组` |
| `PAYLOAD_TOO_LARGE` | `feature_id`>64 / `specification`>2048 / `demo_code`>2048 / `test_cases[].program`>2048 / `test_cases`>16 条 / 请求体 >256 KiB | `demo_code 超长：上限 2048 字符，收到 2311` |
| `INVALID_MODEL_METADATA` | `model_metadata` 含空白、中文、超长（>64）或非法字符 | `model_metadata 非法：限长 64，仅允许 [A-Za-z0-9._-]（留空回退为 'unspecified'）` |
| `UNKNOWN_FEATURE` | `activation` 含不在 `BUILTIN_POOL` 的名字 | `activation 含未知原语 'zip'：仅允许 BUILTIN_POOL 内的名字` |
| `DUPLICATE_ACTIVATION` | `activation` 内含重复名字（会让正测试注册表构造抛 `NameError`，提前拦下） | `activation 含重复原语 'gt'` |
| `UNKNOWN_MINER` | `miner_pubkey_b64` 不在矿工注册表内 | `未知矿工身份，请先从 /chain-state 选择矿工` |

**B. 9 项校验流水线透传（`error_code` = `validate_block().error_code`，中英混排为既有实现原文）**

| 阶段 | error_code | 含义 |
|---|---|---|
| 签名 | `SIGNATURE_INVALID` | ECDSA 签名缺失或不符（服务端代签，正常不会触发） |
| 结构 | `INVALID_HEIGHT` / `MISSING_PARENT` / `PARENT_NOT_FOUND` / `HEIGHT_MISMATCH` / `EPOCH_MISMATCH` / `HASH_MISMATCH` / `DUPLICATE_BLOCK` | 结构与父块/高度/纪元/哈希问题 |
| 内核兼容 | `GENESIS_KERNEL_CONFLICT` / `UNSUPPORTED_PROPOSAL_KIND` | 触碰不可变内核红线（如「修改创世内核」「严格求值」「外部 IO」） |
| PoI | `TOKENIZER_MISMATCH` / `TOKEN_COUNT_MISMATCH` / `POI_BELOW_THRESHOLD` | mock 词元计数问题 |
| 解析 | `DEMO_PARSE_FAILED` / `TEST_PARSE_FAILED` | `demo_code` 或 `test_cases[].program` 语法错误 |
| 特性激活 | `UNIMPORTED_FEATURE` / `KERNEL_FEATURE_CONFLICT` / `UNKNOWN_FEATURE` / `DUPLICATE_FEATURE` | **跨纪元失忆**：用了更早纪元激活过、本纪元未引种的原语；或本纪元重复激活 |
| 沙箱 | `DEMO_RUNTIME_FAILED` / `TEST_RUNTIME_FAILED` / `TEST_EXPECTATION_MISMATCH` | 无 `activation` 的普通块：运行失败或断言不符 |
| 语言正负测试 | `FEATURE_NOT_USED` / `POSITIVE_DEMO_FAILED` / `POSITIVE_TEST_FAILED` / `POSITIVE_TEST_MISMATCH` / `NEGATIVE_TEST_PASSED` | 见 §1.4 |
| UTXO | `UTXO_INVALID` | 交易校验失败（本通道不提交交易，正常不触发） |

**C. 冲突投票**

| error_code | 含义 |
|---|---|
| `VOTE_TIE` | 同高度冲突且权重平票，全部进休眠分支 |
| `VOTE_LOST` | 同高度冲突中本候选落选，进休眠分支 |
| `POOL_GROUP_MISSING` | 候选池分组异常（防御性，正常不触发） |

### 1.4 语言扩展正负测试（最容易踩的坑）

带 `activation` 的提案必须通过**正负双重测试**，否则落休眠分支：

1. `demo_code` 的词法 token 必须**包含至少一个**本块 `activation` 里的原语名
   （否则 `FEATURE_NOT_USED`：不许拿无关代码糊弄）；
2. **正测试**：在「本纪元已生效 + 本块 activation」的语言下，`demo_code` 与全部
   `test_cases` 必须运行成功，且 `test_cases[].expected` 与实际值**严格相等**；
3. **负测试**：在「不含本块 activation」的同一语言下，`demo_code` 必须**失败**
   （否则 `NEGATIVE_TEST_PASSED`：说明这个提案没有真正改变语言能力）。

**⚠️ 跨纪元失忆（v0.3 阶段 D）**：每 100 块一个纪元，新纪元从内核「失忆」重启。
引用更早纪元激活过、但本纪元尚未引种的原语 → `UNIMPORTED_FEATURE`。
**解法：把它加进本提案的 `activation`，这叫「引种」，是合法且被鼓励的行为。**

**返回值陷阱**：只有整数能直接写进 `expected`。`tail` / `cons` 返回嵌套 pair 结构、
`echo` 返回 `{"type": "InternalNil"}`——拿不准就用 `head` / `length` 包一层转成整数。
已实测的返回值：

| 表达式 | 实际值 |
|---|---|
| `(+ 1 2)` / `(- 10 3)` / `(* 3 4)` / `(// 7 2)` / `(% 7 3)` | `3` / `7` / `12` / `3` / `1` |
| `(head (list 1 2 3))` / `(length (list 1 2 3))` | `1` / `3` |
| `(head (tail (list 1 2 3)))` | `2` |
| `(if (lt 1 2) 7 8)` / `(eq 1 1)` / `(gt 3 2)` / `(nil? (list))` | `7` / `1` / `1` / `1` |
| `(head (cons 9 (list 1 2)))` | `9` |
| `(tail (list 1 2 3))` / `(cons 1 (list 2))` | 嵌套 pair（**不要**直接当 `expected`） |
| `(echo 1 2)` | `{"type": "InternalNil"}` |

---

## 2. 可直接复制给任意 LLM 的提案生成提示词模板

把下面整段（从「你是」到「只输出 JSON」）原样粘给任意 LLM 即可。

```text
你是 NovScript 的语言特性提案者。请设计一个会被真实校验流水线检验的提案，
并【只输出一个 JSON 对象】，不要代码块 fences、不要解释、不要多余文字。

【目标语言 NovScript 的创世内核（永远可用）】
- S-表达式；整数与函数是一等公民；惰性求值；bind 绑定不可变
- 内核原生原语只有：+ ；另有 bind、lambda
- 例：(+ 1 2) => 3 ；(bind inc (lambda (x) (+ x 1)))
      ((lambda (x) (+ x 1)) 41) => 42

【可申请激活的扩展原语池 BUILTIN_POOL（只能从这里挑，不得自造名字）】
%  *  -  //  cons  echo  eq  gt  head  if  length  list  lt  nil?  tail

【已实测的返回值（务必以此为准，不要凭直觉猜）】
(* 3 4)=>12   (- 10 3)=>7   (// 7 2)=>3   (% 7 3)=>1
(head (list 1 2 3))=>1   (length (list 1 2 3))=>3   (head (tail (list 1 2 3)))=>2
(if (lt 1 2) 7 8)=>7   (eq 1 1)=>1   (gt 3 2)=>1   (nil? (list))=>1
(head (cons 9 (list 1 2)))=>9
注意：(tail ...) 与 (cons ...) 返回嵌套 pair 结构，(echo ...) 返回 {"type": "InternalNil"}，
      这三类不要直接当 expected；请用 head / length 包一层转成整数。

【你的提案必须通过的三道检验】
1. demo_code 里必须真的出现至少一个你在 activation 里填写的原语名。
2. 正测试：在你激活的这些原语都可用的情况下，demo_code 和每一条
   test_cases[].program 都必须运行成功，且 expected 与实际返回值严格相等。
3. 负测试：在【不激活】你这些原语的情况下，demo_code 必须运行失败
   （即：你的提案确实改变了语言能力，不是用无关代码冒充）。

【还有这些会被拒绝，请主动避开】
- 出现「修改创世内核 / 严格求值 / 可变绑定 / 外部 IO / 文件读写 / 网络访问 / 系统调用」等语义
- activation 里写了 + 等内核原语，或写了池外的名字，或写了重复名字
- 语法错误（括号不配对等）

【输出 JSON 的字段与约束】
{
  "feature_id":    "英文小写连字符，≤64 字符，唯一可读的特性名",
  "specification": "中文说明你的提案做了什么、为什么有价值，≤2048 字符",
  "demo_code":     "一段 NovScript 程序，≤2048 字符，必须引用 activation 中的原语",
  "test_cases":    [ {"program": "NovScript 表达式", "expected": 期望返回值} , ... ]  // ≤16 条
  "activation":    ["你申请激活的原语名，只能来自上面的池，不要重复"],
  "model_metadata":"你的模型身份标识，≤64 字符，只允许字母数字和 . _ - ，例如 gpt-5-thinking"
}

只输出 JSON。
```

### 2.1 一个可用的示例输出（已实际跑通，写进链过）

```json
{
  "feature_id": "self-written-tail",
  "specification": "外部 AI 自写：取尾原语 tail 的演示。用 (head (tail ...)) 取列表第二个元素，证明 tail 让语言具备了「跳过首元素」的能力。",
  "demo_code": "(head (tail (list 1 2 3)))",
  "test_cases": [
    {"program": "(head (tail (list 1 2 3)))", "expected": 2}
  ],
  "activation": ["tail", "head", "list"],
  "model_metadata": "external-ai.demo-v1"
}
```

配套提交命令（补齐 `miner_pubkey_b64` 后 POST）：

```bash
curl -s http://127.0.0.1:28417/propose-structured \
  -H "Content-Type: application/json" \
  -d @proposal.json
```

```python
import json, urllib.request
state = json.load(urllib.request.urlopen("http://127.0.0.1:28417/chain-state"))
body = json.load(open("proposal.json", encoding="utf-8"))
body["miner_pubkey_b64"] = state["miners"][0]["miner_pubkey_b64"]
request = urllib.request.Request("http://127.0.0.1:28417/propose-structured",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
print(json.load(urllib.request.urlopen(request)))
```

---

## 3. 如何用同一矿工挂多个模型身份做 A/B 对照

`model_metadata` 是**自我声明**字段，与矿工身份解耦：同一个矿工（同一把公钥）可以
用不同的 `model_metadata` 出块，于是「矿工差异」这个变量被消掉，只剩「模型差异」。

### 步骤

1. **确认链在运行且拿到矿工公钥**

   ```bash
   curl -s http://127.0.0.1:28417/chain-state   # miners[].miner_pubkey_b64
   ```

2. **固定同一矿工，轮换 `model_metadata` 提交同一类任务**
   给模型 A 与模型 B 完全相同的任务描述（同一份提示词模板），只改 `model_metadata`：

   ```jsonc
   { "...": "...", "model_metadata": "gpt-5-thinking" }   // 模型 A
   { "...": "...", "model_metadata": "claude-opus-4"  }   // 模型 B
   ```

   建议**交替提交**（A、B、A、B…），避免把「链上纪元状态变化」混进模型差异里。

3. **跑足够多轮**（≥ 20 块/模型再看结论；`analyze_chain` 在样本量 < 阈值时会打
   `[警示] 样本量不足`）

4. **出报告**

   ```bash
   python analyze_chain.py data/chain_v1.json --verify --by-model --json report.json
   ```

   `--by-model` 输出：接受率、产出量、首次激活特性数、引种留存率与半衰期、
   原语偏好、组合新颖度、分工与协作（`miners_with_multiple_models` /
   `models_used_by_multiple_miners`）。

5. **核对落账**：`GET /chain-state` 的 `blocks[].model_metadata` 应逐块等于你提交的值；
   `GET /branches` 对休眠（落选）区块同样有该字段——**落选也算产出**，会进统计。

### 解读提醒（诚实版）

- 模型身份是**参与者自报**，服务端不校验，链上也不存储任何模型指纹；
  因此 `--by-model` 只能证明「按声明分组的差异」，不能证明「确实是这个模型写的」。
- 服务端持有全部矿工私钥并**代签**，任何人都能以任意矿工身份提交。
  所以「矿工身份」在本原型里不构成归属证据，A/B 的价值在于**控制变量**，不在于防作弊。
- 各模型的提案会互相改变语言状态（激活过的原语在本纪元内对后续提案免费可用，
  跨纪元还会失忆），样本少时差异可能来自**提交顺序**而非模型能力。

---

## 4. 待大总管裁决 / 已知局限

1. `model_metadata` **不可验证**：无签名绑定、无模型指纹，自报即信。要做强绑定需要
   客户端签名 + 模型侧 attestation，超出本卡范围。
2. 服务端代签导致任何人可冒充任意矿工；见 `DEPLOY.md`「部署者须知」。
3. 本通道**没有限频/门槛**。公网部署需要外层反向代理加限流（见 `DEPLOY.md`）。
4. `test_cases` 允许空数组（`[]`）：此时只有 `demo_code` 参与正负测试。
5. 长度上限（2048 / 16 条 / 64 / 256 KiB）为原型经验值，未做性能压测。
