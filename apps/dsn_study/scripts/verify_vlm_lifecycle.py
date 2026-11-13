#!/usr/bin/env python3
"""本地 VLM 的「拉起 → 空闲回收 → 再拉起」闭环验证。

真实拉起 llama-server（需 GPU），用很短的空闲阈值把整条链路跑一遍。
"""
from __future__ import annotations

import os
import socket
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


def main() -> int:
    from apps.dsn_study.config import Config
    from apps.dsn_study.models import vlm_service

    Config.VLM_IDLE_TIMEOUT = 8          # 8 秒后回收
    Config.VLM_IDLE_SHUTDOWN = True
    Config.RESOURCE_IDLE_SHUTDOWN = True
    Config.VOICE_IDLE_CHECK_INTERVAL = 3  # 回收器检查周期（池级）
    port = int(Config.VLM_PORT)

    print("① 第一次借租约（应按需拉起）")
    t0 = time.time()
    with vlm_service.vlm_lease() as lease:
        print("   拉起用时 %.1fs，端口在听: %s" % (time.time() - t0, port_open(port)))
        assert port_open(port), "服务没起来"

    print("② 归还租约，等空闲回收（阈值 8s，检查周期 3s）")
    t0 = time.time()
    gone = False
    for _ in range(40):
        time.sleep(1)
        if not port_open(port):
            gone = True
            break
    print("   回收用时 %.1fs，端口已关闭: %s" % (time.time() - t0, gone))
    assert gone, "空闲回收没生效"

    print("③ 再借一次租约（应能重新拉起）")
    t0 = time.time()
    with vlm_service.vlm_lease() as lease:
        print("   重新拉起用时 %.1fs，端口在听: %s"
              % (time.time() - t0, port_open(port)))
        assert port_open(port), "没重新拉起来"

    print("\n闭环验证通过：拉起 → 回收 → 再拉起")
    return 0


if __name__ == "__main__":
    sys.exit(main())
