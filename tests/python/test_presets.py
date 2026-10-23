"""presets（config.yaml）用例（纯 Python，无需 DLL）。"""

import pytest

from v6switch import presets
from v6switch.presets import ConfigError

PATCH = "v6switch.presets.config_path"


def cfg(tmp_path):
    return tmp_path / "config.yaml"


def test_first_run_generates_default(tmp_path, monkeypatch):
    path = cfg(tmp_path)
    monkeypatch.setattr(PATCH, lambda: path)
    servers = presets.load_dns64()  # 首次调用自动生成
    assert path.exists()
    # 默认启用 nat64.net 三节点组合，顺序即写入序
    assert servers == ["2a00:1098:2b::1", "2a00:1098:2c::1", "2a01:4f8:c2c:123f::1"]
    text = path.read_text(encoding="utf-8")
    assert "# - 2001:67c:2b0::4" in text  # 备用节点以注释内置
    assert "Trex" in text and "level66" in text


def test_commented_lines_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(PATCH, lambda: cfg(tmp_path))
    cfg(tmp_path).write_text(
        "dns64:\n"
        "  - 2a00:1098:2b::1\n"
        "  # - 2a00:1098:2c::1\n"
        "  - 2a01:4f8:c2c:123f::1\n",
        encoding="utf-8",
    )
    assert presets.load_dns64() == ["2a00:1098:2b::1", "2a01:4f8:c2c:123f::1"]


def test_order_follows_file(tmp_path, monkeypatch):
    monkeypatch.setattr(PATCH, lambda: cfg(tmp_path))
    cfg(tmp_path).write_text(
        "dns64:\n  - 2001:67c:2b0::6\n  - 2001:67c:2960::6464\n", encoding="utf-8"
    )
    assert presets.load_dns64() == ["2001:67c:2b0::6", "2001:67c:2960::6464"]


def test_invalid_address_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(PATCH, lambda: cfg(tmp_path))
    cfg(tmp_path).write_text("dns64:\n  - 1.2.3.4\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="不是合法 IPv6 地址"):
        presets.load_dns64()


def test_empty_list_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(PATCH, lambda: cfg(tmp_path))
    cfg(tmp_path).write_text("dns64:\n  # - 2a00:1098:2b::1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="为空"):
        presets.load_dns64()


def test_over_limit_truncated_in_file_order(tmp_path, monkeypatch):
    monkeypatch.setattr(PATCH, lambda: cfg(tmp_path))
    lines = "\n".join(f"  - 2001:db8::{i}" for i in range(12))
    cfg(tmp_path).write_text(f"dns64:\n{lines}\n", encoding="utf-8")
    servers = presets.load_dns64()
    assert len(servers) == presets.MAX_DNS64 == 10
    assert servers == [f"2001:db8::{i}" for i in range(10)]  # 按文件顺序取前 10 条


def test_malformed_yaml_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(PATCH, lambda: cfg(tmp_path))
    cfg(tmp_path).write_text("dns64: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="YAML 解析失败"):
        presets.load_dns64()


def test_missing_key_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(PATCH, lambda: cfg(tmp_path))
    cfg(tmp_path).write_text("other: []\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="dns64"):
        presets.load_dns64()


def test_non_list_value_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(PATCH, lambda: cfg(tmp_path))
    cfg(tmp_path).write_text("dns64: 2a00:1098:2b::1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="列表"):
        presets.load_dns64()
