"""core_ops 编排用例（纯 Python，mock DLL，无需真实 DLL）。"""

import pytest

from fake_dll import DEFAULT_ADAPTERS, FakeDll
from v6switch import core_ops
from v6switch.bindings.v6core import V6Core, V6Error

IDX = DEFAULT_ADAPTERS[0]["if_index"]  # 12
NAME = DEFAULT_ADAPTERS[0]["name"]  # "以太网"
SERVERS = ["2a00:1098:2b::1", "2a00:1098:2c::1"]


def make_core(**kwargs) -> tuple[V6Core, FakeDll]:
    fake = FakeDll(**kwargs)
    return V6Core(dll=fake), fake


def test_switch_order_dns_first_then_ipv4_off():
    core, fake = make_core()
    core_ops.switch_to_ipv6(core, IDX, NAME, SERVERS)
    assert [c[0] for c in fake.calls] == ["set_ipv6_dns", "set_ipv4"]
    assert fake.calls[0][1] == IDX and fake.calls[0][2] == SERVERS
    assert fake.calls[1] == ("set_ipv4", IDX, False)


def test_switch_passes_exact_server_list():
    core, fake = make_core()
    core_ops.switch_to_ipv6(core, IDX, NAME, SERVERS)
    assert fake.calls[0] == ("set_ipv6_dns", IDX, SERVERS, len(SERVERS))


def test_switch_name_mismatch_rejected():
    core, fake = make_core()
    with pytest.raises(core_ops.TargetMismatchError):
        core_ops.switch_to_ipv6(core, IDX, "不存在的连接名", SERVERS)
    assert fake.calls == []  # 校验失败：不执行任何变更


def test_switch_target_missing_rejected():
    core, fake = make_core()
    with pytest.raises(core_ops.TargetMismatchError):
        core_ops.switch_to_ipv6(core, 999, "任意", SERVERS)
    assert fake.calls == []


def test_switch_ipv4_failure_partial_error():
    core, fake = make_core(fail_ipv4=True)
    with pytest.raises(core_ops.PartialSwitchError) as exc_info:
        core_ops.switch_to_ipv6(core, IDX, NAME, SERVERS)
    # DNS 已先成功设置，随后关闭 IPv4 失败
    assert [c[0] for c in fake.calls] == ["set_ipv6_dns", "set_ipv4"]
    assert exc_info.value.cause.code == -5  # V6_ERR_EXEC


def test_reset_calls_dll():
    core, fake = make_core()
    core_ops.reset_adapter(core, IDX, NAME)
    assert fake.calls == [("reset", IDX)]


def test_reset_name_mismatch_rejected():
    core, fake = make_core()
    with pytest.raises(core_ops.TargetMismatchError):
        core_ops.reset_adapter(core, IDX, "别的名字")
    assert fake.calls == []


def test_dll_error_propagates():
    core, _ = make_core(admin_required=True)
    with pytest.raises(V6Error) as exc_info:
        core_ops.reset_adapter(core, IDX, NAME)
    assert exc_info.value.code == -4  # V6_ERR_ADMIN
