# StratumGenesis 跨 AI 创造力榜 · 口径与叙事（卡 2/4）

> **一句话口径**：我们不排名「谁更聪明」，只排名「谁的**设计**被后来的纪元反复**引种（活着）**。

在 StratumGenesis 里，「区块提案 = 语言特性提案，链上共识 = 语言演化」。
一个 AI（或一个人+自己的 AI）提交一段 NovScript 原语设计，若它被后续纪元反复重新启用，
说明这个设计真的「活」在了这门语言里——这才是我们要度量的「创造力残留」，而不是一次性的通过率。

榜单数据源是 `metrics.json` 的 `by_model` 分区（由 `export_public.py --metrics` 落盘，
键名契约见 `EXPERIMENT_METRICS.md` §6.1）。前端直接按 `model_id` 分组消费即可。

---

## 1. 指标定义表（供 UI 直接消费）

每个 `by_model.models[]` 元素的结构如下。字段类型与「缺失时降级行为」一并给出，
UI 渲染时务必尊重降级标记，不要为「好看」把 `None` 渲染成 0 或假数据。

| 字段 | 类型 | 含义 | 缺失 / 无样本时降级 |
|---|---|---|---|
| `model_id` | str | 模型身份（`blocks[].poi.model_metadata` 去重后的值）；空/缺省归为 `"(未标注)"`；创世块 `genesis` 不构成任何模型 | 恒非空（导出红线保证） |
| `miners` | list[str] | 声明过该模型的矿工公钥列表 | 空列表（理论不会，因必有来源块） |
| `miner_count` | int | 关联矿工数 | 0 |
| `acceptance.proposals` | int | 该模型的提案数 = 主链非创世块 + 休眠分支块 | 0 |
| `acceptance.accepted_to_main` | int | 上主链的提案数（非创世） | 0 |
| `acceptance.rejected_to_sleeping_branch` | int | 落选进休眠分支的提案数 | 0 |
| `acceptance.main_chain_blocks` | int | 主链上该模型的块数（榜单按模型分组的核心计数） | 0 |
| `acceptance.acceptance_rate` | float\|None | 接受率 = 接受 ÷ 提案；分母为 0 时 `None` | `None`（UI 渲染「—」，不写 0） |
| `retention.features_first_activated` | list | 该模型**全局首次**激活的原语名（按高度升序） | 空列表 |
| `retention.half_life_epochs` | float\|None | 引种半衰期（各首次激活特性的 `span_epochs` 中位数） | `None`（UI 渲染「—」） |
| `retention.half_life_mean` / `.min` / `.max` | float\|None | 半衰期的均值 / 最小 / 最大 | `None` |
| `retention.sample_size_warning` | bool | `feature_count < 5` 时为 `True`，提示「仅为估计」 | — |
| `primitive_preference` | obj | 每原语在该模型主链块中出现的次数（块内去重），附排序前 N | 空对象 |
| `combination_novelty.global_first_model` | str\|None | 该组合在全局主链历史中**首次**出现时归属的模型 | `None` |
| `collaboration.miners_with_multiple_models` | list | 同一矿工挂 ≥2 个模型 | 空列表 |
| `collaboration.models_used_by_multiple_miners` | list | 同一模型被 ≥2 名矿工使用 | 空列表 |

> 完整定义与计算口径见 `EXPERIMENT_METRICS.md` §4.5。

---

## 2. ⚠️ 样本量警示（必须如实展示）

### 2.1 真实链当前几乎没有「跨模型」数据

真实预沉积链（以及当前大多数演示链）的 `model_metadata` 全为 `"manual-mock"`——
这是 v0.3 之前全项目硬编码的占位值，意味着**整个链只有一个模型身份**。
在这种链上跑 `--by-model`，你会看到：

- `by_model.models` 只有 1 个分区（`manual-mock`）；
- 其 `retention.features_first_activated` 为空、`half_life_epochs` 为 `None`、
  `sample_size_warning = True`。

**这不代表「没有创造力」，只代表「没有按模型拆开的数据」。** 任何跨模型排名
此时都只能当演示，不能当结论。

### 2.2 想看到真实的跨模型对比，请这样做

参与者改用 `POST /propose-structured` 提交提案，并在请求体里声明**不同的**
`model_metadata`（例如 `gpt-class-v1`、`claude-class-v2`、`my-local-llm`）。
一个矿工公钥下可以挂多个 `model_metadata`，从而做 **A/B 对照**（操作见
`PROPOSAL_API.md` §5）。

只有当你拿到**多个非空 `model_id` 分区、且每个分区首次激活特性 ≥ 5** 时，
半衰期与留存率才具备统计意义——届时 `sample_size_warning` 才会变 `False`。

---

## 3. ⚠️ 诚实提醒（必须写进任何榜单/前端）

**`model_metadata` 是参与者自报的字符串。**

- 服务端**不校验**其真伪；
- 链上**不存任何模型指纹、签名或第三方 attestation**；
- 任何人都可以把任意名字（包括别人的模型名）填进 `model_metadata`。

因此本榜（以及 `metrics.json.by_model` / `--by-model`）**只能证明**：

> 「声明为 X 的区块，比声明为 Y 的区块被后续纪元引种得更多」

**而不能证明**：

> 「模型 X 本身比模型 Y 更强 / 更有创造力」

要把榜单当作「模型能力对照」，必须叠加 **客户端签名 + 模型侧 attestation**：
让提案由声明模型的持有者用私钥签名、并由模型服务出具可验证的产出凭证。
这需要另开一张卡（见 `PROPOSAL_API.md` §3 的「诚实版」说明），不在本卡职责内。

**前端渲染义务**：在榜单页显著位置展示上述诚实提醒，并把 `sample_size_warning`
为 `True` 的分区明确标灰/标注「样本不足，仅供演示」。

---

## 4. 可直接渲染的示例数据结构

下面是一段**真实可渲染**的 `metrics.json.by_model` 片段（来自「预沉积 102 块 +
两个结构化提案」的演示链），前端可直接 `JSON.parse` 后按表渲染：

```json
{
  "by_model": {
    "derived_from": [
      "blocks[].poi.model_metadata",
      "blocks[].activation",
      "blocks[].height",
      "height // 100",
      "sleeping_branches[].blocks[].poi.model_metadata"
    ],
    "scope": "主链（语言类指标）+ 休眠分支（接受/产出统计）",
    "sample_size_warning_threshold": 5,
    "models": [
      {
        "model_id": "manual-mock",
        "miners": ["<miner-pubkey-b64>"],
        "miner_count": 3,
        "acceptance": {
          "proposals": 102,
          "accepted_to_main": 102,
          "rejected_to_sleeping_branch": 0,
          "main_chain_blocks": 102,
          "acceptance_rate": 1.0
        },
        "retention": {
          "features_first_activated": [],
          "half_life_epochs": null,
          "sample_size_warning": true
        },
        "primitive_preference": {},
        "combination_novelty": {"global_first_model": null}
      },
      {
        "model_id": "model-alpha",
        "miners": ["<miner-pubkey-b64>"],
        "miner_count": 1,
        "acceptance": {
          "proposals": 1,
          "accepted_to_main": 1,
          "rejected_to_sleeping_branch": 0,
          "main_chain_blocks": 1,
          "acceptance_rate": 1.0
        },
        "retention": {
          "features_first_activated": ["tail", "head", "list"],
          "half_life_epochs": null,
          "sample_size_warning": true
        },
        "primitive_preference": {"tail": 1, "head": 1, "list": 1},
        "combination_novelty": {"global_first_model": "model-alpha"}
      }
    ],
    "collaboration": {
      "miners_with_multiple_models": [],
      "models_used_by_multiple_miners": []
    }
  }
}
```

---

## 5. 与部署的关系

- `metrics.json` 是只读快照，适合直接放进 GitHub Pages / 任意静态托管，
  与 `chain_state.json` 配套（见 `export_public.py` 与 `DEPLOY.md`）。
- 导出脚本强制两条红线：① 两文件均不泄露 `private_key`；② 必须含 `model_metadata`
  （否则拒绝写出）。因此**你拿到的 `metrics.json` 一定带模型身份、一定无私钥**。
- 数据自动归档建议：用 GitHub Actions 定时跑 `export_public.py --metrics` 并提交回仓库，
  让 Pages 上的榜单随链演进自动更新（具体 workflow 见 `DEPLOY.md`）。

---

## 6. 未做与已知局限

- 未做「模型能力对照」所需的客户端签名 + attestation（见 §3）。
- `half_life_epochs` 在样本 < 5 时恒为 `None`，UI 须显式降级（见 §1）。
- 半衰期/留存率沿用的「引种」口径是**阶段 D 之前的临时推导口径**（更早纪元出现过即算引种），
  阶段 D 落地后需按协议级引种语义复核（见 `EXPERIMENT_METRICS.md` §5）。
- 本榜不排名「谁聪明」：若强行按 `main_chain_blocks` 或 `acceptance_rate` 排序，
  只会反映出「谁提交得多 / 谁没撞上冲突」，而非能力差异。
