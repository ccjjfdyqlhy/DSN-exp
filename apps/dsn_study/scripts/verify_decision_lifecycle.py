#!/usr/bin/env python3
"""System-1 决策模型（JEV）的「拉起 → 决策 → 空闲回收 → 再拉起」闭环验证。

真实拉起 llama-server（需 GPU + 约 16GB 显存 + 17s 冷启动），
用很短的空闲阈值把整条链路跑一遍，并顺带验证一次真实的情绪/危机判断。

前置：配置里 DECISION_ENABLED=true（默认就是）。
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from dotenv import load_dotenv  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
load_dotenv(os.path.join(_ROOT, ".env"))
load_dotenv(os.path.join(_ROOT, "apps", "dsn_study", ".env"), override=True)


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex(("127.0.0.1", port)) == 0


def vram() -> str:
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,memory.used", "--format=csv,noheader,nounits"],
        capture_output=True, text=True).stdout.strip()
    return " | ".join(out.splitlines())


def main() -> int:
    from apps.dsn_study.config import Config
    from apps.dsn_study.models import decision_service as ds
    from apps.dsn_study.models.resource_setup import setup_study_resources

    Config.DECISION_IDLE_TIMEOUT = 20        # 20 秒后回收
    Config.DECISION_IDLE_SHUTDOWN = True
    Config.RESOURCE_IDLE_SHUTDOWN = True
    Config.VOICE_IDLE_CHECK_INTERVAL = 5     # 回收器检查周期（池级）
    port = int(Config.DECISION_PORT)

    print("① 装配资源池（决策资源此刻只是登记，不占显存）")
    pool = setup_study_resources()
    rows = {r.get("name"): r for r in pool.list_resources()}
    row = rows.get("decision")
    assert row is not None, "决策资源没注册进池"
    print("   决策资源: loaded=%s idle_timeout=%ss managed=%s"
          % (row.get("loaded"), row.get("idle_timeout"), row.get("managed")))
    print("   拉起前显存:", vram())

    print("\n② 第一次借租约（应按需拉起 llama-server）")
    t0 = time.time()
    with ds.decision_lease(pool) as client:
        print("   拉起用时 %.1fs，端口在听: %s" % (time.time() - t0, port_open(port)))
        assert port_open(port), "决策服务没起来"
        print("   拉起后显存:", vram())

        print("\n③ 真实决策（一次前向，读 logprobs）")
        from harness.decisions.core import DecisionRequest, build_messages, interpret

        cases = [
            ("该邮件是否威胁取消订阅？",
             "We were billed twice for March. Please refund the duplicate today "
             "or we will cancel our plan."),
            ("这个请求有多紧急？",
             "服务器刚刚宕机，线上所有订单都下不了单，客户已经在投诉了。"),
        ]
        for question, state in cases:
            req = DecisionRequest(type="yes_no", question=question, state=state)
            raw = client.candidates(build_messages(req))
            res = interpret(raw.candidates, req, model=raw.model,
                            latency_ms=raw.latency_ms)
            top = sorted(raw.candidates.items(), key=lambda kv: -kv[1])[:4]
            print("   问: %s" % question)
            print("     候选: %s" % {k: round(v, 4) for k, v in top})
            print("     结论: %s（%.1f%%，%.0fms）"
                  % ("是" if res.answer else "否", res.probability * 100, res.latency_ms))

    print("\n④ 应用层读状态（情绪 + 危机关键词预筛）")
    state = ds.probe_state("今天真的太累了，一整天什么都不想做", is_voice=True)
    print("   情绪:", state.emotion.to_dict())
    print("   危机:", state.crisis.to_dict())
    print("   语气提示:", state.tone_hint or "（无）")

    print("\n⑤ 归还租约，等空闲回收（阈值 20s，检查周期 5s）")
    t0 = time.time()
    gone = False
    for _ in range(60):
        time.sleep(1)
        if not port_open(port):
            gone = True
            break
    print("   回收用时 %.1fs，端口已关闭: %s" % (time.time() - t0, gone))
    print("   回收后显存:", vram())
    assert gone, "空闲回收没生效"

    print("\n⑥ 再借一次租约（应能重新拉起）")
    t0 = time.time()
    with ds.decision_lease(pool):
        print("   重新拉起用时 %.1fs，端口在听: %s"
              % (time.time() - t0, port_open(port)))
        assert port_open(port), "没重新拉起来"

    print("\n闭环验证通过：拉起 → 决策 → 空闲回收 → 再拉起")
    return 0


if __name__ == "__main__":
    sys.exit(main())
