#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""StratumGenesis v0.3 · 公开静态导出（线④：部署与分发 + 静态展馆）

从本地存档生成一份**可公开**的 chain_state.json：字段结构与 GET /chain-state
完全对齐，供 index.html 在拿不到后端时自动降级为「只读展馆」模式
（GitHub Pages / 任意纯静态托管）。

附带 `--metrics <path>` 可同时导出 metrics.json：把 analyze_chain 的实验指标
（含 by_model 跨 AI 创造力分区）落成前端可直接消费的数据文件，口径见
LEADERBOARD.md 与 EXPERIMENT_METRICS.md。metrics.json 是**新文件**，
不改变 chain_state.json 的既有字段名与结构。

安全红线
--------
persistence.py 的存档（data/chain_v1.json）**明文保存矿工私钥**
（miners[].private_key_b64）。公开链数据本身没问题（白皮书 §14.5 本就要公开
数据集），但连带私钥发布等于泄露。因此本脚本：

1. 输出的 miners[] 只保留 label / miner_pubkey_b64 / balance（即 GET /chain-state
   的公开字段），私钥一律丢弃；
2. 写出前用代码断言「序列化文本中不含 private_key 及其常见变体」，
   不满足即拒绝写出并以非零码退出（宁可不产出，也不产出泄密文件）；
   **两个输出文件（chain_state.json / metrics.json）都执行同一条断言**；
3. **模型身份红线**：公开快照必须携带 model_metadata——chain_state.json 的
   blocks[] 与 metrics.json 的 by_model 分区各一处，缺失即报错并拒绝写出。
   没有模型身份，跨 AI 创造力榜（--by-model / LEADERBOARD.md）就没有数据源，
   与其产出一份「看起来完整但榜单空白」的快照，不如直接失败；
4. 只做「读取 + 派生 + 写出」，不修改任何既有文件、不动 data/。

用法
----
    python export_public.py --in data/chain_v1.json --out chain_state.json
    python export_public.py --in data/chain_v1.json --out chain_state.json --metrics metrics.json

退出码
------
    0  成功
    1  失败（存档损坏 / 版本不匹配 / 私钥自检未通过 / 写出失败）
    2  命令行参数错误

依赖：Python 标准库 + 项目既有依赖（ecdsa 由 server / persistence 间接引入）。
不联网、不调用任何 LLM、不引入第三方库。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

DEFAULT_IN = os.path.join(_HERE, "data", "chain_v1.json")
DEFAULT_OUT = os.path.join(_HERE, "chain_state.json")

# 泄露检测：private_key / privateKey / private-key / privatekey（忽略大小写）
_SECRET_RE = re.compile(r"private[\s_\-]*key", re.IGNORECASE)

# 输出中允许保留的矿工字段白名单（余额是链上公开数据，可保留）。
# 注意：GET /chain-state 实际字段名为 miner_pubkey_b64（不是 public_key_b64），
# 这里以真实契约为准，不发明新字段名，避免前端读不到。
_PUBLIC_MINER_FIELDS = ("label", "miner_pubkey_b64", "balance")


class ExportError(Exception):
    """导出失败；错误信息为中文，直接展示给使用者。"""


def _import_project_modules():
    """延迟导入项目模块，导入失败给出可操作的中文提示。"""
    try:
        import persistence
    except Exception as error:
        raise ExportError(
            f"无法导入项目模块 persistence：{error}。"
            f"请在项目根目录下运行本脚本，并确认依赖已安装（pip install ecdsa）。"
        ) from error
    try:
        import server
    except Exception as error:
        raise ExportError(
            f"无法导入 server.py：{error}。"
            f"若其他开发线正在编辑核心模块，请稍后重试；"
            f"若确为标准库/依赖缺失，请先安装 requirements.txt 中的依赖。"
        ) from error
    return persistence, server


def _import_analyze_chain():
    """延迟导入分析器（仅在 --metrics 时需要）。"""
    try:
        import analyze_chain
    except Exception as error:
        raise ExportError(
            f"无法导入 analyze_chain.py：{error}。"
            f"请在项目根目录下运行本脚本；若其他开发线正在编辑该文件，请稍后重试。"
        ) from error
    return analyze_chain


def strip_miners(miners: list) -> list:
    """只保留公开字段（label / public_key_b64 / balance），丢弃私钥等一切字段。"""
    public = []
    for item in miners or []:
        if not isinstance(item, dict):
            continue
        record = {}
        for field in _PUBLIC_MINER_FIELDS:
            if field in item:
                record[field] = item[field]
        public.append(record)
    return public


def build_public_payload(archive_path: str) -> tuple[dict, dict]:
    """读取存档 → 重建链 → 产出与 /chain-state 对齐的可公开结构。

    返回 (payload, stats)；任何一步失败抛 ExportError。
    """
    persistence, server = _import_project_modules()

    if not os.path.exists(archive_path):
        raise ExportError(f"存档文件不存在：{archive_path}")

    try:
        data = persistence.load_state(archive_path)
    except persistence.PersistenceError as error:
        raise ExportError(f"存档校验失败：{error}") from error

    try:
        store = persistence.rebuild_store(data["blocks"], data["sleeping_branches"])
    except persistence.PersistenceError as error:
        raise ExportError(
            f"主链重放失败：{error}。存档与当前代码不兼容，"
            f"请确认存档版本（chain-v2）与代码一致。"
        ) from error

    try:
        registry = server.MinerRegistry(miners=persistence.miners_from_list(data["miners"]))
        state = server.ServerState(
            store=store,
            registry=registry,
            rejection_reasons=dict(data.get("rejection_reasons") or {}),
            seed_count=0,
            persist_path=None,   # 只读导出：绝不触发自动保存
        )
        payload = server.api_chain_state(state)
    except Exception as error:
        raise ExportError(f"生成链状态失败：{error}") from error

    payload["miners"] = strip_miners(payload.get("miners"))
    # 供前端/人工识别：这是一份只读快照，不是活的服务
    payload["readonly"] = True

    stats = {
        "chain_height": payload.get("chain_height"),
        "blocks": len(payload.get("blocks") or []),
        "epochs": len(payload.get("epochs") or []),
        "sleeping_branches": len(payload.get("sleeping_branches") or []),
        "miners": len(payload["miners"]),
        "source_format_version": data.get("format_version"),
        "source_miner_keys_stripped": len(data.get("miners") or []),
    }
    return payload, stats


def build_metrics_payload(archive_path: str) -> dict:
    """读取存档 → 生成 metrics.json 的公开结构（含 by_model 跨 AI 分区）。

    键名与版本契约见 analyze_chain.PUBLIC_METRICS_KEYS / METRICS_SCHEMA_VERSION，
    口径见 LEADERBOARD.md。任何一步失败抛 ExportError。
    """
    analyze_chain = _import_analyze_chain()

    if not os.path.exists(archive_path):
        raise ExportError(f"存档文件不存在：{archive_path}")

    try:
        data = analyze_chain.load_archive(archive_path)
    except analyze_chain.AnalysisError as error:
        raise ExportError(f"存档校验失败：{error}") from error

    try:
        return analyze_chain.build_metrics(
            data,
            source=os.path.abspath(archive_path),
            source_label="archive",
        )
    except Exception as error:
        raise ExportError(f"生成实验指标失败：{error}") from error


def assert_model_identity(payload: dict, metrics: dict) -> None:
    """模型身份红线：公开快照必须携带 model_metadata，缺失即拒绝写出。

    任务书要求「两处各一」，故分别校验：
      1) chain_state.json —— blocks[] 每一块都必须有 model_metadata 键
         （创世块同样带，值为 "genesis"）；休眠分支不计，因其不参与榜单；
      2) metrics.json —— by_model.models 至少有一个非空 model_id 的分区。

    理由：model_metadata 是「跨 AI 创造力榜」唯一的数据源。若它缺失，
    榜单会静默变空， reader 会误以为「没有差异」而不是「没有数据」——
    这是比报错更糟的结果。
    """
    blocks = payload.get("blocks") or []
    if not blocks:
        raise ExportError(
            "模型身份自检未通过：chain_state.json 的 blocks[] 为空，"
            "无法确认快照携带 model_metadata。请检查存档是否损坏。"
        )
    missing = [b.get("height") for b in blocks if "model_metadata" not in b]
    if missing:
        shown = ", ".join(str(h) for h in missing[:10])
        more = "…" if len(missing) > 10 else ""
        raise ExportError(
            "模型身份自检未通过：chain_state.json 有 "
            f"{len(missing)} 个区块缺少 model_metadata 字段（高度：{shown}{more}）。"
            "跨 AI 创造力榜（--by-model / LEADERBOARD.md）将无数据源，已拒绝写出。"
        )

    partition = metrics.get("by_model") or {}
    models = partition.get("models") or []
    if not models:
        raise ExportError(
            "模型身份自检未通过：metrics.json 的 by_model.models 为空，"
            "未能从 model_metadata 分出任何模型分区。已拒绝写出。"
        )
    if not any(str(m.get("model_id") or "").strip() for m in models):
        raise ExportError(
            "模型身份自检未通过：metrics.json 的 by_model.models 存在，"
            "但 model_id 全为空值，无法构成有效分区。已拒绝写出。"
        )


def assert_no_secret(text: str) -> None:
    """自我断言：序列化文本中不得出现任何私钥字段痕迹。"""
    hit = _SECRET_RE.search(text)
    if hit:
        start = max(0, hit.start() - 40)
        snippet = text[start:hit.end() + 40].replace("\n", " ")
        raise ExportError(
            "安全自检未通过：输出内容中检出私钥字段痕迹 "
            f"（匹配 {hit.group(0)!r}，上下文 …{snippet}…）。"
            "已拒绝写出文件，请检查 miners 序列化逻辑。"
        )


def write_atomic(path: str, text: str) -> None:
    """临时文件 + 原子替换，避免中断产生半截 JSON。"""
    parent = os.path.dirname(os.path.abspath(path)) or "."
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError as error:
        raise ExportError(f"无法创建输出目录 {parent}：{error}") from error
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_path, path)
    except OSError as error:
        # 清理临时文件，绝不留下半截产物
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise ExportError(f"写出文件失败 {path}：{error}") from error


def _cli(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="StratumGenesis 公开静态导出：从存档生成可公开的 chain_state.json",
    )
    parser.add_argument("--in", dest="src", default=DEFAULT_IN,
                        help=f"源存档路径（默认 {DEFAULT_IN}）")
    parser.add_argument("--out", dest="out", default=DEFAULT_OUT,
                        help=f"输出路径（默认 {DEFAULT_OUT}）")
    parser.add_argument("--metrics", dest="metrics", default=None,
                        help="同时导出实验指标 metrics.json（含 by_model 跨 AI 分区）；"
                             "不指定则只导出 chain_state.json")
    args = parser.parse_args(argv)

    try:
        payload, stats = build_public_payload(args.src)
    except ExportError as error:
        print(f"[错误] {error}")
        return 1

    metrics = None
    if args.metrics:
        try:
            metrics = build_metrics_payload(args.src)
        except ExportError as error:
            print(f"[错误] {error}")
            return 1

    # 模型身份红线：先于序列化与写出执行（缺失即失败，不产出「榜单空白」的快照）
    if metrics is not None:
        try:
            assert_model_identity(payload, metrics)
        except ExportError as error:
            print(f"[错误] {error}")
            return 1

    try:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    except (TypeError, ValueError) as error:
        print(f"[错误] 序列化失败（链数据含不可序列化字段）：{error}")
        return 1

    try:
        assert_no_secret(text)
    except ExportError as error:
        print(f"[错误] {error}")
        return 1

    try:
        write_atomic(args.out, text)
    except ExportError as error:
        print(f"[错误] {error}")
        return 1

    # 落盘后二次校验：读回文件再验一次，防止写出路径被替换等意外
    try:
        with open(args.out, "r", encoding="utf-8") as handle:
            on_disk = handle.read()
        assert_no_secret(on_disk)
        json.loads(on_disk)
    except (OSError, ValueError) as error:
        print(f"[错误] 落盘校验失败：{error}")
        return 1
    except ExportError as error:
        print(f"[错误] 落盘后私钥复检未通过：{error}")
        return 1

    metrics_bytes = None
    if metrics is not None:
        try:
            metrics_text = json.dumps(metrics, ensure_ascii=False, sort_keys=True, indent=2)
        except (TypeError, ValueError) as error:
            print(f"[错误] 指标序列化失败（含不可序列化字段）：{error}")
            return 1
        try:
            assert_no_secret(metrics_text)
            write_atomic(args.metrics, metrics_text)
        except ExportError as error:
            print(f"[错误] {error}")
            return 1
        # 落盘后二次校验
        try:
            with open(args.metrics, "r", encoding="utf-8") as handle:
                metrics_on_disk = handle.read()
            assert_no_secret(metrics_on_disk)
            json.loads(metrics_on_disk)
            metrics_bytes = len(metrics_on_disk.encode("utf-8"))
        except (OSError, ValueError) as error:
            print(f"[错误] 指标落盘校验失败：{error}")
            return 1
        except ExportError as error:
            print(f"[错误] 指标落盘后私钥复检未通过：{error}")
            return 1

    print("[导出完成] 公开静态链数据已生成")
    print(f"  源存档：{args.src}（format_version={stats['source_format_version']}）")
    print(f"  输出：{args.out}")
    print(f"  主链高度：{stats['chain_height']} · 区块 {stats['blocks']} 块 · "
          f"纪元 {stats['epochs']} 个 · 休眠分支 {stats['sleeping_branches']} 条")
    print(f"  矿工：{stats['miners']} 个（仅 label / miner_pubkey_b64 / balance；"
          f"已剥离 {stats['source_miner_keys_stripped']} 组私钥）")
    print(f"  文件大小：{len(on_disk.encode('utf-8')) / 1024:.1f} KB")
    print("  安全自检：输出内容未检出 private_key 字段痕迹（已通过）")

    if metrics is not None:
        heights_match = (metrics.get("chain_height") == stats["chain_height"])
        print(f"  指标文件：{args.metrics}（{metrics_bytes / 1024:.1f} KB）")
        print(f"    metrics.schema_version = {metrics.get('schema_version')} · "
              f"by_model 分区 {len((metrics.get('by_model') or {}).get('models') or [])} 个模型")
        print(f"    链高一致性：metrics.json={metrics.get('chain_height')} vs "
              f"chain_state.json={stats['chain_height']} → "
              f"{'一致' if heights_match else '★不一致★'}")
        print("    模型身份自检：chain_state.blocks[] 与 metrics.by_model 均含 "
              "model_metadata（已通过）")
        if not heights_match:
            print("  [错误] 两份输出的链高不一致，可能来自不同的链快照。")
            return 1

    print("  提示：把本文件与 index.html 一起放到静态托管即可获得只读展馆。")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
