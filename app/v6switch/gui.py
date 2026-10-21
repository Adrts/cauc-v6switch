"""Tkinter 图形界面（唯一交付入口，设计文档 FR-7 / §5.3）。

五个功能区：A 适配器列表 / B 状态面板 / C 操作区 / E 全局与状态栏。
线程铁律：所有 DLL 操作经后台线程执行，错误读取与转异常在工作线程就地完成，
结果经队列回主线程渲染（Tk 非线程安全，主线程仅渲染与弹窗）。
"""

from __future__ import annotations

import ctypes
import queue
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from ctypes import wintypes
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable

from . import admin, core_ops
from .bindings.v6core import V6Core, V6DllNotFound, V6Error
from .presets import ConfigError, load_dns64

_WINDOW_TITLE = "CAUC IPv6 Switch"

# 应用图标（窗口标题栏 + 任务栏）；frozen 时随 --add-data 收集到 _MEIPASS/v6switch/resources
_APP_ICON = Path(__file__).resolve().parent / "resources" / "appicon.png"

_SPI_GETWORKAREA = 0x0030

# 视觉样式：浅灰页面底 + 白色卡片 + 细边框，用底色对比与明确边界强化分区感
_BG_COLOR = "#F2F4F7"
_CARD_COLOR = "#FFFFFF"
_CARD_BORDER = "#D8DEE7"
_DIVIDER_COLOR = "#EAEEF4"
_TITLE_COLOR = "#1F2937"
_MUTED_COLOR = "#5B6675"
_ERROR_COLOR = "#C0392B"
_ACCENT_COLOR = "#3D6FB4"


def _work_area(root: tk.Tk) -> tuple[int, int, int, int]:
    """返回任务栏之外的屏幕工作区（左、上、宽、高）；失败时回退到整屏。"""
    try:
        rect = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(
            _SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
        ):
            return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    except Exception:
        pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def run_async(
    fn: Callable[[], Any],
    out_queue: queue.Queue[tuple[Callable[[Any], None], Any]],
    on_ok: Callable[[Any], None],
    on_fail: Callable[[Exception], None],
) -> None:
    """在后线程执行 fn，结果/异常对象经队列回传（由主线程轮询取出）。"""
    def worker() -> None:
        try:
            result = fn()
        except Exception as exc:  # 跨线程仅能传对象，异常对象原样回传
            out_queue.put((on_fail, exc))
        else:
            out_queue.put((on_ok, result))

    threading.Thread(target=worker, daemon=True).start()


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


class MainWindow:
    """主窗口：A/B/C/E 四区 + 后台线程调度。"""

    def __init__(self, root: tk.Tk, core: V6Core) -> None:
        self.root = root
        self.core = core
        self.adapters: list[dict] = []
        self._rows: list[dict] = []
        self._busy = False
        self._pending_status: str | None = None
        self._dns64: list[str] = []
        self._dns64_error: str | None = None
        self._queue: queue.Queue[tuple[Callable[[Any], None], Any]] = queue.Queue()
        self._closing = False
        self._poll_after_id: str | None = None

        root.title(_WINDOW_TITLE)
        self._set_icon()
        self._build_ui()
        self._metrics_finalized = False
        self._apply_window_metrics()  # 先用占位内容给出临时尺寸
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._poll_queue()
        self._load_dns64_preview()
        self._set_busy(True, "正在加载网络连接…")
        self._refresh_adapters()

    # ---- UI 构建 ----

    def _set_icon(self) -> None:
        """设置窗口图标（PNG 需 Tk ≥ 8.6，失败时静默降级）。"""
        if not _APP_ICON.is_file():
            return
        try:
            self._icon_image = tk.PhotoImage(file=str(_APP_ICON))
            self.root.iconphoto(True, self._icon_image)
        except tk.TclError:
            pass

    def _build_ui(self) -> None:
        root = self.root
        root.configure(background=_BG_COLOR)
        root.columnconfigure(0, weight=1)

        # 统一控件内边距与表格行高；行高随 DPI 字体高度自适应，避免高缩放下文字被裁切
        scale = max(float(root.tk.call("tk", "scaling")) / (96.0 / 72.0), 1.0)

        def px(value: int) -> int:
            return max(1, round(value * scale))

        # 仅列表区参与伸缩；状态面板与操作区保持请求高度，窗口变小时不会被挤压遮挡
        root.rowconfigure(0, weight=1, minsize=px(140))
        root.rowconfigure(1, weight=0)
        root.rowconfigure(2, weight=0)

        default_font = tkfont.nametofont("TkDefaultFont")
        title_font = default_font.copy()
        title_font.configure(weight="bold", size=default_font.cget("size") + 1)
        self._title_font = title_font  # 保持引用，避免字体对象被回收

        linespace = default_font.metrics("linespace")
        style = ttk.Style(root)
        style.configure("TButton", padding=(px(12), px(6)))
        style.configure("Treeview", rowheight=linespace + px(13))
        style.configure("Treeview.Heading", padding=(px(8), px(7)))
        # 卡片为白底，复选框文字区需同步底色，避免出现灰块
        style.configure("Card.TCheckbutton", background=_CARD_COLOR)

        pad_x = px(14)
        gap = px(6)

        def card(title: str, row: int, pady: tuple[int, int], stretch: bool) -> tk.Frame:
            """白色卡片分区：细边框 + 粗体标题 + 标题下分隔线，返回内容容器。"""
            outer = tk.Frame(
                root,
                background=_CARD_COLOR,
                highlightbackground=_CARD_BORDER,
                highlightcolor=_CARD_BORDER,
                highlightthickness=1,
                borderwidth=0,
            )
            outer.grid(
                row=row,
                column=0,
                sticky="nsew" if stretch else "ew",
                padx=pad_x,
                pady=pady,
            )
            header = tk.Frame(outer, background=_CARD_COLOR)
            header.pack(fill="x", padx=px(14), pady=(px(7), 0))
            tk.Frame(header, background=_ACCENT_COLOR, width=px(3)).pack(
                side="left", fill="y"
            )
            tk.Label(
                header,
                text=title,
                background=_CARD_COLOR,
                foreground=_TITLE_COLOR,
                font=title_font,
                anchor="w",
            ).pack(side="left", fill="x", expand=True, padx=(px(8), 0))
            tk.Frame(outer, background=_DIVIDER_COLOR, height=px(1)).pack(
                fill="x", padx=px(14), pady=(px(5), 0)
            )
            body = tk.Frame(outer, background=_CARD_COLOR)
            body.pack(fill="both", expand=True, padx=px(14), pady=px(9))
            return body

        # A 适配器列表区
        body_a = card("网络连接", 0, (px(12), gap), True)
        body_a.columnconfigure(0, weight=1)
        body_a.rowconfigure(0, weight=1)

        columns = ("name", "desc", "status", "ip", "ipv4_state")
        headers = {
            "name": "名称",
            "desc": "描述",
            "status": "状态",
            "ip": "IP 摘要",
            "ipv4_state": "IPv4 状态",
        }
        widths = {"name": 90, "desc": 140, "status": 60, "ip": 110, "ipv4_state": 70}
        self._col_min = {col: px(widths[col]) for col in widths}
        self._col_ratios = {
            "name": 0.16,
            "desc": 0.34,
            "status": 0.10,
            "ip": 0.26,
            "ipv4_state": 0.14,
        }
        self.tree = ttk.Treeview(
            body_a, columns=columns, show="headings", selectmode="browse", height=8
        )
        for col in columns:
            self.tree.heading(col, text=headers[col])
            self.tree.column(
                col,
                width=self._col_min[col],
                minwidth=self._col_min[col],
                stretch=False,
                anchor="w",
            )
        self.tree.tag_configure("virtual", foreground="#888888")
        self.tree.grid(row=0, column=0, sticky="nsew")
        vscroll = ttk.Scrollbar(body_a, orient="vertical", command=self.tree.yview)
        vscroll.grid(row=0, column=1, sticky="ns", padx=(px(4), 0))
        self.tree.configure(yscrollcommand=vscroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_selection_changed)
        self.tree.bind("<Configure>", self._on_tree_resize)

        row_a = tk.Frame(body_a, background=_CARD_COLOR)
        row_a.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(px(9), 0))
        self.var_virtual = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            row_a,
            text="显示虚拟适配器",
            variable=self.var_virtual,
            command=self._populate_table,
            style="Card.TCheckbutton",
        ).pack(side="left")
        self.btn_refresh = ttk.Button(row_a, text="刷新", command=self._on_refresh)
        self.btn_refresh.pack(side="right")

        # B 状态面板区（固定高度 + 内部滚动，避免长地址换行导致上方表格高度跳动）
        body_b = card("当前状态", 1, (gap, gap), False)
        body_b.columnconfigure(0, weight=1)

        status_canvas = tk.Canvas(
            body_b,
            height=px(120),
            background=_CARD_COLOR,
            highlightthickness=0,
            borderwidth=0,
        )
        status_canvas.grid(row=0, column=0, sticky="ew")
        status_scroll = ttk.Scrollbar(
            body_b, orient="vertical", command=status_canvas.yview
        )
        status_scroll.grid(row=0, column=1, sticky="ns", padx=(px(4), 0))
        status_canvas.configure(yscrollcommand=status_scroll.set)

        status_inner = tk.Frame(status_canvas, background=_CARD_COLOR)
        status_window = status_canvas.create_window((0, 0), window=status_inner, anchor="nw")
        status_inner.columnconfigure(1, weight=1)

        self.lbl_mode = tk.Label(
            status_inner, text="-", background=_CARD_COLOR,
            foreground=_TITLE_COLOR, anchor="w", justify="left",
        )
        self.lbl_ipv4 = tk.Label(
            status_inner, text="-", background=_CARD_COLOR,
            foreground=_TITLE_COLOR, anchor="w", justify="left", wraplength=px(600),
        )
        self.lbl_ipv6 = tk.Label(
            status_inner, text="-", background=_CARD_COLOR,
            foreground=_TITLE_COLOR, anchor="w", justify="left", wraplength=px(600),
        )
        self.lbl_dns = tk.Label(
            status_inner, text="-", background=_CARD_COLOR,
            foreground=_TITLE_COLOR, anchor="w", justify="left", wraplength=px(600),
        )
        rows_b = [
            ("模式：", self.lbl_mode),
            ("IPv4 地址：", self.lbl_ipv4),
            ("IPv6 地址：", self.lbl_ipv6),
            ("DNS：", self.lbl_dns),
        ]
        for r, (title, widget) in enumerate(rows_b):
            tk.Label(
                status_inner, text=title, background=_CARD_COLOR,
                foreground=_MUTED_COLOR, anchor="nw",
            ).grid(row=r, column=0, sticky="nw", pady=px(4))
            widget.grid(row=r, column=1, sticky="nw", pady=px(4))

        def _sync_scroll(_event: tk.Event = None) -> None:
            status_canvas.configure(scrollregion=status_canvas.bbox("all"))

        def _sync_width(event: tk.Event) -> None:
            status_canvas.itemconfigure(status_window, width=event.width)

        def _wrap_status(event: tk.Event) -> None:
            wrap = max(event.width - px(150), px(200))
            for lbl in (self.lbl_ipv4, self.lbl_ipv6, self.lbl_dns):
                if int(lbl.cget("wraplength")) != wrap:
                    lbl.configure(wraplength=wrap)

        status_inner.bind("<Configure>", _sync_scroll)
        status_canvas.bind("<Configure>", _sync_width)
        status_canvas.bind("<Configure>", _wrap_status, add="+")

        # C 操作区
        body_c = card("操作", 2, (gap, px(12)), False)
        body_c.columnconfigure(0, weight=1)
        self.lbl_dns64 = tk.Label(
            body_c, text="-", background=_CARD_COLOR, foreground=_MUTED_COLOR,
            anchor="w", justify="left", wraplength=px(700),
        )
        self.lbl_dns64.grid(row=0, column=0, sticky="ew", pady=(0, px(7)))
        row_c = tk.Frame(body_c, background=_CARD_COLOR)
        row_c.grid(row=1, column=0, sticky="e")
        self.btn_switch = ttk.Button(row_c, text="切换 IPv6-only", command=self._on_switch)
        self.btn_switch.pack(side="right", padx=(12, 0))
        self.btn_reset = ttk.Button(row_c, text="重置", command=self._on_reset)
        self.btn_reset.pack(side="right")

        def _wrap_dns64(event: tk.Event) -> None:
            wrap = max(event.width - px(28), px(200))
            if int(self.lbl_dns64.cget("wraplength")) != wrap:
                self.lbl_dns64.configure(wraplength=wrap)

        body_c.bind("<Configure>", _wrap_dns64)

        # E 状态栏（分隔线 + 左右状态）
        separator = tk.Frame(root, background=_CARD_BORDER, height=px(1))
        separator.grid(row=3, column=0, sticky="ew", padx=pad_x, pady=(px(8), 0))
        bar = tk.Frame(root, background=_BG_COLOR)
        bar.grid(row=4, column=0, sticky="ew", padx=pad_x, pady=(px(6), px(9)))
        bar.columnconfigure(0, weight=1)
        self.status_label = tk.Label(
            bar, text="就绪", background=_BG_COLOR, foreground=_MUTED_COLOR,
        )
        self.status_label.grid(row=0, column=0, sticky="w")
        self.perm_label = tk.Label(
            bar, text="管理员" if admin.is_admin() else "未提权",
            background=_BG_COLOR, foreground=_MUTED_COLOR,
        )
        self.perm_label.grid(row=0, column=1, sticky="e")

    def _on_tree_resize(self, event: tk.Event) -> None:
        """按表格实际宽度比例分配列宽，最小窗口下各列也能完整显示。"""
        width = event.width - 2
        if width <= 1 or width == getattr(self, "_last_tree_width", None):
            return
        self._last_tree_width = width
        if width < sum(self._col_min.values()):
            return
        widths = {
            col: max(self._col_min[col], round(width * ratio))
            for col, ratio in self._col_ratios.items()
        }
        # 舍入误差计入描述列，保证列宽总和与表格宽度一致
        widths["desc"] += width - sum(widths.values())
        for col, col_width in widths.items():
            self.tree.column(col, width=col_width)

    def _apply_window_metrics(self) -> None:
        """按屏幕工作区与内容请求尺寸确定窗口大小，避免小屏/任务栏遮挡底部内容。"""
        root = self.root
        root.update_idletasks()
        req_h = root.winfo_reqheight()
        scale = max(float(root.tk.call("tk", "scaling")) / (96.0 / 72.0), 1.0)

        def px(value: int) -> int:
            return max(1, round(value * scale))

        left, top, work_w, work_h = _work_area(root)
        # 预留窗口边框、标题栏与桌面边距
        avail_w = max(work_w - 48, 480)
        avail_h = max(work_h - 64, 420)
        # 最小尺寸：固定区完整显示 + 列表区约 140px（标题行 + 约 3 行数据）
        fixed_h = req_h - self.tree.winfo_reqheight()
        width = min(max(px(720), 480), avail_w)
        height = min(max(fixed_h + px(140), px(560)), avail_h)
        root.minsize(width, height)
        x = left + max((work_w - width) // 2, 0)
        y = top + max((work_h - height) // 2, 0)
        # 启动即采用最小尺寸，由用户按需放大
        root.geometry(f"{width}x{height}+{x}+{y}")

    def _finalize_window_metrics(self) -> None:
        """首次加载完成后按真实内容重算窗口尺寸（仅执行一次）。"""
        if self._metrics_finalized:
            return
        self._metrics_finalized = True
        self._apply_window_metrics()

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
            self.lbl_dns64.configure(
                text=f"DNS64 配置错误：{self._dns64_error}", foreground=_ERROR_COLOR
            )
        else:
            count = len(self._dns64)
            self.lbl_dns64.configure(
                text=f"已启用 {count} 条 DNS64（来自 config.yaml，修改请编辑配置文件）",
                foreground=_MUTED_COLOR,
            )

    def _refresh_adapters(self) -> None:
        self._set_busy(True, "正在罗列网络连接…")
        self._run(self.core.list_adapters, self._on_adapters_loaded, self._on_worker_failed)

    def _on_adapters_loaded(self, adapters: object) -> None:
        self.adapters = adapters if isinstance(adapters, list) else []
        self._populate_table()
        self._load_dns64_preview()
        message = self._pending_status or "就绪"
        self._pending_status = None
        self._set_busy(False, message)
        self._finalize_window_metrics()

    def _populate_table(self) -> None:
        show_virtual = self.var_virtual.get()
        rows = [a for a in self.adapters if show_virtual or not a.get("virtual")]
        previous = self._selected()
        self._rows = rows
        self.tree.delete(*self.tree.get_children())
        for r, a in enumerate(rows):
            ipv4 = a.get("ipv4") or []
            values = (
                a.get("name", ""),
                a.get("desc", ""),
                "已连接" if a.get("status") == "up" else "断开",
                "、".join((a.get("ipv4") or a.get("ipv6") or ["-"])[:2]),
                "已关闭" if not ipv4 else "开启",
            )
            tags = ("virtual",) if a.get("virtual") else ()
            self.tree.insert("", "end", iid=str(r), values=values, tags=tags)
        # 恢复原选中；否则默认选中首个已连接的非虚拟适配器
        target = None
        if previous:
            target = next(
                (a for a in rows if a.get("if_index") == previous.get("if_index")), None
            )
        if target is None:
            target = next(
                (a for a in rows if a.get("status") == "up" and not a.get("virtual")), None
            )
        if target is not None:
            iid = str(rows.index(target))
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.see(iid)
        # 重填充后选中行未变化时 <<TreeviewSelect>> 可能不触发，显式同步状态面板
        self._update_status_panel(self._selected())
        self._update_buttons()

    def _selected(self) -> dict | None:
        selected = self.tree.selection()
        if not selected:
            return None
        try:
            return self._rows[int(selected[0])]
        except (ValueError, IndexError):
            return None

    def _on_selection_changed(self, _event: object = None) -> None:
        self._update_status_panel(self._selected())
        self._update_buttons()

    def _update_status_panel(self, adapter: dict | None) -> None:
        if not adapter:
            for lbl in (self.lbl_mode, self.lbl_ipv4, self.lbl_ipv6, self.lbl_dns):
                lbl.configure(text="-")
            return
        self.lbl_mode.configure(text=_net_mode(adapter))
        ipv4_list = adapter.get("ipv4") or []
        ipv6_list = adapter.get("ipv6") or []
        ipv4 = ipv4_list[0] if ipv4_list else "已关闭"
        ipv6 = ipv6_list[0] if ipv6_list else "-"
        dns4 = "、".join(adapter.get("dns_v4") or [])
        dns6 = "、".join(adapter.get("dns_v6") or [])
        dns = dns6 if dns6 else "-"
        if dns4:
            dns = f"{dns4}（v4） / {dns}（v6）" if dns6 else f"{dns4}（v4）"
        self.lbl_ipv4.configure(text=ipv4)
        self.lbl_ipv6.configure(text=ipv6)
        self.lbl_dns.configure(text=dns)

    # ---- 忙态与按钮可用性（§5.3.2 控件可用性规则） ----

    def _set_busy(self, busy: bool, message: str) -> None:
        self._busy = busy
        self.status_label.configure(text=message)
        for btn in (self.btn_refresh, self.btn_switch, self.btn_reset):
            btn.state(["disabled"] if busy else ["!disabled"])
        self._update_buttons()

    def _update_buttons(self) -> None:
        """空闲 + 无选中 → 变更按钮禁用；其余按忙态。"""
        if self._busy:
            return
        has_selection = self._selected() is not None
        self.btn_refresh.state(["!disabled"])
        for btn in (self.btn_switch, self.btn_reset):
            btn.state(["!disabled"] if has_selection else ["disabled"])

    # ---- 后台执行与主线程回传 ----

    def _run(
        self,
        fn: Callable[[], Any],
        on_ok: Callable[[Any], None],
        on_fail: Callable[[Exception], None],
    ) -> None:
        run_async(fn, self._queue, on_ok, on_fail)

    def _poll_queue(self) -> None:
        try:
            while True:
                callback, payload = self._queue.get_nowait()
                callback(payload)
        except queue.Empty:
            pass
        if not self._closing:
            self._poll_after_id = self.root.after(50, self._poll_queue)

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
            messagebox.showwarning(
                "DNS64 配置错误", f"配置非法，拒绝执行：\n{exc}", parent=self.root
            )
            return
        if_index = adapter.get("if_index")
        name = adapter.get("name", "")
        notes = ""
        if _net_mode(adapter) == "IPv6-only":
            notes = "\n\n注意：当前已是 IPv6-only。"
        confirmed = messagebox.askyesno(
            "确认切换",
            f"将「{name}」（索引 {if_index}）切换为 IPv6-only？\n\n"
            f"先写入 {len(servers)} 条 DNS64，再关闭 IPv4 绑定。\n"
            f"IPv4 资源将经公共 NAT64 服务访问。{notes}",
            parent=self.root,
        )
        if not confirmed:
            return
        self._set_busy(True, "执行中：切换 IPv6-only…")
        self._run(
            lambda: core_ops.switch_to_ipv6(self.core, if_index, name, servers),
            lambda _: self._on_op_done("切换完成"),
            self._on_op_failed,
        )

    def _on_reset(self) -> None:
        adapter = self._selected()
        if not adapter:
            return
        if_index = adapter.get("if_index")
        name = adapter.get("name", "")
        confirmed = messagebox.askyesno(
            "确认重置",
            f"将「{name}」（索引 {if_index}）恢复默认网络配置？\n\n"
            "IPv4 绑定恢复开启，DNS 恢复自动获取。\n"
            "注意：原有静态 DNS 会被清除（非快照还原）。",
            parent=self.root,
        )
        if not confirmed:
            return
        self._set_busy(True, "执行中：重置…")
        self._run(
            lambda: core_ops.reset_adapter(self.core, if_index, name),
            lambda _: self._on_op_done("重置完成"),
            self._on_op_failed,
        )

    def _on_op_done(self, message: str) -> None:
        # 完成文案须在自动刷新结束后仍可见（§5.3.1 E4），经 _pending_status 延后展示
        self._pending_status = message
        self._refresh_adapters()

    def _on_op_failed(self, exc: Exception) -> None:
        text = str(exc)
        self._pending_status = f"操作失败：{text[:80]}"
        if isinstance(exc, core_ops.PartialSwitchError):
            messagebox.showerror(
                "部分失败", f"{exc}\n\n底层错误：{exc.cause}", parent=self.root
            )
        elif isinstance(exc, core_ops.TargetMismatchError):
            messagebox.showwarning("目标已变化", text, parent=self.root)
        elif isinstance(exc, V6Error):
            messagebox.showerror("操作失败", text, parent=self.root)
        else:
            messagebox.showerror("意外错误", text, parent=self.root)
        self._refresh_adapters()

    def _on_worker_failed(self, exc: Exception) -> None:
        """列表加载失败（非操作类）。"""
        self._set_busy(False, "加载失败")
        self._finalize_window_metrics()
        messagebox.showerror("罗列网络连接失败", str(exc), parent=self.root)

    def _on_close(self) -> None:
        """操作执行中禁止关闭窗口（网络操作须完整收尾）。"""
        if self._busy:
            messagebox.showinfo("请稍候", "有操作正在执行，请等待完成后关闭。", parent=self.root)
            return
        self._closing = True
        if self._poll_after_id is not None:
            try:
                self.root.after_cancel(self._poll_after_id)
            except tk.TclError:
                pass
            self._poll_after_id = None
        self.root.destroy()


def run() -> int:
    """GUI 入口：提权自检 → 加载 DLL（缺失弹窗）→ 主窗口。"""
    admin.ensure_admin(["v6switch"], gui=True)

    # Tk 不自动声明 DPI 感知；Windows 下声明后由系统按缩放比例渲染，避免位图拉伸发虚
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root = tk.Tk()
    root.withdraw()  # 先隐藏，DLL 加载失败弹窗后不残留空窗口
    try:
        core = V6Core()
    except V6DllNotFound as exc:
        messagebox.showerror(
            "缺少 v6core.dll",
            "未找到底层库 v6core.dll。\n"
            "请将其与本程序放在同一目录（即 v6switch 目录内的 v6switch.exe 旁）。\n\n"
            f"{exc}",
            parent=root,
        )
        root.destroy()
        return 1
    root.deiconify()
    MainWindow(root, core)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(run())
