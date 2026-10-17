"""v6core.dll 的 ctypes 绑定封装。

契约真源：v6core/include/v6core.h（设计文档 §5.1.1）。
- 按 §5.6 探测顺序解析 DLL 绝对路径后加载，不依赖 OS 裸名搜索；
- 逐函数声明 argtypes/restype；缓冲区自动构造、UTF-8 编解码、错误码转异常；
- 错误码转异常必须在同一线程、紧随 DLL 调用返回完成（v6_last_error 为线程局部，
  禁止跨线程缓存或延迟读取）。
"""

from __future__ import annotations

import ctypes
import json
import sys
from ctypes import POINTER, c_char, c_char_p, c_int, c_uint32, create_string_buffer
from pathlib import Path

# 返回码（v6core.h）
V6_OK = 0
V6_ERR_GENERIC = -1
V6_ERR_PARAM = -2
V6_ERR_BUFFER = -3
V6_ERR_ADMIN = -4
V6_ERR_EXEC = -5

_CODE_NAMES = {
    V6_ERR_GENERIC: "底层通用错误",
    V6_ERR_PARAM: "参数非法",
    V6_ERR_BUFFER: "缓冲区不足",
    V6_ERR_ADMIN: "需要管理员权限",
    V6_ERR_EXEC: "底层命令执行失败",
}

# 罗列缓冲区：主路径 64 KB 一次完成；V6_ERR_BUFFER 兜底扩容至 256 KB 重试一次（§5.1.2）
_LIST_BUF_SIZE = 64 * 1024
_LIST_BUF_RETRY = 256 * 1024
_ERR_BUF_SIZE = 1024


class V6Error(Exception):
    """v6core.dll 业务错误（负错误码 + 线程局部错误描述）。"""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        super().__init__(message)


class V6BufferError(V6Error):
    """扩容重试后缓冲区仍不足（异常环境）。"""


class V6DllNotFound(Exception):
    """探测顺序内未找到 v6core.dll（§5.6）。"""


def dll_candidates() -> list[Path]:
    """DLL 探测顺序（§5.6）：① exe/主模块同目录（frozen）→ ② 开发期项目 dist/。"""
    if getattr(sys, "frozen", False):
        return [Path(sys.executable).resolve().parent / "v6core.dll"]
    root = Path(__file__).resolve().parents[3]  # app/v6switch/bindings/ → 项目根
    return [root / "dist" / "v6core.dll"]


def load_dll() -> ctypes.CDLL:
    """按探测顺序加载 v6core.dll（cdecl），找不到时抛 V6DllNotFound。"""
    tried: list[str] = []
    for path in dll_candidates():
        tried.append(str(path))
        if path.is_file():
            return ctypes.CDLL(str(path))
    detail = "；已探测：" + "、".join(tried)
    raise V6DllNotFound("未找到 v6core.dll，请将其与程序放在同一目录" + detail)


class V6Core:
    """类型安全的 v6core.dll 调用封装（线程安全：错误读取在同线程就地完成）。"""

    def __init__(self, dll: object | None = None) -> None:
        # dll 参数供测试注入 mock（实现相同 C ABI 的对象）；生产路径走 load_dll()
        self._dll = dll if dll is not None else load_dll()
        self._bind()

    # ---- 契约绑定 ----

    def _bind(self) -> None:
        d = self._dll
        d.v6_list_adapters.argtypes = [POINTER(c_char), c_int]
        d.v6_list_adapters.restype = c_int
        d.v6_set_ipv4.argtypes = [c_uint32, c_int]
        d.v6_set_ipv4.restype = c_int
        d.v6_set_ipv6_dns.argtypes = [c_uint32, POINTER(c_char_p), c_int]
        d.v6_set_ipv6_dns.restype = c_int
        d.v6_reset.argtypes = [c_uint32]
        d.v6_reset.restype = c_int
        d.v6_last_error.argtypes = [POINTER(c_char), c_int]
        d.v6_last_error.restype = c_int

    def _last_error(self) -> str:
        """同线程、紧随失败调用读取错误描述（§5.1.1 截断语义由 DLL 保证）。"""
        buf = create_string_buffer(_ERR_BUF_SIZE)
        n = self._dll.v6_last_error(buf, len(buf))
        if n <= 0:
            return ""
        return buf.raw[:n].decode("utf-8", errors="replace")

    def _raise(self, code: int, ctx: str) -> None:
        detail = self._last_error()
        if not detail:
            detail = _CODE_NAMES.get(code, f"未知错误码 {code}")
        exc = V6Error(code, f"{ctx}：{detail}")
        if code == V6_ERR_BUFFER:
            raise V6BufferError(code, str(exc))
        raise exc

    # ---- 四个业务函数 ----

    def list_adapters(self) -> list[dict]:
        """罗列网络连接（兼作状态查询）；返回 JSON 解析后的字典列表。"""
        size = _LIST_BUF_SIZE
        while True:
            buf = create_string_buffer(size)
            ret = self._dll.v6_list_adapters(buf, size)
            if ret == V6_OK:
                try:
                    data = json.loads(buf.value.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise V6Error(V6_ERR_GENERIC, f"罗列结果解析失败：{exc}") from exc
                if not isinstance(data, list):
                    raise V6Error(V6_ERR_GENERIC, "罗列结果格式异常（非 JSON 数组）")
                return data
            if ret == V6_ERR_BUFFER and size < _LIST_BUF_RETRY:
                size = _LIST_BUF_RETRY  # 兜底扩容重试一次
                continue
            self._raise(ret, "罗列网络连接")

    def set_ipv4(self, if_index: int, enabled: bool) -> None:
        ret = self._dll.v6_set_ipv4(c_uint32(if_index), c_int(1 if enabled else 0))
        if ret != V6_OK:
            self._raise(ret, "开启 IPv4" if enabled else "关闭 IPv4")

    def set_ipv6_dns(self, if_index: int, servers: list[str]) -> None:
        encoded = [s.encode("utf-8") for s in servers]
        arr = (c_char_p * len(encoded))(*encoded)
        ret = self._dll.v6_set_ipv6_dns(c_uint32(if_index), arr, len(encoded))
        if ret != V6_OK:
            self._raise(ret, "设置 IPv6 DNS")

    def reset_adapter(self, if_index: int) -> None:
        ret = self._dll.v6_reset(c_uint32(if_index))
        if ret != V6_OK:
            self._raise(ret, "重置网络连接")
