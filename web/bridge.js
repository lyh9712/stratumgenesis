/* ============================================================
   web/bridge.js · StratumGenesis v0.3 浏览器内核 JS↔Python 桥
   ------------------------------------------------------------
   本文件只定义 createStratumBridge(pyodide)，由 web/pyodide_boot.js
   在 Pyodide 就绪后调用。桥接层把 JS 调用转发给 Pyodide 内已加载的
   web/py_sandbox 模块（真实链核心逻辑）。

   设计红线（见任务书）：
   - canonical_bytes() / ECDSA 签名只在 Python 侧执行；本桥绝不重写它们；
   - ecdsa 不可用时（离线且无 vendored 包），boot 层会直接降级只读，本桥
     不会被创建（即不会伪造任何验签结果）；
   - 所有 Python 侧返回值均为 JSON 字符串，桥只做 JSON 解析，不改写语义。

   导出函数（与后端 API 一一对应）：
   - pyChainState()             -> {chain_state 视图 JSON}
   - pyProposeStructured({...}) -> {propose 响应 JSON}
   - pyProposeText({text,...})  -> {propose 响应 JSON}
   - pyEval({code})             -> {eval 响应 JSON}
   - pyExportArchive()          -> {chain-v2 存档 JSON 字符串}
   - pyImportArchive(json)      -> {导入结果 JSON}
   - pyPromote({head_hash})     -> {升级结果 JSON（本版为留桩）}
   - saveChain() / loadChainLS()-> 浏览器内持久化（localStorage）
   ============================================================ */
(function (global) {
  "use strict";

  const LS_KEY = "stratum_chain_v2";

  function createStratumBridge(pyodide) {
    if (!pyodide) throw new Error("pyodide 未就绪");

    /* 统一转发：把 JS 实参塞进 Pyodide 全局变量 __py_arg，再调用 py_sandbox。
       - 无参函数（py_chain_state / py_export_archive）不传 __py_arg；
       - 字符串实参（如 py_import_archive 的存档 JSON 串）原样传入，禁止二次 JSON 编码；
       - 对象/数组/数字实参才 JSON.stringify。
       runPythonAsync 返回的是 Python 侧函数返回值（str），天然跨边界。 */
    async function callPy(funcName, argObj) {
      const hasArg = argObj !== undefined;
      const argExpr = hasArg ? "__py_arg" : "";
      if (hasArg) {
        const v = (typeof argObj === "string") ? argObj : JSON.stringify(argObj);
        pyodide.globals.set("__py_arg", v);
      }
      const out = await pyodide.runPythonAsync(
        "import json, py_sandbox\n" +
        "py_sandbox." + funcName + "(" + argExpr + ")"
      );
      return out; // 已是 JS 字符串（Python str）
    }

    const bridge = {
      _pyodide: pyodide,

      /* py_init / py_reset 接收的是「整数」而非 JSON 字符串，因此绕过 callPy 的
         JSON 序列化（否则 102 会变成字符串 "102"，导致 seed_count+1 报错）。 */
      async pyInit(seedCount) {
        pyodide.globals.set("__py_arg", seedCount === undefined ? 102 : seedCount);
        return pyodide.runPythonAsync("import py_sandbox\npy_sandbox.py_init(__py_arg)");
      },

      async pyReset(seedCount) {
        pyodide.globals.set("__py_arg", seedCount === undefined ? 102 : seedCount);
        return pyodide.runPythonAsync("import py_sandbox\npy_sandbox.py_reset(__py_arg)");
      },

      async pyChainState() {
        return callPy("py_chain_state");
      },

      async pyProposeStructured(payload) {
        const res = await callPy("py_propose_structured", payload);
        if (JSON.parse(res).success) await this.saveChain();
        return res;
      },

      async pyProposeText(text, modelMetadata) {
        const res = await callPy("py_propose_text", { text: text, model_metadata: modelMetadata || "" });
        if (JSON.parse(res).success) await this.saveChain();
        return res;
      },

      async pyEval(code) {
        return callPy("py_eval", { code: code });
      },

      async pyExportArchive() {
        return callPy("py_export_archive");
      },

      async pyImportArchive(jsonStr) {
        const res = await callPy("py_import_archive", jsonStr);
        await this.saveChain();
        return res;
      },

      async pyPromote(headHash) {
        return callPy("py_promote", { head_hash: headHash });
      },

      /* ---------- 浏览器内持久化（刷新后链仍在） ---------- */
      async saveChain() {
        try {
          const arc = await callPy("py_export_archive");
          global.localStorage.setItem(LS_KEY, arc);
          return true;
        } catch (e) {
          console.warn("[StratumBridge] 存档持久化失败：", e);
          return false;
        }
      },

      async restoreChain() {
        const saved = global.localStorage.getItem(LS_KEY);
        if (!saved) return false;
        try {
          const res = JSON.parse(await callPy("py_import_archive", saved));
          return !!res.success;
        } catch (e) {
          console.warn("[StratumBridge] 本地存档恢复失败（已忽略）：", e);
          return false;
        }
      },

      /* 显式导出为可下载文件（验收 2 需要） */
      async downloadArchive(filename) {
        const arc = await callPy("py_export_archive");
        const blob = new Blob([arc], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename || "stratum_chain_v2.json";
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      },

      get localStorageKey() { return LS_KEY; },
    };

    return bridge;
  }

  global.createStratumBridge = createStratumBridge;
})(window);
