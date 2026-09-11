# StratumGenesis v0.3 · 上线检查单（PUBLISH_CHECKLIST.md）

> 给「要上线的人」照着做。每条都给**可复制命令 / 点击路径 + 失败排查点**。
> 本卡（3/4 · 上线检查单 + 部署验证）编写。所有标注「已验证」的结论，均来自本机实跑（见末尾附录）。

---

## ⛔ 硬门槛（排在最前，未满足不得发布）

**许可占位符已于 2026-09-10 定稿填入**：版权所有人 **鹿拾（Yuanhao Lu）**；
商业授权联络 <https://github.com/luyuanhao>；仓库 <https://github.com/luyuanhao/stratumgenesis>。
若你 fork 后改了署名或仓库地址，必须重新执行 1.1 的残留扫描。

- 本仓库许可为 **PolyForm Noncommercial 1.0.0**，禁止任何商业使用与商业部署；
- 署名或仓库地址缺失 = 许可主体不明，部署者自行承担全部合规风险。

---

## ① 发布前（Pre-publish）

### 1.1 许可与署名（硬门槛）
确认以下位置的**署名 / 联络 / 仓库地址**与你的实际情况一致（fork 改名时需同步替换）：
- `LICENSE`（版权所有人：鹿拾 / Yuanhao Lu）
- `NOTICE`（项目组织者 / 联系方式 / 仓库 URL）
- `LICENSE-SCOPE.md`（§4 署名义务、§7 商业授权联络）
- `README.md §9`（徽章中的仓库地址）

排查（残留占位符扫描）：
```bash
grep -rniE "TODO|FIXME|占位|placeholder|your[-_ ]?name|<.*@.*>|example\.com" LICENSE NOTICE README.md
```
仍命中 → **未填完，停止发布**。

### 1.2 全量测试通过
```bash
python -m unittest discover -s tests -p "test_*.py"
# 期望末两行：Ran N tests in X.XXXs  /  OK
```
排查：
- `import ecdsa` 失败 → `pip install ecdsa==0.19.2`；
- `test_http_api` 报 `Address already in use` → 28417 被占用：`netstat -ano | findstr :28417` 找占用进程并关闭（**28418 是腾讯会议、50062 是沙箱 CLI，禁止误杀**）；
- 若其他开发线正在改核心模块导致个别用例失败 → 重试一次；仍失败请记录并反馈大总管，**不要改核心文件迁就**。

### 1.3 用最新代码刷新公开快照（chain_state.json / metrics.json）
> ⚠️ 导出源必须是 **chain-v2** 存档。`data/chain_v1.json` 是旧版（chain-v1，含明文私钥），当前 `export_public.py` 会**直接拒绝**它（报错「存档格式版本不匹配：期望 chain-v2，实际 chain-v1」）。**不要拿它当源。**

- 方式 A（推荐，从运行中 hub 导出）：hub 已在 `server.py` 的 `persist_path` 落盘 chain-v2 存档，直接导出：
  ```bash
  python export_public.py --in <你的hub存档>.json --out chain_state.json --metrics metrics.json
  ```
- 方式 B（本地重建一份演示快照；不前台起服务）：
  ```bash
  # 生成 chain-v2 存档（data/ 已被 .gitignore 排除，不会入库）
  python -c "import server as s; s.build_server_state(fresh=True, persist_path=r'data/chain_v2.json')"
  python export_public.py --in data/chain_v2.json --out chain_state.json --metrics metrics.json
  ```
- 期望输出：`[导出完成] … 安全自检：输出内容未检出 private_key 字段痕迹（已通过）` + `模型身份自检：chain_state.blocks[] 与 metrics.by_model 均含 model_metadata（已通过）`。
- **私钥零泄漏确认（必做）**：
  ```bash
  grep -rni "private_key" chain_state.json metrics.json
  # 必须无任何输出；有输出 = 泄密，立即删除文件并报 issue
  ```

---

## ② GitHub 仓库与 Pages（静态只读展馆）

### 2.1 仓库设置
- 仓库设为 **Public**（Private 仓库的 Pages 需付费 / 不公开）；
- 确认根目录存在 `index.html`、`chain_state.json`、`metrics.json` 三个文件。
- **是否需要 `.nojekyll`：建议创建（结论：创建）。**
  - 理由：本项目是纯静态站点（`index.html` + 两份 JSON），不含任何 Jekyll 博客结构。GitHub Pages 默认会用 Jekyll 处理站点，可能误解析 `index.html` 的 front matter 或对 `.json` 做额外处理；放一个空的 `.nojekyll` 可让 Pages **原样托管**所有文件，零副作用。
  - 创建：`touch .nojekyll`（空文件即可，本卡已创建）。

### 2.2 开启 Pages
- `Settings → Pages → Source: Deploy from a branch → 选 main / root` → Save。
- 自定义域（可选）：`Settings → Pages → Custom domain` 填域名；DNS 加 `A` 记录指向 `185.199.108~111.153`，或 `CNAME` 指向 `<user>.github.io`；就绪后勾选 **Enforce HTTPS**。

### 2.3 推送后验证站点可用
打开 `https://<user>.github.io/<repo>/`，逐项确认：
1. 页面加载、`index.html` 展区渲染；
2. **只读模式确认方法**：页面顶部出现中文横幅（如「只读展馆 / 无法连接本地服务」说明）；提案入口被禁用（按钮灰掉或点击提示只读）；浏览器 DevTools → Network 能看到前端成功 `fetch chain_state.json` 返回 **200**；
3. 命令行快速验证三路径 200（本卡实跑方法，端口用非 28417）：
   ```bash
   python -m http.server 28500   # 在含 index.html/chain_state.json/metrics.json 的目录起服务
   # 另开终端：
   curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:28500/index.html
   curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:28500/chain_state.json
   curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:28500/metrics.json
   # 三个都应输出 200；验证完记得 Ctrl+C 关掉服务
   ```
排查：
- 显示「无法连接本地服务」→ 根目录缺 `chain_state.json`，或用了 `file://` 双击打开（CORS 会拦 fetch）→ 改用 HTTP 方式访问；
- 页面空白 → 检查 `index.html` 是否为主入口、是否放错子目录；
- 自定义域 HTTPS 红叉 → DNS 未生效或证书未签发，等几分钟重试。

---

## ③ Codespaces 试玩（能提案的玩法）

### 3.1 是否需要 `.devcontainer`：**非必须，但推荐提供**（结论）
- 不提供也能玩：Codespaces 默认 Ubuntu + Python，手动 `pip install ecdsa && python server.py` 即可；
- 提供可做到「一键起服务 + 自动装依赖」，体验更顺。下面给一份最小 `.devcontainer/devcontainer.json`（放到仓库 `.devcontainer/` 下）：
  ```json
  {
    "name": "StratumGenesis",
    "image": "mcr.microsoft.com/devcontainers/python:3.12",
    "postCreateCommand": "pip install ecdsa==0.19.2",
    "forwardPorts": [28417],
    "portsAttributes": { "28417": { "label": "StratumGenesis Hub", "visibility": "public" } }
  }
  ```
  > 注：`.devcontainer` 是否纳入本仓库由大总管裁决；本卡仅给出可复制内容，未擅自创建该目录。

### 3.2 一键起服务与端口转发
1. 仓库页面 → `Code → Codespaces → Create codespace on main`；
2. 终端：
   ```bash
   pip install ecdsa==0.19.2
   python server.py            # 监听 127.0.0.1:28417
   ```
3. 端口转发：Codespaces 自动识别 `forwardPorts: [28417]`；在 `PORTS` 面板把 28417 设为 **Public**（默认 Private 仅自己可访问），点预览 URL 即可在浏览器打开 hub；
4. 打开后即为**活的服务**：可推演提案、可执行 NovScript 沙箱。

### 3.3 能力差异（只读展馆 vs Codespaces）
| 能力 | ② Pages 只读展馆 | ③ Codespaces 活 hub |
|---|---|---|
| 浏览地层 / 纪元 / 程序画廊 | ✅ | ✅ |
| 推演提案 | ❌ 入口禁用 | ✅ |
| NovScript 沙箱执行 | ❌ 禁用 | ✅ |
| 数据持久化 | 仓库快照文件 | 容器会话（重启即丢，需配合归档） |

---

## ④ hub 部署（Docker / Render / Fly）

> ⚠️ 以下 Docker / Render / Fly 的**实机构建本卡未验证**（本机无 Docker 引擎、无 Render·Fly 账号，且按纪律不联网、不装包）。配置按 `DEPLOY.md` 编写，首次部署请按各平台排错命令自查。

### 4.1 Docker（本地 / VPS）
```bash
docker build -t stratumgenesis:0.3 .
docker run -d --name stratum -p 28417:28417 -v stratum-data:/app/data stratumgenesis:0.3
```
- 环境变量：`STRATUM_HOST`（见 4.4 风险；默认 127.0.0.1 即可，容器内用 socat 转发到 0.0.0.0）、`STRATUM_PORT`（默认 28417）；
- 冷启动：不挂卷则链回到初始演示链；挂 `-v stratum-data:/app/data` 可持久化；
- 排错：`docker logs stratum`、`docker exec stratum ls -l /app/data`。

### 4.2 Render（一键蓝图）
1. Fork → Dashboard `New → Blueprint`（自动读 `render.yaml`）；
2. 等 Build 完成 → 打开 `https://<svc>.onrender.com`。
- 免费层**会冷启动休眠**（首访 30–60s）、**无持久化磁盘** → 配合 `DEPLOY.md §8` 的 Actions 归档；
- 排错：若 `apt-get` 装 socat 失败，改用 `DEPLOY.md §2-C` 纯 Python 转发器替换 `startCommand`。

### 4.3 Fly.io
```bash
fly launch --no-deploy   # 生成 fly.toml，改 internal_port = 28417
fly volumes create stratum_data --size 1
fly deploy
```
- 排错：容器内仍 `127.0.0.1`，`internal_port` 转发由 Fly 边车完成。

### 4.4 部署者合规义务（必读）
- **保留 `LICENSE` / `NOTICE` / 免责声明**，随附不删、不涂改；
- 站点显著位置标注「**非官方部署**」，并给出上游仓库链接；
- **不得商用**（PolyForm Noncommercial 1.0.0）；不得暗示由作者运营 / 背书；
- 不得绑定作者个人资源（域名、服务器、账号、密钥）；
- 如对外绑定 `STRATUM_HOST=0.0.0.0`，务必先读下方风险段并自负风险。

#### STRATUM_HOST 风险（由另一条线提供，大总管转交，原文照录）
> STRATUM_HOST：不要轻易改绑。server.py 默认只监听 127.0.0.1，这是它唯一的安全边界。
> 设 STRATUM_HOST=0.0.0.0 会让服务对所有网络接口开放，而该服务服务端持有全部矿工私钥并代为签名、
> 没有任何鉴权与限频——任何能访问到端口的人都可以冒充任意矿工出块、提交任意提案。
> 仅建议在以下前提下改绑：① 部署在可信内网或容器网络内；② 外层有反向代理做访问控制与限流；
> ③ 明确是只读/演示用途。风险由部署者自负。

---

## 附录：本卡实跑验证证据（2026-09-10，本机）

| 验证项 | 命令 / 方法 | 结果 |
|---|---|---|
| 静态服务三路径 200 | `python -m http.server 28500`（临时目录，非 28417） | `/index.html`=**200**、`/chain_state.json`=**200**、`/metrics.json`=**200** |
| 导出刷新 + 私钥零泄漏 | `export_public.py --in <chain-v2 存档> --out … --metrics …` 后 `grep -rni private_key` | 导出退出码 **0**；私钥 grep **零命中（good）**；103 块、model_metadata 全覆盖、metrics 链高 102 一致 |
| 全量测试 | `python -m unittest discover -s tests -p "test_*.py"` | **Ran 306 tests … OK** |
| 端口卫生 | 服务用完 `taskkill` 并 `netstat` 复核 | 28500 已释放（仅 TIME_WAIT，自动消散） |

**未验证项及原因：**
- Docker 实构建：本机无 Docker 引擎，且按纪律不联网 / 不装包 → 未验证；配置按 `DEPLOY.md`，首次部署请自查。
- Render / Fly 实部署：无账号、不联网 → 未验证；配置与排错见 `DEPLOY.md` 与上文 4.2 / 4.3。

**进程卫生自检：**
- 探针服务（http.server 28500）已 `taskkill` 关闭，端口已释放；
- 所有临时文件落在系统临时目录（`C:\Users\…\AppData\Local\Temp\sg_*`），仓库内无 `data/_probe.json`、`_boot*`、`_batlog.txt` 等探针垃圾；
- `git status` 仅含本卡授权文件：`PUBLISH_CHECKLIST.md`（新增）、`DEPLOY.md`（修改）、`.nojekyll`（新增）。

---

*本文件由 3/4 线（上线检查单 + 部署验证）编写，仅新增部署物与文档，不改动任何业务代码。*
