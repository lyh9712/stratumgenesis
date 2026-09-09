# StratumGenesis 最小可运行原型工程规范
## 模块：NovScript 沙箱解释器

- **项目**：StratumGenesis（地层创世实验）
- **文档版本**：Prototype Spec v0.1
- **适用范围**：单机原型、单进程模拟多个节点
- **推荐实现语言**：Python 3.11+
- **本模块状态**：工程设计规范，不等同于已完成实现

> 本模块只定义 NovScript 的最小可运行解释器与纯计算沙箱。原型不实现 P2P 网络，不连接外部 LLM，不执行文件、网络或宿主系统操作。单机模拟器可在同一进程内创建多个“节点验证器”，但这些验证器共享本地程序与运行环境，不等价于真实分布式网络。

---

## 1. 模块目标

### 1.1 最小目标

实现一个可被区块/共识原型调用的 NovScript 解释器，能够：

1. 解析创世内核规定的基础 S 表达式；
2. 支持整数、标识符、函数、函数调用和 `bind`；
3. 按 NovScript 规则执行惰性求值；
4. 维护不可变绑定和纯计算语义；
5. 在受限资源内运行 demo 与测试程序；
6. 返回确定性的成功值、错误类型和资源耗尽状态；
7. 允许单机测试代码分别创建多个独立解释器实例，模拟多个节点进行相同校验。

### 1.2 原型验收标准

满足以下条件才视为本模块原型可运行：

- 合法源代码可完成“词法分析 → 解析 → 求值”；
- 相同源代码、相同初始环境和相同资源限制得到相同结果；
- `bind` 不会在绑定创建时提前执行表达式；
- 解释器无法通过 NovScript 源代码访问宿主 Python 对象；
- 文件、网络、进程、环境变量、随机数和时间等外部能力不存在于语言环境；
- 解析错误、运行时错误和资源限制错误可以被调用方区分；
- 测试用例清单中的成功和失败用例均有自动化测试覆盖。

### 1.3 明确不属于本模块的目标

以下功能不在本次原型范围内：

- P2P 通信、节点发现、网络广播和真实共识；
- 区块存储、分叉管理、投票权重计算；
- LLM 调用、模型推理过程采集；
- 真实标准 tokenizer 的协议冻结；
- 字符串、列表、宏、类型系统、异常处理等后续扩展；
- JIT、并行求值、生产级性能优化；
- 把 Python 函数任意注入 NovScript 环境。

---

## 2. 输入输出接口定义

### 2.1 模块边界

建议将解释器拆分为以下组件：

```text
novscript/
├── lexer.py       # 源码 -> Token 序列
├── parser.py      # Token 序列 -> AST
├── ast.py         # AST 数据结构
├── evaluator.py   # AST -> Value，含 thunk/闭包
├── sandbox.py     # 资源限制与统一执行入口
├── errors.py      # 可区分的错误类型
└── tests/
```

解析器和求值器应尽量保持纯函数式接口；沙箱层负责执行步数、内存估算、输出长度等运行限制。

### 2.2 Python 调用接口

建议提供如下最小接口：

```python
from dataclasses import dataclass
from typing import Any, Mapping

@dataclass(frozen=True)
class SandboxLimits:
    max_steps: int = 100_000
    max_heap_objects: int = 10_000
    max_output_chars: int = 4_096

@dataclass(frozen=True)
class EvalResult:
    ok: bool
    value: Any | None = None
    error_type: str | None = None
    error_message: str | None = None
    steps: int = 0


def parse(source: str) -> "Program":
    """解析 NovScript 源码；失败时抛出 ParseError。"""


def evaluate(
    program: "Program",
    *,
    limits: SandboxLimits | None = None,
) -> EvalResult:
    """在无外部能力环境中求值，不接受宿主对象注入。"""


def run_sandbox(
    source: str,
    *,
    limits: SandboxLimits | None = None,
) -> EvalResult:
    """执行 parse + evaluate，统一返回可序列化结果。"""
```

### 2.3 输入接口

`run_sandbox` 的输入是 UTF-8 文本源代码。原型建议限制：

| 输入项 | 类型 | 原型约束 |
|---|---|---|
| `source` | `str` | 非空；建议最多 64 KiB；不得执行宿主语言代码 |
| `limits.max_steps` | `int` | 正整数；用于防止无限递归或无限循环 |
| `limits.max_heap_objects` | `int` | 正整数；用于限制闭包、环境和中间对象数量 |
| `limits.max_output_chars` | `int` | 正整数；本内核默认无输出原语，供未来扩展预留 |

### 2.4 输出接口

成功时：

```json
{
  "ok": true,
  "value": 3,
  "error_type": null,
  "error_message": null,
  "steps": 5
}
```

失败时：

```json
{
  "ok": false,
  "value": null,
  "error_type": "ParseError",
  "error_message": "unexpected token at line 1, column 8",
  "steps": 0
}
```

建议使用以下错误类型：

- `LexError`：非法字符、非法整数或未闭合注释等词法错误；
- `ParseError`：括号结构、表达式形态或参数列表错误；
- `NameError`：读取未绑定标识符；
- `TypeError`：将非函数作为函数调用，或内置整数运算收到错误类型；
- `ArityError`：函数参数数量不匹配；
- `RecursionError`：递归深度超出实现保护；
- `ResourceLimitError`：步骤、堆对象或输出限制超出；
- `SandboxError`：沙箱配置或隔离边界异常。

错误文本用于诊断，不应作为共识判断依据。单机多节点模拟时，各节点应比较结构化错误类型和稳定错误代码，而不是比较可能不同的自然语言描述。

### 2.5 多节点单机模拟接口

原型可提供一个简单的验证器封装：

```python
@dataclass(frozen=True)
class ValidationReport:
    node_id: str
    accepted: bool
    result: EvalResult
    interpreter_version: str


def validate_on_nodes(
    source: str,
    node_ids: list[str],
    *,
    limits: SandboxLimits | None = None,
) -> list[ValidationReport]:
    """为每个模拟节点创建独立解释器实例并执行相同源代码。"""
```

该接口只模拟“多个节点分别执行本地校验”，不得被描述为网络共识或拜占庭容错实现。

---

## 3. BNF 语法

以下 BNF 仅覆盖创世内核最小子集。空白字符可出现在 token 之间；注释从 `;;` 开始至行尾结束。

```bnf
<program>       ::= <expression>*

<expression>    ::= <integer>
                  | <identifier>
                  | <lambda>
                  | <bind>
                  | <application>

<lambda>        ::= "(" "lambda" "(" <identifier-list> ")" <expression> ")"

<bind>          ::= "(" "bind" <identifier> <expression> ")"

<application>   ::= "(" <expression> <expression>* ")"

<identifier-list> ::= <empty>
                    | <identifier> <identifier-list>

<integer>       ::= "-" <digit>+
                  | <digit>+

<identifier>    ::= <letter> <identifier-char>*

<identifier-char> ::= <letter>
                    | <digit>
                    | "-"
                    | "_"
                    | "?"
                    | "!"

<comment>       ::= ";;" <non-newline>* <newline>

<letter>        ::= "a" | ... | "z"
                  | "A" | ... | "Z"

<digit>         ::= "0" | "1" | ... | "9"
```

### 3.1 语法解释

- 一个 `<program>` 可以包含零个或多个顶层表达式；原型建议按顺序求值，返回最后一个表达式的值。
- `lambda` 的参数只能是标识符，不能直接使用复杂表达式。
- `bind` 创建不可变绑定；同一环境中重复绑定同名标识符应报错，而不是静默覆盖。
- 空列表、字符串、布尔值、引号语法、方括号和中缀运算符不属于本版本语法。
- 是否允许空程序、是否允许多个顶层表达式，应在测试中固定；本规范建议空程序返回 `nil` 内部值，但不把该值暴露为创世内核的第一类语言类型。

---

## 4. 求值语义（惰性求值）

### 4.1 值域

最小原型只定义以下值：

```text
Value ::= Integer
        | Closure(parameters, body, environment)
        | Builtin(name, implementation)
        | InternalNil
```

`InternalNil` 仅作为解释器内部的“无返回值/空程序”标记，不代表已经向语言增加了公开的空值类型。

### 4.2 环境与 thunk

环境是从标识符到绑定单元的不可变映射。绑定单元可为：

```text
Binding ::= Thunk(expression, environment, state=UNFORCED)
          | Value(value)
```

`Thunk` 保存表达式及其创建时环境。第一次读取标识符时，解释器强制求值 thunk，并将结果记忆化；以后再次读取使用同一结果。这种“按需计算 + 记忆化”策略可避免重复执行纯表达式。

原型必须检测 thunk 的循环强制，例如：

```novscript
(bind x x)
x
```

读取 `x` 时应返回稳定的循环绑定错误或资源错误，不得无限占用宿主线程。

### 4.3 基本求值规则

**整数**

```text
⟦n⟧ρ = n
```

整数求值结果为自身。

**标识符**

```text
⟦x⟧ρ = force(ρ[x])
```

如果 `x` 不在环境中，返回 `NameError`。

**lambda**

```text
⟦(lambda (x1 ... xn) body)⟧ρ
  = Closure([x1 ... xn], body, ρ)
```

创建闭包时不执行 `body`，并捕获定义位置的环境。

**bind**

```text
⟦(bind x expr)⟧ρ
  = ρ[x ↦ Thunk(expr, ρ)]
```

`bind` 不立即求值 `expr`。为了保持程序顺序可观察，顶层 `bind` 表达式返回内部 `InternalNil`；绑定后的值只有在后续表达式读取时才被强制。

**函数应用**

```text
⟦(f a1 ... an)⟧ρ
  = apply(force(⟦f⟧ρ), [Thunk(a1, ρ), ..., Thunk(an, ρ)])
```

函数位置必须先被强制求值；参数位置全部以 thunk 传入，不在调用点立即求值。

**闭包应用**

```text
apply(Closure([x1 ... xn], body, ρc), [t1 ... tn])
  = ⟦body⟧(ρc ∪ {x1 ↦ t1, ..., xn ↦ tn})
```

参数数量不匹配时报 `ArityError`。由于绑定不可变，参数名不能在同一调用环境中重复定义。

### 4.4 创世内核内置原语

为保持“纯函数、惰性求值、最小内核”的边界，原型只建议内置必要的整数加法：

```novscript
(+ 1 2)
```

`+` 是严格的内置函数：它会强制所有参数，确认参数均为整数后返回整数和。若参数不是整数，返回 `TypeError`；若参数数量不是 2，返回 `ArityError`。

是否把比较、条件分支、乘法、输出等能力加入后续扩展，不在本模块中预先实现。特别是 `print` 即使未来存在，也只能写入沙箱内存中的受限输出缓冲区，不能写宿主终端或文件。

### 4.5 惰性求值示例

```novscript
(bind unused (+ 100 200))
(bind result 7)
result
```

求值 `result` 时不应强制 `unused`。因此程序结果为 `7`，且执行步骤不应包含 `unused` 对应加法的求值步骤。

函数参数同样惰性：

```novscript
(bind constant
  (lambda (x) 42))

(constant (+ 1 2))
```

如果函数体不读取 `x`，则 `(+ 1 2)` 不应被求值，最终结果为 `42`。

---

## 5. 安全约束：纯计算沙箱

### 5.1 能力模型

NovScript 原型采用“默认无能力”模型。解释器环境只能包含明确列出的整数、闭包和受控内置原语，不允许把 Python 模块、对象、文件句柄、socket 或回调函数直接暴露给脚本。

### 5.2 明确禁止的能力

沙箱内禁止：

- 文件和目录读写；
- 网络连接、DNS、HTTP 和 socket；
- 创建子进程或调用 shell；
- 访问环境变量、命令行参数和宿主路径；
- 读取系统时间、随机数、设备信息或用户信息；
- Python `eval`、`exec`、反射和动态导入；
- 线程、协程、信号处理器和未受控的宿主回调；
- 任意异常对象或宿主对象向脚本泄露。

禁止项既适用于脚本源码，也适用于内置原语实现。原型不应仅依赖“脚本作者不写恶意代码”来保证安全。

### 5.3 资源限制

每次执行必须绑定独立的 `SandboxLimits`。至少实施：

1. **最大步骤数**：每次 AST 求值、函数应用、thunk 强制和内置调用消耗计数；达到上限立即终止。
2. **最大堆对象数**：限制闭包、环境、thunk 和解释器内部集合的创建数量。
3. **最大输入长度**：拒绝超出源代码上限的输入。
4. **最大输出长度**：为未来受控输出预留上限。
5. **递归保护**：对闭包调用深度设置上限，避免宿主 Python 栈溢出。

资源耗尽必须返回 `ResourceLimitError`，不得让宿主进程崩溃或无限等待。

### 5.4 确定性约束

为保证单机模拟节点结果一致：

- 不使用系统时间、随机数或外部状态；
- 整数运算采用明确的无溢出或溢出策略；原型建议使用 Python 任意精度整数，但仍受步骤和对象限制；
- 错误分类使用稳定代码；
- 结果序列化不得依赖 Python 对象地址；
- 解释器版本、语言规范版本和资源限制应作为测试上下文记录。

### 5.5 隔离声明

本模块的“沙箱”是面向纯计算语言的能力隔离层，不是对抗高权限宿主入侵的完整安全容器。若未来需要运行不可信第三方扩展，应在进程、操作系统容器或虚拟机层增加隔离，不能仅依赖本解释器的 AST 检查。

---

## 6. 测试用例清单

测试应至少分为词法、解析、语义、资源限制和多节点一致性五类。下面的源码示例均以本章语法为准。

### 6.1 成功用例

| 编号 | 类别 | 输入 | 预期 |
|---|---|---|---|
| S-01 | 整数 | `42` | `ok=true`, value=`42` |
| S-02 | 负整数 | `-7` | value=`-7` |
| S-03 | 加法 | `(+ 1 2)` | value=`3` |
| S-04 | 绑定读取 | `(bind x 9) x` | value=`9` |
| S-05 | 惰性绑定 | `(bind x (+ 1 2)) 4` | value=`4`；不强制 `x` |
| S-06 | 闭包创建 | `(lambda (x) x)` | 返回 `Closure` |
| S-07 | 闭包调用 | `((lambda (x) x) 8)` | value=`8` |
| S-08 | 惰性参数 | `((lambda (x) 42) (+ 1 2))` | value=`42`；参数不被强制 |
| S-09 | 闭包捕获 | `(bind a 5) ((lambda (x) (+ x a)) 3)` | value=`8` |
| S-10 | 多顶层表达式 | `(bind a 1) (bind b 2) (+ a b)` | value=`3` |
| S-11 | 注释 | `;; comment\n(+ 2 3)` | value=`5` |
| S-12 | 多节点 | 同一源码在 3 个独立节点实例运行 | 三份结构化结果一致 |

### 6.2 边界与失败用例

| 编号 | 类别 | 输入 | 预期错误 |
|---|---|---|---|
| F-01 | 空输入 | 空字符串 | 按实现约定返回 `InternalNil` 或 `ParseError`，必须固定且测试锁定 |
| F-02 | 括号不匹配 | `(+ 1 2` | `ParseError` |
| F-03 | 多余右括号 | `(+ 1 2))` | `ParseError` |
| F-04 | 非法字符 | `(+ 1 @)` | `LexError` |
| F-05 | 未绑定名称 | `missing-name` | `NameError` |
| F-06 | 重复绑定 | `(bind x 1) (bind x 2)` | `NameError` 或专用 `DuplicateBindingError`；实现必须统一 |
| F-07 | 非函数调用 | `(1 2)` | `TypeError` |
| F-08 | 加法参数不足 | `(+ 1)` | `ArityError` |
| F-09 | 加法参数过多 | `(+ 1 2 3)` | `ArityError` |
| F-10 | 加法类型错误 | `(+ 1 (lambda (x) x))` | `TypeError` |
| F-11 | 参数数量不足 | `((lambda (x y) x) 1)` | `ArityError` |
| F-12 | 参数数量过多 | `((lambda (x) x) 1 2)` | `ArityError` |
| F-13 | 循环 thunk | `(bind x x) x` | 循环绑定错误或 `ResourceLimitError`，不得挂死 |
| F-14 | 无限递归 | `((lambda (x) (x x)) (lambda (x) (x x)))` | `ResourceLimitError` 或 `RecursionError` |
| F-15 | 超长输入 | 超出 `max_source_chars` 的源码 | `ResourceLimitError` 或输入校验错误 |
| F-16 | 外部能力伪造 | `(__import__ "os")` | `NameError` 或 `ParseError`，不得执行导入 |
| F-17 | 不闭合注释/字符串 | 含未定义或未闭合词法结构 | `LexError` |
| F-18 | 节点差异 | 同源码在不同节点使用不同宿主环境 | 结果仍一致；若不一致则测试失败 |

### 6.3 测试实施要求

- 每个成功用例验证返回值类型和值；
- 每个失败用例验证稳定错误类型，不只验证错误字符串；
- 对惰性用例增加“未被读取绑定未执行”的观测计数，但观测计数只能由测试夹具提供，不能通过 IO；
- 对资源限制用例设置较小上限，确保测试运行快速；
- 使用属性测试或模糊测试生成括号、整数和标识符输入，重点验证解释器不崩溃；
- 多节点测试必须使用独立环境实例，避免共享可变状态掩盖问题。

---

## 7. 实现建议（推荐 Python）

### 7.1 推荐技术路线

推荐使用 Python 3.11+，先实现一个清晰、可审计的树遍历解释器，不使用 Python `eval` 或 `exec`。建议顺序：

1. 定义不可变 AST 数据类；
2. 实现字符级 lexer，保留行号和列号；
3. 实现递归下降或栈式 S 表达式 parser；
4. 实现 `Environment`、`Thunk`、`Closure` 和 `Builtin`；
5. 在 evaluator 中统一注入步骤计数器和对象计数器；
6. 用 `run_sandbox` 统一捕获、分类和序列化错误；
7. 为每个模拟节点创建独立解释器状态；
8. 最后再接入区块候选校验器。

### 7.2 数据结构建议

```python
@dataclass(frozen=True)
class IntLiteral:
    value: int

@dataclass(frozen=True)
class Symbol:
    name: str

@dataclass(frozen=True)
class Lambda:
    params: tuple[str, ...]
    body: "Expr"

@dataclass(frozen=True)
class Bind:
    name: str
    expr: "Expr"

@dataclass(frozen=True)
class Call:
    function: "Expr"
    arguments: tuple["Expr", ...]
```

环境更新建议返回新环境或使用明确的不可变绑定单元。若为了性能使用内部可变缓存，只允许修改 thunk 的“是否已求值”和缓存值，不得修改语言层绑定含义。

### 7.3 不建议的实现方式

- 不要把 NovScript 翻译为 Python 源码后执行；
- 不要用 `eval`、`exec` 或 `ast` 直接作为安全边界；
- 不要把任意 Python callable 注入语言环境；
- 不要用线程超时作为唯一的死循环防护；
- 不要把宿主异常堆栈直接返回给脚本或网络调用方；
- 不要为方便而预置字符串、列表、文件、网络等未定义特性。

### 7.4 与后续区块模块的接口预留

解释器应允许调用方指定一个“活跃语言规范快照”或扩展注册表，但本版本只接受内核特性。未来加载区块扩展时，每个扩展必须显式提供：

```python
@dataclass(frozen=True)
class LanguageExtension:
    feature_id: str
    source_block_id: str
    parser_version: str
    evaluator_version: str
    deterministic: bool
```

该结构只是扩展点，不表示本原型已经支持动态扩展。任何扩展接入前都必须补充规范、兼容性检查和沙箱测试。

---

## 8. 已知缺陷与原型阶段暂不实现的功能

### 8.1 已知缺陷

1. **语义覆盖有限**：测试用例只能覆盖有限程序，无法证明扩展组合的全面正确性。
2. **资源计量是近似的**：Python 对象数量不等同于真实内存占用，`max_heap_objects` 只能作为原型保护措施。
3. **宿主隔离不充分**：同进程解释器不是高强度安全边界，不能直接承载敌意代码或多租户生产服务。
4. **错误位置可能不完整**：复杂嵌套表达式的运行时错误需要额外保存调用位置，原型初版可能只能返回最近 AST 节点位置。
5. **惰性求值实现复杂**：循环 thunk、递归闭包、错误传播和缓存时机需要通过更多测试锁定。
6. **整数策略尚未协议化**：Python 任意精度整数虽然便于原型，但跨实现的整数上限和资源成本仍需后续冻结。
7. **无持久化快照**：本模块不负责保存解释器环境或历史语言规范快照，进程退出后状态默认丢失。

### 8.2 原型阶段暂不实现

- P2P 网络、节点发现、广播和网络重传；
- 真实多机节点、拜占庭节点和网络分区模拟；
- 区块哈希、签名、分叉和投票确认；
- LLM 提案生成与标准 token 计数；
- 纪元摘要、摘要投票和跨纪元引种；
- 列表、字符串、布尔值、条件表达式、宏和模块系统；
- 用户自定义宏、反射、动态加载和 FFI；
- 文件、网络、时间、随机数、进程和并行计算；
- 生产级容器/虚拟机隔离；
- 性能基准、JIT、增量编译和大规模程序优化。

### 8.3 与全局项目背景的关系

本模块实现的是 StratumGenesis 的“语言执行地基”，不是完整链系统。它只为后续区块校验提供可重复的纯计算执行器：后续模块可以调用它验证提案中的 demo 和测试，但不得据此推断已经实现分布式共识、完整 PoI 或可交易经济系统。

---

## 附录 A：最小端到端示例

```python
source = """
(bind add-one (lambda (x) (+ x 1)))
(add-one 41)
"""

result = run_sandbox(
    source,
    limits=SandboxLimits(
        max_steps=1_000,
        max_heap_objects=100,
        max_output_chars=1_000,
    ),
)

assert result.ok is True
assert result.value == 42
```

该示例只验证单机解释器行为。它不代表区块已生成、提案已通过 PoI、节点已达成共识或任何链内凭证已产生。
