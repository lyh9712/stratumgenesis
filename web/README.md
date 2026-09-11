# StratumGenesis v0.3 · 浏览器内核（Pyodide）部署与运行说明

让 `index.html` 在 **GitHub Pages / 任意静态托管** 上打开时，能直接在浏览器内跑真
Python（Pyodide 运行时），从而**无需后端**即可完成：查看链 → 提交提案 → 9 项校验 →
上链 → 跨纪元失忆/引种 → 存档导出/导入。

> 设计红线（卡 4/4 任务书）：`canonical_bytes()` 与 ECDSA 签名**只在 Python 侧执行**，
> 绝不在 JS 侧重写；序列化与签名结果哈希/签名完全一致，杜绝逐字节偏差。

---

## 1. 文件清单

| 文件 | 作用 |
| --- | --- |
| `web/pyodide_boot.js` | 引导：探测后端 → 加载 Pyodide（CDN→vendored 回退）→ 挂载模块 → 安装 ecdsa → 创建桥 |
| `web/bridge.js` | JS↔Python 桥：把调用转发给 Pyodide 内的 `web/py_sandbox` |
| `web/py_sandbox.py` | **真实链核心逻辑的浏览器入口**：复用 `block_model / chain_store / block_validator / crypto_key / novscript / persistence` 等，绝不直接 import `server.py` |
| `web/README.md` | 本文件 |
| `tests/test_pyodide_bridge.py` | 本机 Python 对桥等价入口的冒烟测试（浏览器无法用 unittest 驱动，故在本地等价验证） |

`index.html` 新增：三态运行模式探测、`#pyodide-tools` 存档工具条、调用桥的 write 路径。
**未改动**任何既有 id / class 的交互与动画。

---

## 2. 三态运行模式与降级顺序

打开 `index.html` 时按以下优先级探测，状态栏顶部显示当前模式：

1. **本机后端**（`/chain-state` 可达）→ 走原 `python server.py` 逻辑，Pyodide **不加载**。
2. **浏览器内核（Pyodide）**→ 后端不可达且 Pyodide + ecdsa 均就绪 → 页面内真实签名上链。
3. **只读展馆**→ 以上都失败（CDN 屏蔽 / WASM 失败 / ecdsa 不可用）→ 降级读静态
   `chain_state.json`，**不白屏、不静默失败**，并给出中文提示。

> 任何一步失败都**不会伪造验签结果**：ecdsa 不可用时直接降级只读，浏览器内核不会
> 用假签名写块。

---

## 3. 本地运行与验证

```bash
# 用非默认端口起静态服务（请勿占用 28417，那是另一条线/后端实例）
python -m http.server 28520
# 浏览器打开
#   http://127.0.0.1:28520/index.html
```

预期：状态栏显示「浏览器内核」，提交提案（如 `demo_code="(- 10 3)"`、`activation=["-"]`）
后新岩层出现，沙箱弹窗真实执行 `(- 10 3)` = 7。刷新页面链仍在（localStorage 持久化）。

本机 Python 入口冒烟测试（等价于浏览器内核入口验证）：

```bash
python -m unittest tests.test_pyodide_bridge -v
```

---

## 4. 离线 / vendored 部署（避免「没网就跑不了」）

Pyodide 运行时与 `ecdsa` 包默认从 CDN / PyPI 在线获取。要让项目**离线也能玩**，
需把二者 vendored 到仓库内（`web/vendor/`）。项目代码本身**不依赖网络**——
所有 Python 源文件由页面 `fetch` 自同源静态目录。

### 4.1 vendored Pyodide（约 12–13 MB）

在与 `pyodide_boot.js` 中 `VENDOR_BASE` 对应的目录放置**完整发行包**（`indexURL` 下文件必须齐全）：

```
web/vendor/pyodide/
├── pyodide.js            # 加载器（必须）
├── pyodide.asm.js        # 运行时胶水（must）
├── pyodide.asm.wasm      # 核心 WASM（~10 MB，必须）
├── python_stdlib.zip     # 标准库（必须）
└── pyodide-lock.json     # 包锁文件（必须，离线回退时避免无谓联网探测）
```

```bash
VER=0.26.4
mkdir -p web/vendor/pyodide
BASE="https://cdn.jsdelivr.net/pyodide/v${VER}/full"
curl -L "$BASE/pyodide.js"         -o web/vendor/pyodide/pyodide.js
curl -L "$BASE/pyodide.asm.js"     -o web/vendor/pyodide/pyodide.asm.js
curl -L "$BASE/pyodide.asm.wasm"   -o web/vendor/pyodide/pyodide.asm.wasm
curl -L "$BASE/python_stdlib.zip"  -o web/vendor/pyodide/python_stdlib.zip
curl -L "$BASE/pyodide-lock.json"  -o web/vendor/pyodide/pyodide-lock.json
```

> **MIME 提醒（自托管静态服务器）**：Pyodide 用动态 `import()` 加载
> `pyodide.asm.js`，并 `fetch` `.wasm`/`.zip`/`.json`。请确保静态服务器对这些扩展名返回
> 正确 MIME：`text/javascript`、`application/wasm`、`application/zip`、`application/json`。
> **GitHub Pages 默认即正确**；本地 `python -m http.server` 亦正确。若用其他服务器，
> 错误 MIME 会导致「Failed to fetch dynamically imported module」而降级只读。
> **切勿让本地请求走 HTTP 代理**（localhost 应直连），否则同源 vendored 资源会被代理拦截。

### 4.2 vendored ecdsa 依赖（仅需 six + ecdsa）

浏览器内核签名依赖 `ecdsa`，`ecdsa` 依赖 `six`。离线回退**不依赖 micropip/loadPackage**
（其 SRI 校验与离线自举会失败），而是把两个纯 Python wheel **直接解包**进 Pyodide 虚拟
`site-packages`：

```
web/vendor/wheels/
├── six.whl      # 稳定文件名（ecdsa 依赖，必须）
└── ecdsa.whl    # 稳定文件名（必须）
```

```bash
mkdir -p web/vendor/wheels
pip download six   -d web/vendor/wheels --no-deps --only-binary=:all:
pip download ecdsa -d web/vendor/wheels --no-deps --only-binary=:all:
cp web/vendor/wheels/six-*.whl   web/vendor/wheels/six.whl
cp web/vendor/wheels/ecdsa-*.whl web/vendor/wheels/ecdsa.whl
```

离线流程：`pyodide_boot.js` 的 `installEcdsa` 在线尝试失败后，按 `six → ecdsa` 顺序
`fetch` 两个 wheel 写入虚拟 FS 并 `zipfile` 解包到 `/stratum/site-packages`，再 `import ecdsa`
校验可用性；**任一缺失则如实抛出并降级只读，绝不伪造签名**。

> 注意：vendored 文件体积较大，**不计入 git 强制要求**，由部署者按 README 自行补齐；
> 缺失时仅影响「离线内核」，线上有网时仍走 CDN，不受影响。

---

## 5. 红线与签名说明

- **序列化/签名只在 Python 侧**：区块哈希基于 `Block.canonical_bytes()`，ECDSA 签名用
  `crypto_key.sign_block_payload`。JS 桥从不重建这两个函数，避免哈希/签名逐字节不符。
- **若未来改用 WebCrypto 做签名**：必须将 raw `r‖s` 正确转换为 DER 再写回
  `signature_bytes`（ecdsa 库输出即 DER，本项目直接用库，无需手动转换；如自实现须显式说明）。
- **导出存档不含私钥**：`py_export_archive()` 只输出 `blocks` + `sleeping_branches`
  （chain-v2 格式），**不含** `miners` 私钥字段；会话矿工密钥仅存于浏览器内存。
- **未改 FORMAT_VERSION / 未改 Block 字段 / 未改任何既有 API 契约**。

---

## 6. 实测指标（浏览器内实跑，headless Chrome）

| 指标 | 在线（CDN）内核 | 离线（vendored）内核 |
| --- | --- | --- |
| 内核就绪耗时（Pyodide 启动到 `kernel="pyodide"`） | ~31 s（首屏含 WASM 下载） | ~2.1 s（WASM 已本地） |
| Pyodide WASM 体积 | ~2.85 MB（按需） | ~10.1 MB（全量 `pyodide.asm.wasm`） |
| 首屏传输量（含模块挂载） | ~10.8 MB | ~12.4 MB |
| JS 堆内存占用 | ~24 MB | ~26 MB |
| 提案上链 | ✅ 102 → 103 | ✅ 102 → 103 |
| 沙箱真实执行 `(- 10 3)` | ✅ = 7 | ✅ = 7 |
| 导出存档含私钥 | ❌ 否 | ❌ 否 |

> 在线耗时主要是首次从 CDN 拉取 WASM/stdlib；离线因全量 vendored 已落地反而更快。
> 数值来自 Playwright + headless Chrome（Windows）DevTools 采集，硬件相关仅供参考。

---

## 7. 已知限制

- **`pyPromote`（休眠分支升级 / reorg）本版为留桩**：返回
  `status="not_implemented"`，前端给出「该能力待后续迭代」提示。提案上链、9 项校验、
  语言演化、跨纪元失忆/引种、存档导出/导入均完整可用。
- **首屏耗时 / WASM 体积 / 内存**：见下方「实测指标」一节（由浏览器 DevTools 采集）。
- **离线内核依赖 vendored**：未 vendored 且屏蔽 CDN 时自动降级只读展馆（符合红线）。
- **seed 链与线上 `chain_state.json` 哈希不同**：浏览器内核每次重新预沉积（用内存密钥
  签名），是独立的本地可玩实例；线上快照为只读展示用，二者不混用。

---

## 8. 与后端模式的一致性

浏览器内核复用**同一份** `block_validator.validate_block` 的 9 项校验流水线（签名 →
结构 → 内核 → PoI → 解析 → 特性激活 → 沙箱 → 语言正负测试 → UTXO），因此前端在
「本机后端」与「浏览器内核」两种模式下看到的校验语义完全一致。
