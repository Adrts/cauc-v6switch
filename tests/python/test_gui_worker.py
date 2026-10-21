"""GUI 线程模型与 MainWindow 用例（Tk 隐藏窗口，无需真实 DLL）。

覆盖设计文档 §8 测试分层②中的「GUI 线程模型：工作线程调度与队列回传」
与 MainWindow 交互用例（默认选中、控件可用性、虚拟适配器过滤、刷新同步）。
"""

from __future__ import annotations

import queue
import threading
import time

import pytest

tk = pytest.importorskip("tkinter")

from v6switch.gui import MainWindow, run_async  # noqa: E402


@pytest.fixture()
def root():
    """隐藏的 Tk 根窗口；无图形环境时跳过。"""
    try:
        r = tk.Tk()
    except tk.TclError as exc:  # 无显示/无 Tk 运行时
        pytest.skip(f"Tk 不可用：{exc}")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


def _wait_result(out_queue, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return out_queue.get(timeout=0.05)
        except queue.Empty:
            continue
    raise AssertionError("等待后台线程结果超时")


def test_run_async_returns_result():
    out = queue.Queue()
    got = []
    run_async(lambda: 42, out, got.append, got.append)
    callback, payload = _wait_result(out)
    callback(payload)  # 模拟主线程轮询取出并回调
    assert got == [42]


def test_run_async_failure_propagates_as_object():
    out = queue.Queue()
    got = []

    def boom():
        raise ValueError("boom")

    run_async(boom, out, got.append, got.append)
    callback, payload = _wait_result(out)
    callback(payload)
    assert len(got) == 1
    assert isinstance(got[0], ValueError)
    assert "boom" in str(got[0])


def test_run_async_runs_off_main_thread():
    out = queue.Queue()
    got = []
    run_async(lambda: threading.current_thread().name, out, got.append, got.append)
    callback, payload = _wait_result(out)
    callback(payload)
    assert got[0] != threading.main_thread().name


# ---- MainWindow 选中态与控件可用性（回归：列表与状态面板同源） ----

def _wait_idle(root, win, timeout=10.0):
    deadline = time.monotonic() + timeout
    while getattr(win, "_busy", True) and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    root.update()


def _button_enabled(btn) -> bool:
    return "disabled" not in btn.state()


def test_mainwindow_selection_enables_actions(root, monkeypatch, tmp_path):
    from fake_dll import FakeDll

    from v6switch.bindings.v6core import V6Core

    monkeypatch.setattr("v6switch.presets.config_path", lambda: tmp_path / "config.yaml")
    win = MainWindow(root, V6Core(dll=FakeDll()))
    _wait_idle(root, win)

    # 默认过滤虚拟适配器，仅 1 行，且默认选中首个 up 的物理适配器
    assert len(win.tree.get_children()) == 1
    assert win._selected() is not None
    assert win._selected()["if_index"] == 12
    assert _button_enabled(win.btn_switch) and _button_enabled(win.btn_reset)

    # 状态面板同步
    assert win.lbl_mode.cget("text") == "双栈"
    assert win.lbl_ipv4.cget("text") == "10.132.0.8"

    # 清空选中 → 变更按钮禁用（§5.3.2 空闲+无选中）
    win.tree.selection_remove(*win.tree.selection())
    root.update()
    assert win._selected() is None
    assert not _button_enabled(win.btn_switch) and not _button_enabled(win.btn_reset)
    assert _button_enabled(win.btn_refresh)


def test_mainwindow_virtual_filter_toggle(root, monkeypatch, tmp_path):
    from fake_dll import FakeDll

    from v6switch.bindings.v6core import V6Core

    monkeypatch.setattr("v6switch.presets.config_path", lambda: tmp_path / "config.yaml")
    win = MainWindow(root, V6Core(dll=FakeDll()))
    _wait_idle(root, win)
    assert len(win.tree.get_children()) == 1

    win.var_virtual.set(True)
    win._populate_table()
    root.update()
    assert len(win.tree.get_children()) == 2  # 勾选后显示虚拟适配器
    assert win.tree.item("1", "tags") == ("virtual",)


# ---- 刷新后状态面板同步（回归：重填充后选中行未变时事件不发射） ----

def test_mainwindow_refresh_updates_status_panel(root, monkeypatch, tmp_path):
    from fake_dll import FakeDll

    from v6switch.bindings.v6core import V6Core

    monkeypatch.setattr("v6switch.presets.config_path", lambda: tmp_path / "config.yaml")
    fake = FakeDll()
    win = MainWindow(root, V6Core(dll=fake))
    _wait_idle(root, win)
    assert win.lbl_ipv4.cget("text") == "10.132.0.8"
    assert win.lbl_mode.cget("text") == "双栈"

    # 模拟"切换 IPv6-only 后点刷新"：同一 if_index 的地址状态变化、行数不变
    fake.adapters[0]["ipv4"] = []
    fake.adapters[0]["ipv6"] = ["2001:da8:1005::1008"]
    win._refresh_adapters()
    _wait_idle(root, win)

    # 表格与状态面板都必须反映新数据
    assert win.lbl_ipv4.cget("text") == "已关闭"
    assert win.lbl_mode.cget("text") == "IPv6-only"
    assert win.tree.item("0", "values")[4] == "已关闭"


def test_mainwindow_list_failure_shows_error(root, monkeypatch, tmp_path):
    from fake_dll import FakeDll

    from v6switch.bindings.v6core import V6Core

    monkeypatch.setattr("v6switch.presets.config_path", lambda: tmp_path / "config.yaml")
    errors: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "v6switch.gui.messagebox.showerror",
        lambda title, message, **kwargs: errors.append((title, message)),
    )
    # 需要 300 KB：扩容重试（256 KB）后仍不足 → 触发加载失败分支
    win = MainWindow(root, V6Core(dll=FakeDll(buffer_need=300_000)))
    _wait_idle(root, win)

    assert win.status_label.cget("text") == "加载失败"
    assert errors and errors[0][0] == "罗列网络连接失败"
