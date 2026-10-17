"""纯 Python 实现的 v6core.dll mock（经 ctypes.CFUNCTYPE 暴露相同 C ABI）。

供 bindings 封装与 core_ops 编排的纯 Python 单测使用，无需真实 DLL、不触网。
线程局部错误语义与真实 DLL 一致（v6_last_error 同线程紧随读取）。
"""

from __future__ import annotations

import ctypes
import ipaddress
import json
import threading

V6_OK = 0
V6_ERR_GENERIC = -1
V6_ERR_PARAM = -2
V6_ERR_BUFFER = -3
V6_ERR_ADMIN = -4
V6_ERR_EXEC = -5

_LIST_PROTO = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.POINTER(ctypes.c_char), ctypes.c_int
)
_SET_IPV4_PROTO = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_uint32, ctypes.c_int)
_SET_DNS_PROTO = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_uint32, ctypes.POINTER(ctypes.c_char_p), ctypes.c_int
)
_RESET_PROTO = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_uint32)
_LAST_ERR_PROTO = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_char), ctypes.c_int)

DEFAULT_ADAPTERS = [
    {
        "name": "以太网",
        "desc": "Intel(R) Ethernet Connection",
        "status": "up",
        "if_index": 12,
        "ipv4": ["10.132.0.8"],
        "ipv6": ["2001:da8:1005::1008"],
        "dns_v4": ["202.115.0.10"],
        "dns_v6": [],
        "virtual": False,
    },
    {
        "name": "vEthernet (WSL)",
        "desc": "Hyper-V Virtual Ethernet Adapter",
        "status": "up",
        "if_index": 33,
        "ipv4": ["172.22.0.1"],
        "ipv6": [],
        "dns_v4": [],
        "dns_v6": [],
        "virtual": True,
    },
]


class FakeDll:
    """行为可编排的 v6core mock。

    Args:
        adapters: v6_list_adapters 输出的数据。
        fail_ipv4: v6_set_ipv4 返回 V6_ERR_EXEC（模拟 Apply 失败）。
        fail_dns_step: v6_set_ipv6_dns 在第 N 条失败（模拟中途失败触发回滚语义）。
        buffer_need: 罗列调用声称需要的最小 buf_len（模拟缓冲区不足）。
        admin_required: 操作类函数一律返回 V6_ERR_ADMIN。
    """

    def __init__(
        self,
        adapters: list[dict] | None = None,
        *,
        fail_ipv4: bool = False,
        fail_dns_step: int | None = None,
        buffer_need: int | None = None,
        admin_required: bool = False,
    ) -> None:
        self.adapters = adapters if adapters is not None else [dict(a) for a in DEFAULT_ADAPTERS]
        self.fail_ipv4 = fail_ipv4
        self.fail_dns_step = fail_dns_step
        self.buffer_need = buffer_need
        self.admin_required = admin_required
        self.calls: list[tuple] = []
        self._tls = threading.local()

        self.v6_list_adapters = _LIST_PROTO(self._list)
        self.v6_set_ipv4 = _SET_IPV4_PROTO(self._set_ipv4)
        self.v6_set_ipv6_dns = _SET_DNS_PROTO(self._set_dns)
        self.v6_reset = _RESET_PROTO(self._reset)
        self.v6_last_error = _LAST_ERR_PROTO(self._last_error)

    # ---- 线程局部错误 ----

    def _set_err(self, msg: str) -> None:
        self._tls.err = msg.encode("utf-8")

    def _clear_err(self) -> None:
        self._tls.err = b""

    def _last_error(self, buf, buf_len: int) -> int:
        if not buf or buf_len <= 0:
            return 0
        raw = getattr(self._tls, "err", b"")
        n = min(len(raw), buf_len - 1)
        out = raw[:n] + b"\x00"
        ctypes.memmove(buf, out, len(out))
        return n

    # ---- 业务函数 ----

    def _find(self, if_index: int) -> dict | None:
        return next((a for a in self.adapters if a.get("if_index") == if_index), None)

    def _list(self, buf, buf_len: int) -> int:
        if not buf or buf_len <= 0:
            self._set_err("无效输出缓冲区")
            return V6_ERR_PARAM
        self._clear_err()
        data = json.dumps(self.adapters, ensure_ascii=False).encode("utf-8")
        if self.buffer_need is not None and buf_len < self.buffer_need:
            self._set_err(f"罗列结果需要 {self.buffer_need} 字节，超过缓冲区 {buf_len} 字节")
            return V6_ERR_BUFFER
        if len(data) + 1 > buf_len:
            self._set_err(f"罗列结果需要 {len(data) + 1} 字节，超过缓冲区 {buf_len} 字节")
            return V6_ERR_BUFFER
        ctypes.memmove(buf, data + b"\x00", len(data) + 1)
        return V6_OK

    def _check_target(self, if_index: int) -> dict | None:
        adapter = self._find(if_index)
        if adapter is None:
            self._set_err(f"接口索引 {if_index} 不存在（连接可能已断开或被移除，请刷新列表）")
            return None
        return adapter

    def _set_ipv4(self, if_index: int, enabled: int) -> int:
        self.calls.append(("set_ipv4", if_index, bool(enabled)))
        if enabled not in (0, 1):
            self._set_err("enabled 参数非法")
            return V6_ERR_PARAM
        if self._check_target(if_index) is None:
            return V6_ERR_PARAM
        self._clear_err()
        if self.admin_required:
            self._set_err("当前进程无管理员权限")
            return V6_ERR_ADMIN
        if self.fail_ipv4:
            self._set_err("应用网络配置失败（INetCfg::Apply）")
            return V6_ERR_EXEC
        return V6_OK

    def _set_dns(self, if_index: int, servers, count: int) -> int:
        if servers is None:
            self.calls.append(("set_ipv6_dns", if_index, None, count))
            self._set_err("servers 数组为 NULL")
            return V6_ERR_PARAM
        if count < 1 or count > 16:
            self.calls.append(("set_ipv6_dns", if_index, [], count))
            self._set_err(f"DNS 数量 {count} 超出范围")
            return V6_ERR_PARAM
        read = []
        for i in range(count):
            item = servers[i]
            if item is None:
                self.calls.append(("set_ipv6_dns", if_index, read, count))
                self._set_err(f"servers[{i}] 为 NULL")
                return V6_ERR_PARAM
            read.append(item.decode("utf-8"))
        self.calls.append(("set_ipv6_dns", if_index, read, count))
        for i, s in enumerate(read):
            try:
                ipaddress.IPv6Address(s)
            except ValueError:
                self._set_err(f"servers[{i}]（{s}）不是合法 IPv6 地址")
                return V6_ERR_PARAM
        if self._check_target(if_index) is None:
            return V6_ERR_PARAM
        self._clear_err()
        if self.admin_required:
            self._set_err("当前进程无管理员权限")
            return V6_ERR_ADMIN
        if self.fail_dns_step is not None and count >= self.fail_dns_step:
            self._set_err(f"netsh 设置第 {self.fail_dns_step} 条 DNS 失败（exit=1）；已回滚")
            return V6_ERR_EXEC
        return V6_OK

    def _reset(self, if_index: int) -> int:
        self.calls.append(("reset", if_index))
        if self._check_target(if_index) is None:
            return V6_ERR_PARAM
        self._clear_err()
        if self.admin_required:
            self._set_err("当前进程无管理员权限")
            return V6_ERR_ADMIN
        return V6_OK
