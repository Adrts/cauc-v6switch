"""CLI 入口（开发期工具，不随包分发，设计文档 FR-8 / §5.2 / §5.6）。

- 子命令：list / set-ipv4 / set-dns / reset / presets（与导出函数对应，供开发调试）；
- 无参数时进入交互菜单：罗列 / 切换 IPv6-only / 重置；
- 切换与重置一律经 core_ops（身份校验 + 顺序铁律），与 GUI 行为一致；
- 启动自检提权（FR-5），无权限 runas 重启自身。
"""

from __future__ import annotations

import argparse
import sys

from . import admin, core_ops
from .bindings.v6core import V6Core, V6DllNotFound, V6Error
from .presets import ConfigError, config_path, ensure_config, load_dns64


def _print_adapters(adapters: list[dict], show_virtual: bool = False) -> None:
    rows = [a for a in adapters if show_virtual or not a.get("virtual")]
    if not rows:
        print("（无网络连接）")
        return
    width = max(len(str(a.get("name", ""))) for a in rows)
    print(f"{'名称':<{width}}  {'状态':<6} {'索引':>4}  {'IPv4 摘要':<20} {'IPv6 摘要':<24} 描述")
    for a in rows:
        ipv4 = ",".join(a.get("ipv4", [])) or "已关闭"
        ipv6 = ",".join(a.get("ipv6", [])[:1]) or "-"
        flag = "（虚拟）" if a.get("virtual") else ""
        print(
            f"{a.get('name', ''):<{width}}  {a.get('status', ''):<6} "
            f"{a.get('if_index', 0):>4}  {ipv4:<20} {ipv6:<24} {a.get('desc', '')}{flag}"
        )


def _find_adapter(adapters: list[dict], if_index: int) -> dict | None:
    return next((a for a in adapters if a.get("if_index") == if_index), None)


def _ask_index(core: V6Core, action: str) -> tuple[int, str] | None:
    """罗列并让用户输入 if_index，返回 (if_index, name)；输入非法返回 None。"""
    adapters = core.list_adapters()
    _print_adapters(adapters)
    raw = input(f"输入要{action}的连接 if_index（回车取消）：").strip()
    if not raw:
        return None
    try:
        idx = int(raw)
    except ValueError:
        print("！请输入数字 if_index")
        return None
    adapter = _find_adapter(adapters, idx)
    if not adapter:
        print(f"！索引 {idx} 不在列表中")
        return None
    return idx, adapter.get("name", "")


def _confirm(prompt: str) -> bool:
    return input(f"{prompt} [y/N]：").strip().lower() in ("y", "yes")


def _read_servers() -> list[str]:
    """读取 DNS64 配置（所见即所执）。"""
    servers = load_dns64()
    print(f"将写入 DNS64（{len(servers)} 条，来自 {config_path().name}）：")
    for s in servers:
        print(f"  - {s}")
    return servers


def _run_switch(core: V6Core) -> None:
    try:
        servers = _read_servers()
    except ConfigError as exc:
        print(f"！配置错误：{exc}")
        return
    target = _ask_index(core, "切换 IPv6-only")
    if not target:
        return
    if_index, name = target
    if not _confirm(f"确认切换「{name}」（索引 {if_index}）到 IPv6-only？先设 DNS64，后关 IPv4"):
        print("已取消")
        return
    try:
        core_ops.switch_to_ipv6(core, if_index, name, servers)
    except core_ops.TargetMismatchError as exc:
        print(f"！{exc}")
        return
    except core_ops.PartialSwitchError as exc:
        print(f"×部分失败：{exc}")
        print("  建议立即执行重置恢复默认配置。")
        return
    except V6Error as exc:
        print(f"×切换失败：{exc}")
        return
    print("√切换完成（IPv6-only）")


def _run_reset(core: V6Core) -> None:
    target = _ask_index(core, "重置")
    if not target:
        return
    if_index, name = target
    if not _confirm(
        f"确认重置「{name}」（索引 {if_index}）？IPv4 绑定恢复开启，DNS 恢复自动获取"
        "（原有静态 DNS 会被清除，非快照还原）"
    ):
        print("已取消")
        return
    try:
        core_ops.reset_adapter(core, if_index, name)
    except core_ops.TargetMismatchError as exc:
        print(f"！{exc}")
        return
    except V6Error as exc:
        print(f"×重置失败：{exc}")
        return
    print("√重置完成")


def interactive_menu(core: V6Core) -> int:
    while True:
        print()
        print("[1] 罗列网络连接  [2] 切换 IPv6-only（先设 DNS64 后关 IPv4）  [3] 重置  [0] 退出")
        choice = input("选择：").strip()
        try:
            if choice == "1":
                _print_adapters(core.list_adapters())
            elif choice == "2":
                _run_switch(core)
            elif choice == "3":
                _run_reset(core)
            elif choice in ("0", "q", "Q", ""):
                return 0
            else:
                print("无效选择")
        except (KeyboardInterrupt, EOFError):
            print()
            return 0
        except V6Error as exc:
            print(f"×操作失败：{exc}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="v6switch.cli",
        description="CAUC IPv6 Switch CLI（开发期工具）",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="罗列网络连接")

    p = sub.add_parser("set-ipv4", help="开关指定连接的 IPv4 绑定（开发调试用，单步直调）")
    p.add_argument("if_index", type=int)
    p.add_argument("state", choices=["on", "off"], help="on=开启 off=关闭")

    p = sub.add_parser("set-dns", help="为指定连接写入 config.yaml 启用的 DNS64（开发调试用）")
    p.add_argument("if_index", type=int)

    p = sub.add_parser("reset", help="重置指定连接（恢复默认配置，经 core_ops 身份校验）")
    p.add_argument("if_index", type=int)

    sub.add_parser("presets", help="显示 DNS64 配置文件路径与启用地址")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    # 先解析参数（无副作用），再提权——避免拼错参数也先弹 UAC
    if args:
        ns = build_parser().parse_args(args)
    admin.ensure_admin(["v6switch.cli", *args])

    try:
        core = V6Core()
    except V6DllNotFound as exc:
        print(f"×{exc}", file=sys.stderr)
        return 1

    if not args:
        return interactive_menu(core)

    try:
        if ns.cmd == "list":
            _print_adapters(core.list_adapters())
            return 0
        if ns.cmd == "presets":
            ensure_config()
            print(f"配置文件：{config_path()}")
            try:
                servers = load_dns64()
            except ConfigError as exc:
                print(f"×配置错误：{exc}")
                return 1
            print(f"启用 {len(servers)} 条：")
            for s in servers:
                print(f"  - {s}")
            return 0
        if ns.cmd == "set-ipv4":
            core.set_ipv4(ns.if_index, ns.state == "on")
            print(f"√IPv4 已{'开启' if ns.state == 'on' else '关闭'}（索引 {ns.if_index}）")
            return 0
        if ns.cmd == "set-dns":
            servers = load_dns64()
            core.set_ipv6_dns(ns.if_index, servers)
            print(f"√已写入 {len(servers)} 条 DNS64（索引 {ns.if_index}）")
            return 0
        if ns.cmd == "reset":
            adapters = core.list_adapters()
            adapter = _find_adapter(adapters, ns.if_index)
            if not adapter:
                print(f"×索引 {ns.if_index} 不存在，请先 list")
                return 1
            name = adapter.get("name", "")
            if not _confirm(
                f"确认重置「{name}」（索引 {ns.if_index}）？原有静态 DNS 会被清除，非快照还原"
            ):
                print("已取消")
                return 0
            core_ops.reset_adapter(core, ns.if_index, name)
            print("√重置完成")
            return 0
    except core_ops.TargetMismatchError as exc:
        print(f"×{exc}")
        return 1
    except ConfigError as exc:
        print(f"×配置错误：{exc}")
        return 1
    except V6Error as exc:
        print(f"×操作失败（错误码 {exc.code}）：{exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
