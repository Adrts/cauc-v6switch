"""bindings 封装用例（纯 Python，mock DLL，无需真实 DLL）。"""

import pytest

from fake_dll import DEFAULT_ADAPTERS, FakeDll
from v6switch.bindings.v6core import (
    V6_ERR_BUFFER,
    V6_ERR_PARAM,
    V6Core,
    V6BufferError,
    V6Error,
)

IDX = DEFAULT_ADAPTERS[0]["if_index"]
SERVERS = ["2a00:1098:2b::1", "2a00:1098:2c::1", "2a01:4f8:c2c:123f::1"]


def make_core(**kwargs) -> tuple[V6Core, FakeDll]:
    fake = FakeDll(**kwargs)
    return V6Core(dll=fake), fake


def test_list_adapters_parses_json_utf8():
    core, _ = make_core()
    adapters = core.list_adapters()
    assert isinstance(adapters, list) and len(adapters) == 2
    first = adapters[0]
    assert first["name"] == "以太网"  # 中文经 UTF-8 编解码往返
    assert first["if_index"] == IDX
    assert first["virtual"] is False


def test_list_buffer_retry_on_insufficient():
    # 首次 64KB 声称不足 → bindings 扩容 256KB 重试成功（兜底路径）
    core, _ = make_core(buffer_need=64 * 1024 + 1)
    adapters = core.list_adapters()
    assert adapters[0]["name"] == "以太网"


def test_list_buffer_still_insufficient_raises():
    core, _ = make_core(buffer_need=300 * 1024)
    with pytest.raises(V6BufferError) as exc_info:
        core.list_adapters()
    assert exc_info.value.code == V6_ERR_BUFFER


def test_error_code_to_exception_with_thread_local_message():
    core, _ = make_core()
    with pytest.raises(V6Error) as exc_info:
        core.set_ipv4(0, True)
    assert exc_info.value.code == V6_ERR_PARAM
    assert "接口索引 0" in str(exc_info.value)


def test_set_ipv4_bool_mapping():
    core, fake = make_core()
    core.set_ipv4(IDX, True)
    core.set_ipv4(IDX, False)
    assert fake.calls == [("set_ipv4", IDX, True), ("set_ipv4", IDX, False)]


def test_set_ipv6_dns_encodes_utf8():
    core, fake = make_core()
    core.set_ipv6_dns(IDX, SERVERS)
    assert fake.calls == [("set_ipv6_dns", IDX, SERVERS, 3)]


def test_set_ipv6_dns_invalid_address_rejected_by_dll():
    core, _ = make_core()
    with pytest.raises(V6Error) as exc_info:
        core.set_ipv6_dns(IDX, ["1.2.3.4"])  # IPv4 不是合法 IPv6
    assert exc_info.value.code == V6_ERR_PARAM


def test_reset_ok():
    core, fake = make_core()
    core.reset_adapter(IDX)
    assert fake.calls == [("reset", IDX)]
