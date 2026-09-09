"""StratumGenesis NovScript 沙箱统一入口演示。

本演示只运行单机纯计算，不创建区块、不调用 LLM、不进行网络通信。
"""

from novscript import SandboxLimits, run_sandbox, validate_on_nodes


SOURCE = """
;; 惰性绑定：add-one 的参数只在函数体读取时才会被强制。
(bind add-one (lambda (x) (+ x 1)))
(add-one 41)
"""


def main() -> None:
    limits = SandboxLimits(max_steps=1_000, max_heap_objects=100, max_output_chars=1_000)
    result = run_sandbox(SOURCE, limits=limits)
    print("单次沙箱运行：")
    print(result)

    reports = validate_on_nodes(SOURCE, ["node-a", "node-b", "node-c"], limits=limits)
    print("\n单机模拟多节点验证：")
    for report in reports:
        print(report.node_id, report.accepted, report.result.value, report.interpreter_version)


if __name__ == "__main__":
    main()
