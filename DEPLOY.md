# StratumGenesis v0.3 · 部署与分发指南

> 面向「想替全世界开一个 hub 的人」和「只想零服务器看一眼的人」。
> 本文件由 **线④（DevOps + 前端）** 编写，只新增部署物，不改动任何业务代码。
> 目标：别人能在 **10 分钟** 内跑起来；不联网、不收费也能看到东西。

---

## 0. 先读这一节：这是什么、不是什么

| 项 | 说明 |
|---|---|
| 项目性质 | **单机仿真原型**，`server.py` 用标准库 `http.server` 起的一个进程内演示链 |
| 网络 | **无 P2P、无节点发现**。两个 hub 之间不互通，只能靠导出/导入链文件交换数据 |
| 资产 | **无代币、无真实资产**。UTXO 只是实验记账，白皮书明确声明不具现实货币价值 |
| 共识 | 单进程串行处理，仅适配小规模仿真 |
| 身份 | **无鉴权**，且服务端 `MinerRegistry` 持有全部矿工私钥并代为签名 |
| 存储 | 实验级 JSON 存档，**明文保存矿工私钥**，无加密、无备份保障 |
| 许可 | **PolyForm Noncommercial 1.0.0（非商业）** —— 见 `LICENSE`，**禁止商业使用/商业部署** |
| 依赖 | 仅 `ecdsa==0.19.2`（Apache-2.0），见 `requirements.txt`；其余全为标准库 |

**因此：本指南适用于「公开只读演示」与「小范围熟人 hub」，不适用于任何生产、金融或承载真实身份的场景；
在 Noncommercial 许可下，也不得用于任何商业目的（含商业托管、收费服务、商业宣传）。**

### 三条硬红线

1. **绝不发布 `data/` 目录。** 其中的存档含 `miners[].private_key_b64` 明文私钥。
   公开链数据可以（`chain_state.json`），公开私钥等于泄露。
   （`data/` 已被 `.gitignore` 排除，但仍不要手工提交或挂到公网目录。）
2. **保留 `LICENSE` / `NOTICE` / 免责声明**，并在站点显著位置标注「**非官方部署**」。
   本仓库许可为 **PolyForm Noncommercial 1.0.0**，部署者必须同时遵守其条款
   （禁止商用；`LICENSE` 的版权所有人已定稿（鹿拾 / Yuanhao Lu））。
3. **不要绑定作者个人资源** —— 不要拿作者的域名、服务器、账号、API key 去部署。

---

## 1. 四种上线方式，按作者负担从低到高

| 方式 | 成本 | 能提案吗 | 数据持久化 | 适合谁 |
|---|---|---|---|---|
| **A. GitHub Pages 静态展馆** | 零 | ❌ 只读浏览 | 仓库里的快照文件 | 只想「看到」的人 |
| **B. Docker 本地/自建服务器** | 一台机器 | ✅ | 挂卷即可 | 有闲置机器/VPS 的人 |
| **C. Render / Fly 免费层** | 零（会休眠） | ✅ | ❌ 需配合 §8 归档 | 想一键开 hub 的人 |
| **D. PythonAnywhere** | 零（有额度） | ⚠️ 见 §6 | ✅ 有家目录 | 习惯 PythonAnywhere 的人 |

---

## 2. ⚠️ 绑定地址：127.0.0.1 的问题与四种做法

**事实**：`server.py` 里 `HOST = "127.0.0.1"` 是硬编码的，`create_server()` 直接用它绑定。
`server.py` 是 **线①的独占文件**，线④ **不修改它**。

**后果**：

- 直接 `python server.py` → 只有**本机**能访问；
- 容器里跑 → 只有**容器内部**能访问，`EXPOSE 28417` / `-p 28417:28417` **都不生效**；
- Render / Fly / 任何云平台 → 平台要求监听 `0.0.0.0:$PORT`，否则**健康检查必失败**。

### 做法 A（推荐，但需线①放行）：让监听地址可配置

最干净的一行改动，属于 `server.py` 的所有权范围，**本线不擅自实施**：

```python
# server.py（建议补丁，待线①确认）
import os
HOST = os.environ.get("STRATUM_HOST", "127.0.0.1")
PORT = int(os.environ.get("STRATUM_PORT", "28417"))
```

风险：**默认行为不变**（仍只听环回），只有显式设 `STRATUM_HOST=0.0.0.0` 才对外。
一旦对外，§7 的所有风险同时生效。

### 做法 B：容器内 socat 转发（不动 server.py）

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends socat
CMD sh -c "socat TCP4-LISTEN:28417,bind=0.0.0.0,fork,reuseaddr TCP4:127.0.0.1:28417 & exec python server.py"
```

`render.yaml` 用的就是这招。风险：多一个进程、多一层转发；socat 只做明文转发，
TLS 由平台终止，不要把它直接暴露在不可信网络里。

### 做法 C：纯 Python 转发器（无 socat、无 apt）

当构建环境不允许装包时使用，仅标准库：

```sh
python - <<'PY' &
import socket, threading, os
p = int(os.environ.get("PORT", "28417"))
def pipe(a, b):
    try:
        while True:
            d = a.recv(65536)
            if not d: break
            b.sendall(d)
    except Exception: pass
    finally:
        try: b.close()
        except Exception: pass
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("0.0.0.0", p)); s.listen(64)
while True:
    c, _ = s.accept()
    u = socket.create_connection(("127.0.0.1", 28417))
    threading.Thread(target=pipe, args=(c, u), daemon=True).start()
    threading.Thread(target=pipe, args=(u, c), daemon=True).start()
PY
exec python server.py
```

### 做法 D：平台反向代理 / 隧道

Fly.io 可在 `fly.toml` 里让 `internal_port = 28417` 配合 `[[services]]` 转发；
或在机器本地跑 `cloudflared tunnel`、`ngrok` 之类。**注意：这意味着把无鉴权服务暴露到公网，先读完 §7。**

> #### ⚠️ STRATUM_HOST 风险（由另一条线提供，大总管转交，原文照录）
>
> STRATUM_HOST：不要轻易改绑。server.py 默认只监听 127.0.0.1，这是它唯一的安全边界。
> 设 STRATUM_HOST=0.0.0.0 会让服务对所有网络接口开放，而该服务服务端持有全部矿工私钥并代为签名、
> 没有任何鉴权与限频——任何能访问到端口的人都可以冒充任意矿工出块、提交任意提案。
> 仅建议在以下前提下改绑：① 部署在可信内网或容器网络内；② 外层有反向代理做访问控制与限流；
> ③ 明确是只读/演示用途。风险由部署者自负。

---

## 3. Docker：本地或 VPS 自建

```bash
# 构建（仓库根目录下）
docker build -t stratumgenesis:0.3 .

# 运行（挂卷持久化链数据）
docker run -d --name stratum -p 28417:28417 -v stratum-data:/app/data stratumgenesis:0.3
```

| 参数 | 说明 |
|---|---|
| `-p 28417:28417` | **只有在按 §2 做了转发后才有效**，否则端口映射无效 |
| `-v stratum-data:/app/data` | 持久化 `chain_v1.json`；不挂则容器销毁即丢 |
| `--restart unless-stopped` | 建议加上，免费层/个人机器重启后自动拉起 |

排错：

```bash
docker logs stratum            # 看启动日志（存档加载失败会有中文提示）
docker exec stratum ls -l /app/data
```

**已知取舍**：镜像内 `RUN rm -rf /app/data && mkdir -p /app/data` ——
因为本地工作目录里的 `data/chain_v1.json` 是 **chain-v1 旧格式**且含私钥，
若被 `COPY . .` 带进来会让服务因版本不匹配直接退出。干净 git 检出不受影响
（`data/` 已被 `.gitignore` 排除）。

> ⚠️ **本线环境无 Docker，`Dockerfile` 未经真机构建验证**（仅有语法与逻辑审查）。
> 首次构建如有问题，请按上面的排错命令看日志，并把报错回传给大总管。
>
> 建议补一个 `.dockerignore`（本线未创建，属新增文件）：
> `__pycache__/`、`*.pyc`、`data/`、`.git/`、`.codebuddy/`、`.workbuddy/`、`server.log`、`tests/`。

---

## 4. Render（一键蓝图）

1. Fork 本仓库；
2. Render Dashboard → **New → Blueprint** → 选你的 fork（会自动读 `render.yaml`）；
3. 触发首次部署，等 Build 结束；
4. 打开 `https://<服务名>.onrender.com`。

**注意**：

- 免费层 **会冷启动休眠**，首次访问可能等 30–60 秒；
- 免费层 **无持久化磁盘**，实例重启后链回到初始演示链 → 务必配合 §8 归档；
- 蓝图里的 `socat` 方案**未经真机验证**（见 `render.yaml` 顶部注释）；
  若构建阶段 `apt-get` 失败，改用 §2-C 的纯 Python 转发器替换 `startCommand`。

---

## 5. Fly.io

```bash
fly auth login
fly launch --no-deploy          # 生成 fly.toml
```

编辑 `fly.toml`，关键是让外部端口转发到容器内的 `28417`：

```toml
[build]

[env]
  PYTHONUNBUFFERED = "1"

[[services]]
  protocol = "tcp"
  internal_port = 28417
  auto_stop_machines = true      # 无访问时休眠，省额度
  auto_start_machines = true
  min_machines_running = 0

  [[services.ports]]
    port = 80
    handlers = ["http"]

  [[services.ports]]
    port = 443
    handlers = ["tls", "http"]

[[mounts]]
  source = "stratum_data"
  destination = "/app/data"      # 持久化链数据
```

```bash
fly volumes create stratum_data --size 1
fly deploy
```

风险同 §2：容器内仍是 `127.0.0.1`，`internal_port` 的转发由 Fly 的边车完成。

---

## 6. PythonAnywhere

1. 注册免费账号 → **Web** → **Add a new web app** → Manual configuration → Python 3.12；
2. **Files** 里上传仓库，或 `$ git clone <你的 fork>`；
3. Web 页 **Source code** 填 `/home/<用户名>/tokenmint`，**Working directory** 同上；
4. **Virtualenv** 填 `/home/<用户名>/.virtualenvs/stratum`，先 `$ pip install ecdsa`；
5. WSGI 配置文件内容（PythonAnywhere 必须走 WSGI，**不能直接跑 `python server.py`**）：

```python
# /var/www/<用户名>_pythonanywhere_com_wsgi.py
import sys, os
sys.path.insert(0, "/home/<用户名>/tokenmint")
os.chdir("/home/<用户名>/tokenmint")

# server.py 是标准库 http.server 实现，不是 WSGI 应用。
# 免费账号也不允许长期监听端口。这里给出两条路：
#   路径 1（可写）：用 wsgiref 把 WSGI 请求转接到后端 —— 需要额外代码，本线未提供；
#   路径 2（推荐）：PythonAnywhere 免费账号【不允许】长期运行自定义监听服务，
#                  请改用 Docker(§3) / Render(§4) / Fly(§5)；
#                  付费账号可在 Consoles 里跑 `python server.py` 并用 Always-on task 保活。
from wsgiref.simple_server import ...
```

> ⚠️ **诚实说明**：PythonAnywhere 免费层**不支持**以 `http.server` 方式长期监听端口，
> 且本线**未提供** WSGI 适配层（那属于改动运行时行为，超出线④授权范围）。
> 免费用户请走 §3/§4/§5；付费用户可用 "Always-on task" 跑 `python server.py`。

---

## 7. 部署者须知（安全与合规）

### 7.1 服务端持私钥 = 公网可冒充

`server.py` 的 `MinerRegistry` 保存 **全部矿工的私钥**，`/propose` 由服务端代签。
任何人只要知道 `miner_pubkey_b64`（`/chain-state` 里公开返回），
就能**冒充任意矿工身份**提交提案。

建议（按优先级）：

1. **只在只读/演示模式开放**（Pages 静态展馆最安全，见 §9）；
2. 若要开放写入，等上游把**签名移到客户端**（WebCrypto / Pyodide 内生成密钥，服务端只验签）；
3. 至少加一层**来源限制**（仅内网 / VPN / 反向代理 Basic Auth）。

### 7.2 无金融激励 + 公网匿名 = 垃圾提案

没有成本约束时，自动化脚本能在几分钟内刷满整条链。轻量防滥用：

- 提案限频（同一 IP / 同一 pubkey 每隔 N 秒一条）；
- 提高 PoI 门槛（`block_validator.MIN_POI_TOKENS`）；
- 邀请制纪元；
- 只读访客模式 + 白名单矿工。

> 以上均涉及 `server.py` / `block_validator.py`，**属线①独占文件，本线未实现**。

### 7.3 免费层会冷启动 / 休眠

不要指望单个免费 hub 长期在线。**「多 hub + 数据归档」比「一个稳定 hub」更现实**：

- 任何人都能开一个 hub；
- 每个 hub 定时把链数据导出提交回仓库（§8）；
- 某个 hub 关站，历史仍留在仓库里，可被别人接手继续长。

### 7.4 合规

- 本仓库许可为 **PolyForm Noncommercial 1.0.0**：**禁止任何商业使用与商业部署**；
  保留并随附 `LICENSE` 与 `NOTICE`，不得移除其中的声明；
  ⚠️ `LICENSE` 的版权所有人已定稿（鹿拾 / Yuanhao Lu，仓库 https://github.com/luyuanhao/stratumgenesis）。
- 站点显著位置标注「**非官方部署**」，并给出上游仓库链接；
- 不得暗示该部署由原作者运营、背书或承担任何责任；
- 不得绑定作者个人资源（域名、服务器、账号、密钥）；
- 第三方依赖 `ecdsa`（Apache-2.0）的许可声明已在 `requirements.txt` 中注明，随附即可；
- 若你在欧盟/加州等地公开部署并采集访问日志，注意隐私合规义务（本项目默认不采集，
  但宿主平台与反向代理可能会）。

---

## 8. 数据自动归档（GitHub Actions 当免费定时任务）

思路：hub 运营者无需服务器，用 Actions 定时把链数据导出提交回仓库，
某个 hub 关站后历史仍留存。

```yaml
# .github/workflows/archive-chain.yml（部署者自行添加到自己的 fork）
name: archive-chain
on:
  schedule:
    - cron: "17 */6 * * *"     # 每 6 小时
  workflow_dispatch:

jobs:
  archive:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: 安装依赖
        run: pip install ecdsa
      - name: 导出可公开链快照（自动剥离私钥）
        run: python export_public.py --in "你的chain-v2存档.json" --out chain_state.json --metrics metrics.json
      - name: 提交回仓库
        run: |
          git config user.name  "archive-bot"
          git config user.email "archive-bot@users.noreply.github.com"
          git add chain_state.json
          git diff --quiet --cached || git commit -m "chore: 归档链快照 $(date -u +%Y-%m-%dT%H:%MZ)"
          git push
```

> 若 hub 跑在容器里，需先把 `/app/data/chain_v1.json` 取出（如 `docker cp` 或挂卷备份）
> 再执行导出。**绝不要把 `data/` 整个提交进仓库。**

---

## 9. 零服务器静态展馆（GitHub Pages）

### 9.1 生成可公开快照

```bash
python export_public.py --in "你的chain-v2存档.json" --out chain_state.json --metrics metrics.json
```

> ⚠️ **不要用本仓库自带的 `data/chain_v1.json`**：它是 **chain-v1 旧格式样本**（加载会被拒绝），
> 只用于验证「旧版本存档被拒」行为。请改用你自己 hub 实例的存档，或先造一份干净存档：
> `python -c "import server as s; s.build_server_state(fresh=True, persist_path=r'C:\Temp\gen.json')"`

脚本保证：

- 字段结构与 `GET /chain-state` 对齐，前端可直接复用；
- `miners[]` 只保留 `label` / `miner_pubkey_b64` / `balance`，**私钥一律丢弃**；
- 写出前 + 落盘后 **双重自检**：序列化文本中不得出现 `private_key` 及其变体
  （`privateKey` / `private-key` / `privatekey`，忽略大小写），不满足则拒绝写出并非零退出。

### 9.2 前端自动降级

`index.html` 已内置：**`/chain-state` 不可用（fetch 失败、非 200、非 JSON）时**，
自动读取同目录 `chain_state.json` 并进入 **只读展馆模式**：

| 能力 | 只读展馆 |
|---|---|
| 地层剖面 / 岩层详情 | ✅ |
| 纪元摘要卡 / 钻探考古 | ✅ |
| 休眠分支列表 / 影子岩层对照 | ✅ |
| 程序画廊 / 语言地层 | ✅ 浏览 |
| 推演提案 | ❌ 入口禁用 |
| NovScript 沙箱执行 | ❌ 禁用（代码仅供查看） |

页面顶部会出现一条中文横幅，说明当前为只读展馆及如何亲手提案。

> **能力边界（明确）**：只读展馆**不能提案、不能执行 NovScript 沙箱**——它不是「活的服务」，
> 只是仓库快照 `chain_state.json` 的可视化。任何需要写入（出块、提交提案、运行沙箱）的操作在只读模式下都会被禁用。
> 想亲手参与共识，请看 §9.4 的两条路。

### 9.3 发布

1. 仓库 **Settings → Pages → Source: Deploy from a branch → `main` / `/root`**；
2. 确认根目录同时存在 `index.html` 与 `chain_state.json`；
3. 打开 `https://<用户名>.github.io/<仓库名>/`。

> 需要 HTTP 环境：直接双击 `index.html` 用 `file://` 打开时，浏览器会因 CORS
> 拒绝 `fetch("chain_state.json")`，页面会退回到「无法连接本地服务」提示。
> 本地预览请用 `python -m http.server` 后访问 `http://127.0.0.1:8000/`。

### 9.4 想亲手玩？用 Codespaces，或等 Pyodide 版

只读展馆只能看不能动。**想亲手出块、提交提案、跑 NovScript 沙箱**，有两条路：

1. **GitHub Codespaces（推荐，能提案）**：见本仓库 `PUBLISH_CHECKLIST.md` §③，一键起活 hub + 端口转发，
   能力等同本地 `python server.py`；
2. **浏览器内 Pyodide 版（另一条线开发中）**：目标是把服务端验证逻辑搬进浏览器，纯前端即可提案与验签，
   **无需服务器、无需暴露私钥**。上线前请以该线进展为准。

> 一句话：只看演示用 Pages 只读展馆；想参与共识请用 Codespaces，或等 Pyodide 版。

---

## 10. 截至本线收工时的状态（并行开发中，其他线仍在推进）

| 项 | 状态 | 备注 |
|---|---|---|
| `requirements.txt` | ✅ 已有（别线补充） | 内容 `ecdsa==0.19.2`；Dockerfile 仍保留「缺失则兜底装 ecdsa」的兼容分支 |
| `LICENSE` | ✅ 已有（已定稿） | **PolyForm Noncommercial 1.0.0**，禁止商用；版权所有人：鹿拾（Yuanhao Lu），仓库 https://github.com/luyuanhao/stratumgenesis |
| `NOTICE` | ✅ 已有 | 含项目定位与免责声明 |
| `README.md` | ✅ 已有 | 由线②持有，部署徽章/链接待线②补 |
| `.dockerignore` | ❌ 缺失 | 建议新增；本线未被授权创建 |
| `server.py` 监听地址可配置 | ❌ 未做 | 属线①独占文件，本线只给提案（§2-A） |
| 客户端签名（消除公网冒充） | ❌ 未做 | 属线①范围，见 §7.1 |
| `data/chain_v1.json` 旧格式 | ⚠️ 保留 | chain-v1 样本，含私钥，**不要发布** |

> 本线收工时，仓库中另有其他线的在途改动（`server.py` / `chain_store.py` /
> `block_validator.py` / `analyze_chain.py` / `BRANCH_PROMOTION_IMPLEMENTATION.md` 等）。
> `export_public.py` 已在**最新**的 `server.py` 上复测通过（链高 102、103 块、2 纪元）。

---

## 11. 故障排查

| 现象 | 原因 | 解决 |
|---|---|---|
| 容器起来就退出，日志提示存档格式不匹配 | 本地 `data/chain_v1.json`（chain-v1）被打进镜像 | 用干净检出构建，或依赖镜像内的 `rm -rf /app/data` |
| `docker run` 后宿主机访问不了 | `server.py` 只听 `127.0.0.1` | 见 §2 |
| Render 健康检查失败 | 同上；平台要求 `0.0.0.0:$PORT` | §2-B / §2-C |
| Pages 上显示「无法连接本地服务」 | 缺 `chain_state.json`，或用了 `file://` | 按 §9 生成并用 HTTP 访问 |
| 导出脚本报「存档校验失败」 | 存档损坏或版本不符 | 换存档路径，或 `--fresh` 重建演示链 |
| 导出脚本报「安全自检未通过」 | 输出中检出私钥痕迹 | 属保护机制生效，请提交 issue 并附上下文 |

---

*本文件由线④编写。所有涉及 `server.py` / `block_validator.py` / `chain_store.py` 的改动建议，
均以「提案」形式给出，未实施。*
