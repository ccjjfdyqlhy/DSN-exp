# benchmarks —— 可复现的数字

> 原则（roadmap 段 8）：**README 上的每个数字都能被一条命令复现**。
> 「很快」「很稳」不算数字；下面每一个数字后面都跟着复现它的命令。

```bash
python benchmarks/run_benchmarks.py            # 四项全部
python benchmarks/run_benchmarks.py --json     # 机器可读（写文件用 --out）
```

参考值（2026-11-21，本机 16 线程 Linux / Python 3.12；数字随机器浮动，
**口径不变**）：

| 数字 | 参考值 | 口径 | 复现 |
|---|---|---|---|
| 守卫链路单次往返 | p50 ≈ 0.28 ms，p95 ≈ 0.38 ms | 纯工具经 策略求值+幂等检查+执行+审计 的本地单次调用，N=300 | `run_benchmarks.py`（tool_call_latency_us） |
| journal 重放恢复 | ≈ 1 ms / 200 事件 | checkpoint 不可用时的全量 journal 重放（最坏恢复路径） | 同上（journal_recovery_ms） |
| 分层记忆 L1 压缩比 | ≈ 3.35× | 40 条 L1 原文进入摘要压缩后，组装产物与原文的字符量之比 | 同上（memory_compaction_ratio） |
| 崩溃恢复成功率 | 46/46 = 100% | `tests/fault/` 故障注入层：kill -9 恢复 / 幂等重复投递 / checkpoint 损坏 / 审批崩溃补填（59 条中 46 条运行 + 13 条变异层默认跳过） | 同上（fault_suite）；单独跑：`python -m pytest -q tests/fault/` |

## 为什么「崩溃恢复成功率」指向测试层

这个数字不是基准出来的 —— 它是 `tests/fault/` 测出来的（真 `os._exit(9)`
子进程、真 SIGKILL、真损坏 checkpoint）。基准脚本**引用**该层的通过率，
不自己伪造一个「成功率」。这也是变异测试存在的原因：拆掉实现里的任何
一条保护，这层的对应用例立刻变红（`RUN_MUTATION=1 python -m pytest -q tests/fault/mutation/`）。

## 为什么没有「显存占用」的数字

它依赖真 GPU 与真模型进程，通用脚本测不出可移植的值。框架层如实提供的
是各资源的 `vram_estimate_mb` **声明值**（`aicf/infra/resources/pool.py`
的 `ResourceSpec`，如 decision ≈ 20400 MB、tts ≈ 2048 MB、asr ≈ 1500 MB）
—— 声明值与实测值分开说，不冒充。

## 数字进 README 的规矩

- README 里引用基准数字时**必须带复现命令**；
- 数字变了先跑一遍本脚本，贴新值；
- 口径变了要改这张表并说明为什么（口径是承诺，值是观察）。
