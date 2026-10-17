"""真实 DLL 端到端用例（仅只读/参数拒绝类，绝不改动网络配置）。

网络变更类用例（IPv4 开关、切换序列、reset 往返）按设计文档 §8 一律为
人工测试，不在自动化范围。本文件所有用例均不触碰网络配置：
- v6_list_adapters：只读；
- 参数拒绝用例：if_index 用 0 或不存在的大数、非法地址，DLL 在参数层拒绝；
- v6_last_error：错误描述读取，无副作用。
"""

import ctypes
import threading
from ctypes import POINTER, c_char, c_char_p, c_int, c_uint32, create_string_buffer

import pytest

from conftest import requires_dll

V6_OK = 0
V6_ERR_PARAM = -2
V6_ERR_BUFFER = -3

pytestmark = requires_dll


@pytest.fixture()
def raw_dll(real_dll_path):
    dll = ctypes.CDLL(str(real_dll_path))
    dll.v6_list_adapters.argtypes = [POINTER(c_char), c_int]
    dll.v6_list_adapters.restype = c_int
    dll.v6_set_ipv4.argtypes = [c_uint32, c_int]
    dll.v6_set_ipv4.restype = c_int
    dll.v6_set_ipv6_dns.argtypes = [c_uint32, POINTER(c_char_p), c_int]
    dll.v6_set_ipv6_dns.restype = c_int
    dll.v6_reset.argtypes = [c_uint32]
    dll.v6_reset.restype = c_int
    dll.v6_last_error.argtypes = [POINTER(c_char), c_int]
    dll.v6_last_error.restype = c_int
    return dll


@pytest.fixture()
def core(real_dll_path):
    from v6switch.bindings.v6core import V6Core

    return V6Core()


# ---- v6_list_adapters：只读端到端 ----

def test_list_adapters_real(core):
    adapters = core.list_adapters()
    assert isinstance(adapters, list) and len(adapters) >= 1  # 至少有回环
    for a in adapters:
        assert set(a.keys()) == {
            "name", "desc", "status", "if_index",
            "ipv4", "ipv6", "dns_v4", "dns_v6", "virtual",
        }
        assert isinstance(a["if_index"], int)
        assert a["status"] in ("up", "down")
        assert isinstance(a["virtual"], bool)
        for key in ("ipv4", "ipv6", "dns_v4", "dns_v6"):
            assert isinstance(a[key], list)
    indexes = [a["if_index"] for a in adapters]
    assert len(indexes) == len(set(indexes))  # if_index 唯一


def test_list_adapters_json_chinese_roundtrip(core):
    """中文适配器名 UTF-8 往返：与 Windows 实际 FriendlyName 一致性难以离线断言，
    至少保证解析后字符串非空、无替换符乱码。"""
    adapters = core.list_adapters()
    for a in adapters:
        assert a["name"] != "" or a["desc"] != ""
        assert "\ufffd" not in a["name"] and "\ufffd" not in a["desc"]


def test_list_buffer_too_small_returns_buffer_error(raw_dll):
    """兜底路径：8 字节缓冲必然不足 → V6_ERR_BUFFER（真实触发一次）。"""
    buf = create_string_buffer(8)
    ret = raw_dll.v6_list_adapters(buf, len(buf))
    assert ret == V6_ERR_BUFFER
    # 错误描述可读
    err_buf = create_string_buffer(256)
    n = raw_dll.v6_last_error(err_buf, len(err_buf))
    assert n > 0
    assert err_buf.value.decode("utf-8") != ""


# ---- 参数拒绝类（不触网） ----

def test_list_param_null_buffer(raw_dll):
    ret = raw_dll.v6_list_adapters(None, 1024)
    assert ret == V6_ERR_PARAM
    ret = raw_dll.v6_list_adapters(create_string_buffer(64), 0)
    assert ret == V6_ERR_PARAM


def test_set_ipv4_invalid_index_rejected(raw_dll):
    """if_index=0 与不存在的大索引 → V6_ERR_PARAM（参数层拒绝，绝不执行）。"""
    assert raw_dll.v6_set_ipv4(0, 1) == V6_ERR_PARAM
    assert raw_dll.v6_set_ipv4(0, 0) == V6_ERR_PARAM
    # 0xDEADBEEF 大索引：先 GetAdaptersAddresses 匹配失败才返回，只读
    assert raw_dll.v6_set_ipv4(0xDEADBEEF, 1) == V6_ERR_PARAM


def test_set_ipv4_invalid_enabled_rejected(raw_dll):
    # enabled=7 非法 → V6_ERR_PARAM（不会执行任何绑定操作）
    assert raw_dll.v6_set_ipv4(0, 7) == V6_ERR_PARAM


def test_set_ipv6_dns_param_rejections(raw_dll):
    servers = (ctypes.c_char_p * 1)(b"2a00:1098:2b::1")
    # servers NULL
    assert raw_dll.v6_set_ipv6_dns(0, None, 1) == V6_ERR_PARAM
    # count 越界
    assert raw_dll.v6_set_ipv6_dns(0, servers, 0) == V6_ERR_PARAM
    assert raw_dll.v6_set_ipv6_dns(0, servers, 17) == V6_ERR_PARAM
    # 非法 IPv6 地址
    bad = (ctypes.c_char_p * 1)(b"not-an-ipv6")
    assert raw_dll.v6_set_ipv6_dns(0, bad, 1) == V6_ERR_PARAM
    # IPv4 地址混入
    bad2 = (ctypes.c_char_p * 1)(b"10.0.0.1")
    assert raw_dll.v6_set_ipv6_dns(0, bad2, 1) == V6_ERR_PARAM
    # NULL 元素
    mixed = (ctypes.c_char_p * 2)(b"2a00:1098:2b::1", None)
    assert raw_dll.v6_set_ipv6_dns(0, mixed, 2) == V6_ERR_PARAM
    # 参数全合法但 if_index 不存在（只读定位，不触网）
    assert raw_dll.v6_set_ipv6_dns(0xDEADBEEF, servers, 1) == V6_ERR_PARAM


def test_reset_invalid_index_rejected(raw_dll):
    assert raw_dll.v6_reset(0) == V6_ERR_PARAM
    assert raw_dll.v6_reset(0xDEADBEEF) == V6_ERR_PARAM


# ---- v6_last_error 语义（§5.1.1） ----

def test_last_error_after_failure_and_truncation(raw_dll):
    assert raw_dll.v6_set_ipv4(0, 1) == V6_ERR_PARAM  # 制造一次失败
    full = create_string_buffer(2048)
    n = raw_dll.v6_last_error(full, len(full))
    assert n > 0
    text = full.raw[:n].decode("utf-8")
    assert full.raw[n] == 0  # NUL 结尾
    # 截断：小缓冲写入 <= buf_len-1 字节，NUL 结尾，且按 UTF-8 字符边界回退（可安全解码）
    small = create_string_buffer(8)
    n2 = raw_dll.v6_last_error(small, len(small))
    assert 0 < n2 <= 7
    assert small.raw[n2] == 0
    decoded = small.value.decode("utf-8")  # 不得抛 UnicodeDecodeError
    assert decoded == text.encode("utf-8")[:n2].decode("utf-8")  # 与完整消息的前 n2 字节一致


def test_last_error_null_and_zero_len(raw_dll):
    assert raw_dll.v6_last_error(None, 1024) == 0
    assert raw_dll.v6_last_error(create_string_buffer(64), 0) == 0
    assert raw_dll.v6_last_error(create_string_buffer(64), -5) == 0


def test_last_error_never_negative(raw_dll):
    assert raw_dll.v6_last_error(create_string_buffer(1), 1) >= 0


# ---- 线程局部语义 ----

def test_last_error_is_thread_local(raw_dll):
    """线程 A 触发错误，线程 B 读取 → 0（错误不跨线程可见）。"""
    box = {}

    # 先在主线程做一次只读成功调用，清掉此前用例可能残留的错误槽
    big = create_string_buffer(64 * 1024)
    assert raw_dll.v6_list_adapters(big, len(big)) == V6_OK
    assert raw_dll.v6_last_error(create_string_buffer(64), 64) == 0

    def trigger():
        box["ret"] = raw_dll.v6_set_ipv4(0, 1)  # 参数错误，写线程 A 的错误槽

    t = threading.Thread(target=trigger)
    t.start()
    t.join()
    assert box["ret"] == V6_ERR_PARAM
    err_buf = create_string_buffer(256)
    assert raw_dll.v6_last_error(err_buf, len(err_buf)) == 0  # 主线程无待取描述


def test_last_error_visible_same_thread(raw_dll):
    """同线程紧随失败读取 → 非空（契约主语义）。"""
    assert raw_dll.v6_set_ipv4(0, 1) == V6_ERR_PARAM
    err_buf = create_string_buffer(256)
    assert raw_dll.v6_last_error(err_buf, len(err_buf)) > 0
