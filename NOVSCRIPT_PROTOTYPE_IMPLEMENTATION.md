# StratumGenesis NovScript 沙箱解释器原型

## 1. 简要实现说明

本目录实现 StratumGenesis 阶段二的 NovScript 纯计算解释器原型，严格采用独立的：

```text
源码 -> lexer -> Token -> parser -> AST -> evaluator -> EvalResult
```

实现没有使用 Python `eval`、`exec`，也没有把 NovScript 翻译成 Python 执行。

### 分层文件

| 文件 | 职责 |
|---|---|
| `novscript/errors.py` | 定义 LexError、ParseError、NameError、TypeError、ArityError、RecursionError、ResourceLimitError、SandboxError |
| `novscript/ast.py` | 定义 frozen AST 数据类：IntLiteral、Symbol、Lambda、Bind、Call、Program |
| `novscript/lexer.py` | 实现整数、标识符、括号、`+` 原语和 `;;` 注释的词法分析 |
| `novscript/parser.py` | 根据最小 BNF 构建 Program AST |
| `novscript/evaluator.py` | 实现环境、Closure、Builtin、Thunk 记忆化、惰性求值和资源计数 |
| `novscript/sandbox.py` | 定义 SandboxLimits、EvalResult、ValidationReport，提供 `run_sandbox`、`evaluate`、`validate_on_nodes` |
| `novscript/__init__.py` | 导出公共 API |
| `demo.py` | 单次沙箱运行与单机三节点模拟演示 |
| `tests/test_novscript.py` | S-01~S-12、F-01~F-18 全部回归测试 |

## 2. 已固定的规范歧义

工程规范允许原型对少数行为进行固定，本实现采用：

- 空程序 `""` 成功返回 `{"type": "InternalNil"}`；
- 顶层重复 `bind` 返回 `NameError`；
- `;;` 注释允许一直到文件末尾；
- `+` 作为创世内核原语被 lexer 识别为标识符；
- `(bind x x) x` 通过让 thunk 捕获包含自身绑定的环境，返回 `RecursionError`；
- 不支持的字符串字面量在词法阶段返回 `LexError`；
- 闭包结果只公开稳定摘要（类型和 arity），不泄露 Python 对象地址。

## 3. 运行结果

已执行：

```bash
python -m unittest discover -s tests -v
```

结果：30 个测试全部通过，包括全部 S-01~S-12 成功用例和 F-01~F-18 失败/边界用例。

已执行：

```bash
python demo.py
```

结果：

- 单次沙箱运行结果为 `42`；
- `node-a`、`node-b`、`node-c` 三个独立模拟节点均接受相同程序并返回 `42`；
- 该过程不包含 P2P 网络或真实分布式共识。

## 4. 原型暂未实现清单

以下功能明确不在本次实现内：

- P2P 网络、节点发现、广播、重传和真实多机节点；
- 区块哈希、签名、区块存储、分叉、投票和纪元逻辑；
- LLM 调用、提案生成、PoI 证明和标准 tokenizer；
- 纪元摘要、摘要投票和跨纪元引种；
- 字符串、列表、布尔值、`if`、循环、宏、模块系统和类型系统；
- 文件、网络、时间、随机数、进程、线程、协程和 FFI；
- 用户自定义扩展的动态加载；
- 生产级容器或虚拟机安全隔离；
- JIT、并行求值、增量编译和大规模性能优化；
- 可交易代币或任何金融功能。

## 5. 已知缺陷

这是教学级纯计算隔离，不是生产安全容器。资源限制中的堆对象计数是近似保护，不等于操作系统级内存隔离。当前测试覆盖有限，不能证明所有程序组合和未来语言扩展都没有语义冲突。

项目层面的已知局限也必须持续保留在代码注释和文档中：LLM 摘要会发生信息衰减并存在幻觉风险；摘要链仅线性低速增长；共识设计只适配小规模仿真网络；纯非金融激励存在参与者流失风险；沙箱仅为教学级纯计算隔离，不是生产安全容器。
