"""切换/重置编排封装（设计文档 §5.2 core_ops）。

固化两条铁律（§11），GUI 与 CLI 一律经本模块调用，禁止各自拼 DLL 调用序列：
- 身份校验铁律：执行任何变更前，重新罗列并以 if_index↔name 配对校验目标接口
  （防目标消失后索引被复用导致误操作其他接口）；
- 切换顺序铁律：先 v6_set_ipv6_dns 成功、再 v6_set_ipv4(0)，全程保持解析可用；
  还原一律用 v6_reset。
"""

from __future__ import annotations

from .bindings.v6core import V6Core, V6Error


class TargetMismatchError(Exception):
    """if_index 与连接名配对校验失败（目标消失或索引被复用）。"""


class PartialSwitchError(Exception):
    """DNS64 已设置成功但关闭 IPv4 失败（网络可能不可用，建议执行重置）。"""

    def __init__(self, message: str, cause: V6Error) -> None:
        self.cause = cause
        super().__init__(message)


def _verify_target(core: V6Core, if_index: int, name: str) -> dict:
    """重新罗列并做 if_index↔name 配对二次校验；通过返回目标适配器数据。"""
    for adapter in core.list_adapters():
        if adapter.get("if_index") == if_index:
            if adapter.get("name") == name:
                return adapter
            break
    raise TargetMismatchError(
        f"目标网络连接已变化（索引 {if_index} 与名称「{name}」不配对），请刷新列表后重选"
    )


def switch_to_ipv6(core: V6Core, if_index: int, name: str, servers: list[str]) -> None:
    """一键切换 IPv6-only：先设 DNS64，后关 IPv4（顺序铁律）。"""
    _verify_target(core, if_index, name)
    # a. 先设 IPv6 DNS64，保持解析不断
    core.set_ipv6_dns(if_index, servers)
    # b. 后关 IPv4 绑定
    try:
        core.set_ipv4(if_index, False)
    except V6Error as exc:
        raise PartialSwitchError(
            "DNS64 已设置成功，但关闭 IPv4 失败，当前网络可能不可用。"
            "建议执行「重置」恢复默认配置。",
            exc,
        ) from exc


def reset_adapter(core: V6Core, if_index: int, name: str) -> None:
    """重置：恢复默认网络配置（IPv4 绑定开启 + DNS 恢复自动获取，非快照还原）。"""
    _verify_target(core, if_index, name)
    core.reset_adapter(if_index)
