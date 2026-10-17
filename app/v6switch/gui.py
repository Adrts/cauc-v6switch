"""PySide6 图形界面（唯一交付入口，设计文档 FR-7 / §5.3）。

五个功能区：A 适配器列表 / B 状态面板 / C 操作区 / E 全局与状态栏。
线程铁律：所有 DLL 操作经 QThread 工作线程执行，错误读取与转异常在工作线程
就地完成后经 signal 回传，主线程仅渲染与弹窗（§5.2 / §11）。
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import admin, core_ops
from .bindings.v6core import V6Core, V6DllNotFound, V6Error
from .presets import ConfigError, load_dns64

_WINDOW_TITLE = "CAUC IPv6 Switch"
_COL_HEADERS = ["名称", "描述", "状态", "IP 摘要", "IPv4 状态"]


class Worker(QThread):
    """工作线程：执行一个函数，结果/异常经 signal 回传主线程。"""

    ok = Signal(object)
    fail = Signal(object)

    def __init__(self, fn, *args, parent=None) -> None:
        super().__init__(parent)
        self._fn = fn
        self._args = args

    def run(self) -> None:
        try:
            self.ok.emit(self._fn(*self._args))
        except Exception as exc:  # 跨线程仅能传对象，异常对象原样回传
            self.fail.emit(exc)


def _net_mode(adapter: dict) -> str:
    """B1 模式标识：双栈 / IPv4-only / IPv6-only / 无 IP（ipv4[] 空即视为已关闭）。"""
    has4 = bool(adapter.get("ipv4"))
    has6 = bool(adapter.get("ipv6"))
    if has4 and has6:
        return "双栈"
    if has4:
        return "IPv4-only"
    if has6:
        return "IPv6-only"
    return "无 IP 地址"


class MainWindow(QMainWindow):
    def __init__(self, core: V6Core) -> None:
        super().__init__()
        self.core = core
        self.adapters: list[dict] = []
        self._worker: Worker | None = None
        self._pending_status: str | None = None
        self._dns64: list[str] = []
        self._dns64_error: str | None = None

        self.setWindowTitle(_WINDOW_TITLE)
        self.setMinimumSize(860, 640)
        self._build_ui()
        self._load_dns64_preview()
        self._set_busy(True, "正在加载网络连接…")
        self._refresh_adapters()

    # ---- UI 构建 ----

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)

        # A 适配器列表区
        group_a = QGroupBox("网络连接")
        lay_a = QVBoxLayout(group_a)
        self.table = QTableWidget(0, len(_COL_HEADERS))
        self.table.setHorizontalHeaderLabels(_COL_HEADERS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        lay_a.addWidget(self.table)
        row_a = QHBoxLayout()
        self.chk_virtual = QCheckBox("显示虚拟适配器")
        self.chk_virtual.toggled.connect(self._populate_table)
        row_a.addWidget(self.chk_virtual)
        row_a.addStretch(1)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self._on_refresh)
        row_a.addWidget(self.btn_refresh)
        lay_a.addLayout(row_a)
        root.addWidget(group_a, 3)

        # B 状态面板区
        group_b = QGroupBox("当前状态")
        form_b = QFormLayout(group_b)
        self.lbl_mode = QLabel("-")
        self.lbl_ipv4 = QLabel("-")
        self.lbl_ipv6 = QLabel("-")
        self.lbl_dns = QLabel("-")
        for lbl in (self.lbl_ipv4, self.lbl_ipv6, self.lbl_dns):
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form_b.addRow("模式：", self.lbl_mode)
        form_b.addRow("IPv4 地址：", self.lbl_ipv4)
        form_b.addRow("IPv6 地址：", self.lbl_ipv6)
        form_b.addRow("DNS：", self.lbl_dns)
        root.addWidget(group_b, 2)

        # C 操作区
        group_c = QGroupBox("操作")
        lay_c = QVBoxLayout(group_c)
        self.lbl_dns64 = QLabel("-")
        self.lbl_dns64.setWordWrap(True)
        lay_c.addWidget(self.lbl_dns64)
        row_c = QHBoxLayout()
        row_c.addStretch(1)
        self.btn_switch = QPushButton("切换 IPv6-only")
        self.btn_switch.clicked.connect(self._on_switch)
        self.btn_reset = QPushButton("重置")
        self.btn_reset.clicked.connect(self._on_reset)
        row_c.addWidget(self.btn_switch)
        row_c.addWidget(self.btn_reset)
        lay_c.addLayout(row_c)
        root.addWidget(group_c, 2)

        self.setCentralWidget(central)

        # E 状态栏
        self.status_label = QLabel("就绪")
        self.perm_label = QLabel("管理员" if admin.is_admin() else "未提权")
        self.statusBar().addWidget(self.status_label)
        self.statusBar().addPermanentWidget(self.perm_label)

    # ---- 数据加载与渲染 ----

    def _load_dns64_preview(self) -> None:
        """C1 DNS64 配置预览（只读，启动/刷新时更新）。"""
        try:
            self._dns64 = load_dns64()
            self._dns64_error = None
        except ConfigError as exc:
            self._dns64 = []
            self._dns64_error = str(exc)
        if self._dns64_error:
            self.lbl_dns64.setStyleSheet("color: red;")
            self.lbl_dns64.setText(f"DNS64 配置错误：{self._dns64_error}")
        else:
            self.lbl_dns64.setStyleSheet("")
            shown = "、".join(self._dns64)
            self.lbl_dns64.setText(
                f"DNS64（{len(self._dns64)} 条，来自 config.yaml，修改请编辑配置文件）：{shown}"
            )

    def _refresh_adapters(self) -> None:
        self._set_busy(True, "正在罗列网络连接…")
        self._worker = Worker(self.core.list_adapters, parent=self)
        self._worker.ok.connect(self._on_adapters_loaded)
        self._worker.fail.connect(self._on_worker_failed)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_adapters_loaded(self, adapters: object) -> None:
        self.adapters = adapters if isinstance(adapters, list) else []
        self._populate_table()
        self._load_dns64_preview()
        message = getattr(self, "_pending_status", None) or "就绪"
        self._pending_status = None
        self._set_busy(False, message)

    def _populate_table(self) -> None:
        show_virtual = self.chk_virtual.isChecked()
        rows = [a for a in self.adapters if show_virtual or not a.get("virtual")]
        previous = self._selected()
        self.table.setRowCount(len(rows))
        for r, a in enumerate(rows):
            ipv4 = a.get("ipv4") or []
            values = [
                a.get("name", ""),
                a.get("desc", ""),
                "已连接" if a.get("status") == "up" else "断开",
                "、".join((a.get("ipv4") or a.get("ipv6") or ["-"])[:2]),
                "已关闭" if not ipv4 else "开启",
            ]
            for c, text in enumerate(values):
                item = QTableWidgetItem(str(text))
                item.setData(Qt.ItemDataRole.UserRole, a)  # 挂载适配器数据
                self.table.setItem(r, c, item)
        # 恢复原选中；否则默认选中首个已连接的非虚拟适配器
        target = None
        if previous:
            target = next((a for a in rows if a.get("if_index") == previous.get("if_index")), None)
        if target is None:
            target = next((a for a in rows if a.get("status") == "up" and not a.get("virtual")), None)
        if target is not None:
            r = rows.index(target)
            self.table.selectRow(r)
        else:
            self._update_status_panel(None)
        self._update_buttons()

    def _selected(self) -> dict | None:
        items = self.table.selectedItems()
        if not items:
            return None
        data = items[0].data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else None

    def _on_selection_changed(self) -> None:
        self._update_status_panel(self._selected())
        self._update_buttons()

    def _update_status_panel(self, adapter: dict | None) -> None:
        if not adapter:
            self.lbl_mode.setText("-")
            self.lbl_ipv4.setText("-")
            self.lbl_ipv6.setText("-")
            self.lbl_dns.setText("-")
            return
        self.lbl_mode.setText(_net_mode(adapter))
        ipv4 = "、".join(adapter.get("ipv4") or []) or "已关闭"
        ipv6 = "、".join(adapter.get("ipv6") or []) or "-"
        dns4 = "、".join(adapter.get("dns_v4") or [])
        dns6 = "、".join(adapter.get("dns_v6") or [])
        dns = dns6 if dns6 else "-"
        if dns4:
            dns = f"{dns4}（v4） / {dns}（v6）" if dns6 else f"{dns4}（v4）"
        self.lbl_ipv4.setText(ipv4)
        self.lbl_ipv6.setText(ipv6)
        self.lbl_dns.setText(dns)

    # ---- 忙态与按钮可用性（§5.3.2 控件可用性规则） ----

    def _set_busy(self, busy: bool, message: str) -> None:
        self._busy = busy
        self.status_label.setText(message)
        for btn in (self.btn_refresh, self.btn_switch, self.btn_reset):
            btn.setEnabled(not busy)
        self._update_buttons()

    def _update_buttons(self) -> None:
        """空闲 + 无选中 → 变更按钮禁用；其余按忙态。"""
        if getattr(self, "_busy", False):
            return
        has_selection = self._selected() is not None
        self.btn_refresh.setEnabled(True)
        self.btn_switch.setEnabled(has_selection)
        self.btn_reset.setEnabled(has_selection)

    # ---- 操作（C2/C3） ----

    def _on_refresh(self) -> None:
        self._refresh_adapters()

    def _on_switch(self) -> None:
        adapter = self._selected()
        if not adapter:
            return
        # 执行前重读 config.yaml（所见即所执）
        try:
            servers = load_dns64()
        except ConfigError as exc:
            self._load_dns64_preview()
            QMessageBox.warning(self, "DNS64 配置错误", f"配置非法，拒绝执行：\n{exc}")
            return
        if_index = adapter.get("if_index")
        name = adapter.get("name", "")
        notes = ""
        if _net_mode(adapter) == "IPv6-only":
            notes = "\n\n注意：当前已是 IPv6-only。"
        ret = QMessageBox.question(
            self,
            "确认切换",
            f"将「{name}」（索引 {if_index}）切换为 IPv6-only？\n\n"
            f"先写入 {len(servers)} 条 DNS64，再关闭 IPv4 绑定。\n"
            f"IPv4 资源将经公共 NAT64 服务访问。{notes}",
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        self._set_busy(True, "执行中：切换 IPv6-only…")
        self._worker = Worker(core_ops.switch_to_ipv6, self.core, if_index, name, servers, parent=self)
        self._worker.ok.connect(lambda _: self._on_op_done("切换完成"))
        self._worker.fail.connect(self._on_op_failed)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_reset(self) -> None:
        adapter = self._selected()
        if not adapter:
            return
        if_index = adapter.get("if_index")
        name = adapter.get("name", "")
        ret = QMessageBox.question(
            self,
            "确认重置",
            f"将「{name}」（索引 {if_index}）恢复默认网络配置？\n\n"
            "IPv4 绑定恢复开启，DNS 恢复自动获取。\n"
            "注意：原有静态 DNS 会被清除（非快照还原）。",
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        self._set_busy(True, "执行中：重置…")
        self._worker = Worker(core_ops.reset_adapter, self.core, if_index, name, parent=self)
        self._worker.ok.connect(lambda _: self._on_op_done("重置完成"))
        self._worker.fail.connect(self._on_op_failed)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_op_done(self, message: str) -> None:
        # 完成文案须在自动刷新结束后仍可见（§5.3.1 E4），经 _pending_status 延后展示
        self._pending_status = message
        self._refresh_adapters()

    def _on_op_failed(self, exc: object) -> None:
        text = str(exc)
        self._pending_status = f"操作失败：{text[:80]}"
        if isinstance(exc, core_ops.PartialSwitchError):
            QMessageBox.critical(
                self,
                "部分失败",
                f"{exc}\n\n底层错误：{exc.cause}",
            )
        elif isinstance(exc, core_ops.TargetMismatchError):
            QMessageBox.warning(self, "目标已变化", text)
        elif isinstance(exc, V6Error):
            QMessageBox.critical(self, "操作失败", text)
        else:
            QMessageBox.critical(self, "意外错误", text)
        self._refresh_adapters()

    def _on_worker_failed(self, exc: object) -> None:
        """列表加载失败（非操作类）。"""
        self._set_busy(False, "加载失败")
        QMessageBox.critical(self, "罗列网络连接失败", str(exc))

    def closeEvent(self, event) -> None:
        """操作执行中禁止关闭窗口，避免 QThread 中途销毁（网络操作须完整收尾）。"""
        if getattr(self, "_busy", False) and self._worker is not None and self._worker.isRunning():
            event.ignore()
            QMessageBox.information(self, "请稍候", "有操作正在执行，请等待完成后关闭。")
            return
        event.accept()


def run() -> int:
    """GUI 入口：提权自检 → 加载 DLL（缺失弹窗）→ 主窗口。"""
    admin.ensure_admin(["v6switch"], gui=True)

    app = QApplication(sys.argv)
    try:
        core = V6Core()
    except V6DllNotFound as exc:
        QMessageBox.critical(
            None,
            "缺少 v6core.dll",
            "未找到底层库 v6core.dll。\n"
            "请将其与本程序放在同一目录（交付形态为 v6switch.exe + v6core.dll 两文件）。\n\n"
            f"{exc}",
        )
        return 1
    window = MainWindow(core)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
