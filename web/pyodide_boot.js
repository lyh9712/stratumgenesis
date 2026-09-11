/* ============================================================
   web/pyodide_boot.js · StratumGenesis v0.3 浏览器内核引导
   ------------------------------------------------------------
   职责：
   1) 快速探测本机后端（/chain-state）。若可达，直接判定为「本机后端」模式，
      不加载 Pyodide —— 保证 python server.py 模式完全不受影响。
   2) 否则加载 Pyodide（CDN 优先，失败回退 web/vendor/pyodide/）。
   3) 把项目真实 Python 模块（block_model / chain_store / block_validator /
      novscript / crypto_key / persistence / web/py_sandbox 等）挂载进
      Pyodide 虚拟文件系统，加入 sys.path。
   4) micropip 安装 ecdsa（纯 Python，网络优先，失败回退 vendored wheel）。
   5) 创建浏览器内核桥（createStratumBridge），并从 localStorage 恢复存档。

   降级纪律（任务书红线）：
   - 任何一步失败（CDN 屏蔽 / WASM 加载失败 / ecdsa 不可用）→ 不伪造、不白屏，
     直接降级为「只读展馆」，并给出中文提示；
   - canonical_bytes() 与 ECDSA 签名始终在 Python 侧完成，本引导层不重实现。

   对外暴露：
   - window.__STRATUM_KERNEL__ : "loading" | "backend" | "pyodide" | "readonly"
   - window.__STRATUM_BRIDGE_PROMISE__ : Promise<bridge|null>
   - window.__STRATUM_BOOT_ERROR__ : 失败原因（中文）
   ============================================================ */
(function (global) {
  "use strict";

  const PYODIDE_VERSION = "0.26.4";
  const CDN_BASE = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
  const PAGE_BASE = new URL(".", global.location.href).href;
  const VENDOR_BASE = new URL("web/vendor/pyodide/", PAGE_BASE).href;

  // 需要在 Pyodide 内加载的项目根模块（仅核心，不引入 server.py）。
  const ROOT_MODULES = [
    "block_model.py", "block_validator.py", "chain_store.py", "epoch_manager.py",
    "persistence.py", "crypto_key.py", "utxo_model.py", "utxo_ledger.py",
    "mock_tokenizer.py", "weight_calculator.py", "candidate_pool.py",
    "conflict_voter.py", "epoch_summary.py", "miner_identity.py",
  ];
  const NOVSCRIPT_FILES = [
    "__init__.py", "ast.py", "errors.py", "evaluator.py", "language.py",
    "lexer.py", "parser.py", "registry.py", "sandbox.py",
  ];
  const SANDBOX_MODULE = "web/py_sandbox.py";

  const STRATUM_MOUNT = "/stratum";

  function setKernel(mode) { global.__STRATUM_KERNEL__ = mode; }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error("脚本加载失败：" + src));
      document.head.appendChild(s);
    });
  }

  async function fetchText(url) {
    const resp = await fetch(url, { cache: "no-store" });
    if (!resp.ok) throw new Error(`获取 ${url} 失败：HTTP ${resp.status}`);
    return resp.text();
  }

  async function mountModules(pyodide) {
    // 挂载点必须预先创建（Pyodide FS 不自动建父目录；否则 writeFile 抛 FS.ErrnoError 导致降级）。
    try { pyodide.FS.mkdir(STRATUM_MOUNT); } catch (_) { /* 已存在则忽略 */ }
    // 根模块
    for (const name of ROOT_MODULES) {
      const code = await fetchText(PAGE_BASE + name);
      pyodide.FS.writeFile(`${STRATUM_MOUNT}/${name}`, code);
    }
    // novscript 包
    pyodide.FS.mkdir(`${STRATUM_MOUNT}/novscript`);
    for (const name of NOVSCRIPT_FILES) {
      const code = await fetchText(PAGE_BASE + "novscript/" + name);
      pyodide.FS.writeFile(`${STRATUM_MOUNT}/novscript/${name}`, code);
    }
    // 浏览器内核沙箱（py_sandbox.py）
    const sb = await fetchText(PAGE_BASE + SANDBOX_MODULE);
    pyodide.FS.writeFile(`${STRATUM_MOUNT}/py_sandbox.py`, sb);
    // 加入搜索路径
    pyodide.runPython(`import sys; sys.path.insert(0, '${STRATUM_MOUNT}')`);
  }

  async function installEcdsa(pyodide) {
    const wheelUrl = (n) => PAGE_BASE + "web/vendor/wheels/" + n + ".whl";

    // 1) 在线优先：用 Pyodide 自带 micropip 从 PyPI 安装 ecdsa（含 six 依赖自动解析）。
    try {
      await pyodide.loadPackage("micropip");
      await pyodide.runPythonAsync(
        "import micropip\nawait micropip.install('ecdsa')"
      );
      return;
    } catch (_) { /* 联网失败 → 走 vendored 回退 */ }

    // 2) 离线回退：把 vendored 纯 Python wheel 直接解包进虚拟 site-packages。
    //    避开 loadPackage 的 SRI 校验与 micropip 离线自举难题；ecdsa 仅依赖 six，
    //    按依赖顺序（six → ecdsa）解包即可。
    const names = ["six", "ecdsa"];
    await pyodide.runPythonAsync(
      "import sys, os\n" +
      "_site = '/stratum/site-packages'\n" +
      "os.makedirs(_site, exist_ok=True)\n" +
      "if _site not in sys.path: sys.path.insert(0, _site)"
    );
    for (const n of names) {
      const url = wheelUrl(n);
      const resp = await fetch(url);
      if (!resp.ok) throw new Error("vendored wheel 缺失或不可达：" + url);
      const buf = new Uint8Array(await resp.arrayBuffer());
      pyodide.FS.writeFile("/stratum/_wheel.whl", buf);
      await pyodide.runPythonAsync(
        "import zipfile\n" +
        "with zipfile.ZipFile('/stratum/_wheel.whl') as z:\n" +
        "    z.extractall('/stratum/site-packages')\n"
      );
    }
    // 校验 ecdsa 确实可用（不可用则如实抛错，绝不伪造）
    await pyodide.runPythonAsync("import ecdsa");
  }

  async function startPyodide() {
    let loadPyodideFn;
    try {
      await loadScript(CDN_BASE + "pyodide.js");
      loadPyodideFn = global.loadPyodide;
      if (typeof loadPyodideFn !== "function") throw new Error("loadPyodide 未定义（CDN）");
      return await loadPyodideFn({ indexURL: CDN_BASE });
    } catch (cdnErr) {
      // CDN 不可用：回退 vendored
      try {
        await loadScript(VENDOR_BASE + "pyodide.js");
        loadPyodideFn = global.loadPyodide;
        if (typeof loadPyodideFn !== "function") throw new Error("loadPyodide 未定义（vendor）");
        return await loadPyodideFn({ indexURL: VENDOR_BASE });
      } catch (vendorErr) {
        throw new Error("Pyodide 运行时加载失败（CDN 与 vendored 均不可用）：" +
          String(cdnErr) + " | " + String(vendorErr));
      }
    }
  }

  async function bootPyodide() {
    setKernel("loading");
    // 1) 后端探测：可达则走本机后端，不加载 Pyodide。
    let backendOK = false;
    try {
      const probe = await fetch("/chain-state", { method: "GET" });
      backendOK = probe.ok;
    } catch (_) { backendOK = false; }
    if (backendOK) {
      setKernel("backend");
      global.__STRATUM_BRIDGE_PROMISE__ = Promise.resolve(null);
      return null;
    }

    // 2) 加载 Pyodide 运行时
    const pyodide = await startPyodide();

    // 3) 挂载项目模块
    await mountModules(pyodide);

    // 4) 安装 ecdsa；失败则降级只读（绝不伪造签名）
    try {
      await installEcdsa(pyodide);
    } catch (err) {
      throw new Error("ECDSA 不可用，浏览器内核无法签名区块：" + String(err));
    }

    // 5) 导入 py_sandbox 并创建桥
    await pyodide.runPythonAsync("import py_sandbox");
    const bridge = global.createStratumBridge(pyodide);
    global.StratumBridge = bridge; // 关键：暴露给 index.html 的写路径（deducePyodide / sb-run / 导入导出）
    await bridge.pyInit(102);
    const restored = await bridge.restoreChain();
    if (!restored) {
      // 没有本地存档时，pyInit 已完成预沉积；再确保落一份 baseline。
      await bridge.saveChain();
    }
    setKernel("pyodide");
    return bridge;
  }

  // 对外承诺：无论成功与否都 resolve（失败返回 null + 记录原因）。
  global.__STRATUM_BRIDGE_PROMISE__ = bootPyodide().catch((err) => {
    const msg = String(err && err.message ? err.message : err);
    global.__STRATUM_BOOT_ERROR__ = msg;
    setKernel("readonly");
    console.warn("[StratumGenesis] 浏览器内核不可用，降级为只读展馆：", msg);
    // 在页面给出中文提示（不白屏）。
    try {
      const note = document.createElement("div");
      note.id = "pyodide-fallback-note";
      note.style.cssText =
        "position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:999;" +
        "background:#2a1f15;color:#f0e4cf;border:1px solid #5a4630;border-radius:8px;" +
        "padding:10px 16px;font-size:12px;max-width:90vw;box-shadow:0 6px 20px rgba(0,0,0,.4)";
      note.textContent =
        "浏览器内核（Pyodide）未能加载，已降级为只读展馆：无法提案/执行。" +
        "如需离线内核，请按 web/README.md 放置 vendored Pyodide 与 ecdsa wheel。";
      document.body.appendChild(note);
    } catch (_) { /* 忽略 DOM 注入失败 */ }
    return null;
  });

  // 立即给一个初始状态，避免页面空白期无反馈。
  setKernel(global.__STRATUM_KERNEL__ || "loading");
})(window);
