"""GUI 线程模型用例（纯 Python，offscreen 平台，无需真实 DLL）。

覆盖设计文档 §8 测试分层②中的「GUI 线程模型：工作线程调度与 signal 回传」。
"""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from v6switch.gui import Worker  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def run_worker(qapp, fn, *args):
    """在主线程事件循环中等待 Worker 完成，返回 (结果/异常) 信标序列。"""
    events = []
    worker = Worker(fn, *args)
    worker.ok.connect(lambda v: events.append(("ok", v)))
    worker.fail.connect(lambda e: events.append(("fail", e)))
    worker.start()
    deadline = time.monotonic() + 10
    while not events and worker.isRunning() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    worker.wait()
    qapp.processEvents()
    return events


def test_worker_returns_result(qapp):
    events = run_worker(qapp, lambda: 42)
    assert events == [("ok", 42)]


def test_worker_passes_args(qapp):
    events = run_worker(qapp, lambda a, b: a + b, 1, 2)
    assert events == [("ok", 3)]


def test_worker_failure_propagates_as_object(qapp):
    def boom():
        raise ValueError("boom")

    events = run_worker(qapp, boom)
    assert len(events) == 1
    kind, exc = events[0]
    assert kind == "fail"
    assert isinstance(exc, ValueError)
    assert "boom" in str(exc)


def test_worker_runs_off_main_thread(qapp):
    import threading

    events = run_worker(qapp, lambda: threading.current_thread().name)
    kind, name = events[0]
    assert kind == "ok"
    assert name != threading.main_thread().name


# ---- MainWindow 选中态与控件可用性（回归：UserRole 读写一致） ----

def _wait_idle(qapp, win, timeout=5.0):
    deadline = time.monotonic() + timeout
    while getattr(win, "_busy", True) and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    qapp.processEvents()


def test_mainwindow_selection_enables_actions(qapp, monkeypatch, tmp_path):
    from fake_dll import FakeDll
    from v6switch.bindings.v6core import V6Core
    from v6switch.gui import MainWindow

    monkeypatch.setattr("v6switch.presets.config_path", lambda: tmp_path / "config.yaml")
    core = V6Core(dll=FakeDll())  # 两个适配器：以太网(up, 非虚拟) + vEthernet(虚拟)
    win = MainWindow(core)
    try:
        _wait_idle(qapp, win)
        # 默认过滤虚拟适配器，仅 1 行，且默认选中首个 up 的物理适配器
        assert win.table.rowCount() == 1
        assert win._selected() is not None
        assert win._selected()["if_index"] == 12
        assert win.btn_switch.isEnabled() and win.btn_reset.isEnabled()

        # 状态面板同步
        assert "IPv6-only" not in win.lbl_mode.text()  # ipv4 非空 → 非IPv6-only
        assert win.lbl_ipv4.text() == "10.132.0.8"

        # 清空选中 → 变更按钮禁用（§5.3.2 空闲+无选中）
        win.table.clearSelection()
        qapp.processEvents()
        assert win._selected() is None
        assert not win.btn_switch.isEnabled() and not win.btn_reset.isEnabled()
        assert win.btn_refresh.isEnabled()
    finally:
        win.deleteLater()
        qapp.processEvents()


def test_mainwindow_virtual_filter_toggle(qapp, monkeypatch, tmp_path):
    from fake_dll import FakeDll
    from v6switch.bindings.v6core import V6Core
    from v6switch.gui import MainWindow

    monkeypatch.setattr("v6switch.presets.config_path", lambda: tmp_path / "config.yaml")
    win = MainWindow(V6Core(dll=FakeDll()))
    try:
        _wait_idle(qapp, win)
        assert win.table.rowCount() == 1
        win.chk_virtual.setChecked(True)
        qapp.processEvents()
        assert win.table.rowCount() == 2  # 勾选后显示虚拟适配器
    finally:
        win.deleteLater()
        qapp.processEvents()
