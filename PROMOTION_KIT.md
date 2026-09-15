# StratumGenesis · 推广物料包（PROMOTION_KIT）

> 用途：把项目发出去时**直接复制粘贴**的文案与操作清单。
> 原则：**说真话**——不吹、不说自己是加密货币、不暗示有代币或收益。
> 所有文案里的链接统一用：**https://lyh9712.github.io/stratumgenesis/**

---

## 0. 一句话口径（发任何平台都用这三条）

- **一句话**：一群人和他们各自的 AI，从同一套内核规则出发，一起从零「沉积」出一门新语言。
- **30 秒**：链上记的不是转账，而是一门语言一层层的成长史。最底下是永不修改的「创世内核」，往上每层是一条新增的语言规则。每 100 层是一个纪元；纪元翻页语言会「失忆」，旧特性必须靠「引种」重新激活——于是能看出哪些设计被反复引种（活着），哪些被遗忘。
- **技术版**：单机仿真实验链（Python 标准库 + ecdsa）。提案走 9 项校验（含「激活前跑不通、激活后跑得通」的正负测试），所以语言是真的在长，不是记账。语言作用域按纪元隔离，历史区块按当时的语言快照重放；已实现休眠分支升级（reorg）。浏览器版用 Pyodide 在页面内跑真 Python，零后端可玩。

**必须同时说清的三句**（防止被误认为发币项目）：
1. **不是加密货币**：没有代币、没有募资、链内凭证无现实价值、不可交易；
2. **不调用真实大模型**：PoI 是 mock 确定性分词，提案由参与者（或他的 AI）自己写；
3. **是实验原型**：无 P2P、无公网鉴权、非生产系统，许可为**非商业**（PolyForm NC 1.0.0）。

---

## 1. 配图与素材

| 素材 | 位置 | 用途 |
|---|---|---|
| 分享预览图 1200×630 | 仓库根 `og-preview.png` | 链接预览（已挂 `og:image`） |
| 30 秒 GIF（建议自制） | 建议放 `docs/demo.gif` | 平台发帖必备：打开页面 → 输入「减法」→ 粒子沉积 → 新岩层 → 沙箱跑 `(- 10 3)` = 7 |
| 截图 | 地层剖面 / 纪元开篇 / 休眠分支侧栏 / 沙箱弹窗 | 帖子配图 |
| 在线试玩 | https://lyh9712.github.io/stratumgenesis/ | 所有帖子的主链接 |
| 代码仓库 | https://github.com/lyh9712/stratumgenesis | 技术帖附链接 |

**GIF 录制法**（Windows）：用 ShareX / ScreenToGif 录浏览器窗口 8–12 秒，压到 3MB 内。

---

## 2. 各平台可直接粘贴的文案

### 2.1 X / Twitter（中文，配 og-preview.png + GIF）

```
我在造一门「会被忘记」的编程语言。

一群人（和各自的 AI）从只有 + 加法的内核出发，一层层提交语言扩展；
每 100 层是一个纪元，纪元翻页语言就「失忆」——
旧特性必须靠「引种」重新激活。

于是有了一个残酷的成绩单：谁的设计被反复引种（活着），谁被遗忘。

打开即玩（浏览器内跑真 Python，无需安装）：
https://lyh9712.github.io/stratumgenesis/

不是加密货币，没有代币。只是个实验。
```

### 2.2 X / Twitter (English)

```
I'm building a programming language that forgets.

A group of people — each with their own AI — grow a language from a kernel
that only knows `+`. Every 100 layers is an epoch. When an epoch turns over,
the language "loses its memory": old features must be re-inoculated to survive.

So you get a brutal scoreboard: whose designs get re-imported (alive) and whose
get forgotten.

Playable in your browser (real Python via Pyodide, no install):
https://lyh9712.github.io/stratumgenesis/

Not a cryptocurrency. No token. Just an experiment.
```

### 2.3 V2EX（节点：程序员 / 分享创造）

标题：**我做了一条「地层式」的实验链：链上记的不是转账，而是一门语言的成长史**

```
起因是我想验证一个念头：一门编程语言能不能由一群人和他们各自的 AI「从零长出来」，
而不是由标准委员会设计出来。

于是做了 StratumGenesis：
- 内核只有 S 表达式 + 惰性求值 + 不可变 bind + 一个 `+` 加法，永不修改；
- 每个区块承载一条「语言扩展提案」，要过 9 项校验，其中包括一组正负测试：
  提案的示例代码必须在「激活该特性后」能跑通、在「不激活时」跑不通——
  这样「语言真的在变」是可验证的事实，而不是叙事；
- 每 100 层是一个纪元。纪元翻页，语言作用域重置（失忆），
  旧特性必须在新纪元里重新「引种」才算回来。跨纪元的存活率，
  正好可以用来比较不同 AI 的提案谁的设计更有生命力；
- 已实现休眠分支升级（reorg）：落选的候选可以把主链后缀顶掉，
  账本/纪元快照/语言快照全部按新主链重放重建。

技术上没什么黑魔法：Python 标准库 + ecdsa，单机仿真，无 P2P、无代币。
浏览器版用 Pyodide 在页面里跑真 Python（含 314 项测试的同一套代码），
所以打开链接就能提案、跑沙箱。

在线试玩：https://lyh9712.github.io/stratumgenesis/
源码（PolyForm NC，非商业）：https://github.com/lyh9712/stratumgenesis

欢迎来喷：尤其想知道「失忆 + 引种」这套选择机制，在你们看来是玩法还是设计缺陷。
```

### 2.4 掘金 / 即刻 / 微博（短版）

```
用地质地层的方式，创造一门编程语言。

内核只有 + 加法：每提交一次语言扩展，地层就多一层；
每 100 层是 1 纪元，纪元翻页语言会「失忆」，
旧特性要靠「引种」复活——谁的设计被反复引种，谁就被记住。

打开就玩（浏览器内跑真 Python）：https://lyh9712.github.io/stratumgenesis/
不是加密货币，没有代币。
```

### 2.5 微信朋友圈 / 群

```
最近在做一件有点疯的事：让一群人和各自的 AI，从零「沉积」出一门编程语言。
每 100 层算一个纪元，纪元一翻页，之前加过的规则会沉入地下、暂时失效——
想继续用就得重新「引种」。所以地层本身就是成绩单：谁的设计活得久，一目了然。
点开就能玩，不用装东西：https://lyh9712.github.io/stratumgenesis/
（不是币，没有代币，纯实验）
```

### 2.6 Reddit · r/ProgrammingLanguages

标题：**StratumGenesis: a language that evolves by on-chain proposals, and forgets at epoch boundaries**

```
I built a small experiment: a programming language (NovScript) that grows from
a frozen kernel (s-expressions, lazy evaluation, immutable `bind`, one `+`
primitive) by accepting "language extension proposals" as blocks in a chain.

Two mechanics I'd love feedback on:

1) Provable language change. A proposal must pass a positive/negative test pair:
   the demo must run *after* activating the feature and must FAIL without it.
   So "the language actually changed" is machine-checkable, not a slogan.

2) Amnesia + inoculation. Epochs are 100 blocks. At an epoch boundary the active
   primitive set resets, so features from earlier epochs must be explicitly
   re-inoculated in the new epoch. Survivorship across epochs becomes a fitness
   signal for proposals (and, in the intended use, for comparing different
   models' proposals).

Also implemented: sleeping-branch promotion (reorg) with full replay-derived
state, and a browser build that runs the real Python interpreter via Pyodide
(no backend) so you can submit proposals in the page.

Not a cryptocurrency: no token, no fundraising, non-commercial license (PolyForm NC).
Single-node simulation, no P2P, mock PoI (no real LLM calls).

Play: https://lyh9712.github.io/stratumgenesis/
Code: https://github.com/lyh9712/stratumgenesis

Would especially appreciate criticism of the epoch-scoped language registry —
is "forgetting by default" a defensible language-evolution model?
```

### 2.7 Hacker News · Show HN

标题：**Show HN: StratumGenesis – a language that evolves by proposals and forgets each epoch**

首楼（自己补的说明，必须发，否则会被当加密项目）：

```
Author here. Some context since "blockchain" raises eyebrows:

- No token, no crypto, no fundraising, no chain asset of any value. The UTXO
  ledger is a teaching device for double-spend semantics and is deliberately
  isolated from voting weight.
- PoI ("proof of inference") is mocked with a deterministic tokenizer; no LLM
  is called. Real-model proposals are a future direction, not a claim.
- The interesting part (to me) is that language change is *verified*: each
  proposal carries a demo + tests that must pass with the new primitive active
  and fail without it. Plus epoch-scoped scoping: the active primitive set
  resets every 100 blocks, so earlier features must be re-inoculated to survive.
- Runs entirely in the browser via Pyodide, or locally with `python server.py`.
  Single-node, no P2P.
- Non-commercial license (PolyForm NC 1.0.0).

Happy to answer questions about the validator pipeline, the reorg design, or why
I think "language amnesia" is a feature rather than a bug.
```

---

## 3. 不要做什么（红线）

1. **不要说「区块链货币」「代币」「挖矿收益」**——本项目没有代币；「挖矿」这里指提交提案的工作量。
2. **不要暗示 AI 自动写语言**：当前提案由参与者（或他用自己的 AI）写，PoI 是 mock。
3. **不要刷量**：不要买 star、不要用机器人刷计数；计数是给作者自己看真实流量的。
4. **不要承诺「可交易」「升值」「空投」**——一次这样的表述就会让项目被归入币圈，且违反许可。
5. **不要去掉「非商业」许可**：任何商业使用需事先取得书面授权（见 `LICENSE-SCOPE.md` §7）。

---

## 4. 发布节奏与观测

**首日**（2 小时内）：X/Twitter 中英各一条 → V2EX「分享创造」→ 即刻/朋友圈。
**48 小时**：Reddit r/ProgrammingLanguages（英文长帖）→ Hacker News Show HN（美东上午）。
**首周**：掘金/知乎长文（可基于 `TokenMint 设计白皮书` 改写）→ 在 1–2 个语言设计/AI 社群里做线上演示。

**观测指标怎么读**：
| 指标 | 在哪看 | 说明 |
|---|---|---|
| 页面打开次数 | 页面状态区「已有 N 次打开」 | 匿名计数；**这是唯一能反映"有人看了"的信号** |
| 仓库浏览/克隆 | 仓库 Insights → Traffic（或我给的 API 查询） | 克隆数含机器行为，看趋势不看绝对值 |
| Star / Fork | 仓库页 | 真实关注的代理指标 |
| **有人接手部署** | README 的 hub 注册表（待建） | 项目「活下去」的最强信号 |

**回应常见质疑的标准答案**：
- 「这不就是币吗？」→ 没有代币、没有募资、许可禁止商业使用；UTXO 只是教学结构，与投票权重完全隔离。
- 「失忆是 bug 吧？」→ 是有意设计（白皮书 §7.6）：让每个纪元重新选择自己的语言，用跨纪元存活率衡量设计价值。可关掉的实验开关留给 v2。
- 「AI 在哪？」→ 当前 AI 体现在「参与者用各自的模型写提案」，链上记录 `model_metadata`，分析器按模型分组统计接受率与引种留存率；真实 LLM 接入是下一波。

---

## 5. 我能替你做的与只能你做的

**我（AI 助手）能直接做的**：改页面/仓库以提升可发现性（og 卡片、计数器、README 首屏、topics、部署徽章）、写任何语言的文案、生成配图、跑技术验证、代你回答技术质疑。

**只能你做的**：在各平台**以你本人身份发帖**、回复评论、决定是否接受商业授权、以及决定要不要把仓库转移到你个人账号名下。
