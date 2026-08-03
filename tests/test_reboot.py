# tests/test_reboot.py
# /reboot 指令测试 — 自动重启控制台

import os
import sys
import threading
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as main_mod


def test_restart_process_uses_same_command():
    """_restart_process 应用同一命令行重建进程"""
    import main
    with mock.patch.object(main.os, "execv") as fake_execv:
        main._restart_process()
    fake_execv.assert_called_once_with(
        sys.executable, [sys.executable] + sys.argv)


def test_reboot_sets_flag_and_event():
    """/reboot 应置位重启标记并触发 shutdown_event"""
    import main
    main._REBOOT_REQUESTED = False
    evt = threading.Event()

    main._execute_command("/reboot", None, None, None, None, None, evt)

    assert main._REBOOT_REQUESTED is True
    assert evt.is_set()


def test_stop_does_not_set_reboot_flag():
    """/stop 不应置位重启标记"""
    import main
    main._REBOOT_REQUESTED = False
    evt = threading.Event()

    main._execute_command("/stop", None, None, None, None, None, evt)

    assert main._REBOOT_REQUESTED is False
    assert evt.is_set()


if __name__ == "__main__":
    test_restart_process_uses_same_command()
    test_reboot_sets_flag_and_event()
    test_stop_does_not_set_reboot_flag()
    print("\nALL REBOOT TESTS PASSED")
