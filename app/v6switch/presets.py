"""DNS64 预设配置（config.yaml）读写（设计文档 §5.4）。

- 便携式：与程序本体同目录（frozen → exe 目录；开发 → app/）；
- 首次运行不存在 → 自动生成默认配置（程序始终以管理员运行，写入权限有保证）；
- 解析规则：顺序即写入顺序；行首加 # 即停用（YAML 解析天然排除注释行）；
  按文件顺序取前 10 条启用地址（1 ≤ count ≤ 10），超出部分直接忽略；
- GUI 只读预览，修改经编辑配置文件。
"""

from __future__ import annotations

import ipaddress
import sys
from pathlib import Path

import yaml

MAX_DNS64 = 10

_DEFAULT_SERVERS = [
    ("2a00:1098:2b::1", "nat64.net Amsterdam"),
    ("2a00:1098:2c::1", "nat64.net London"),
    ("2a01:4f8:c2c:123f::1", "nat64.net Nuremberg"),
    ("2a01:4ff:f0:9876::1", "nat64.net Ashburn"),
    ("2a01:4f9:c010:3f02::1", "nat64.net Helsinki"),
    ("2001:67c:2b0::4", "Trex Tampere"),
    ("2001:67c:2b0::6", "Trex Tampere"),
    ("2001:67c:2960::64", "level66 Germany"),
    ("2001:67c:2960::6464", "level66 Germany"),
]


class ConfigError(Exception):
    """config.yaml 缺失/解析失败/内容非法。"""


def _default_config_text() -> str:
    lines = [
        "# DNS64 服务器列表",
        "# 规则：按序写入 v6_set_ipv6_dns；行首加 # 即停用该地址；",
        "# 未注释行数 = 实际写入数量 count（按文件顺序取前 10 条，超出部分忽略）",
        "dns64:",
    ]
    for i, (addr, note) in enumerate(_DEFAULT_SERVERS):
        enabled = i < 3  # 默认启用前三（nat64.net 三节点组合）
        lines.append(f"{'  - ' if enabled else '  # - '}{addr:<26}# {note}")
    return "\n".join(lines) + "\n"


def config_path() -> Path:
    """config.yaml 定位（双模式保证源码/打包均可读）。"""
    if getattr(sys, "frozen", False):  # 打包（PyInstaller exe）
        return Path(sys.executable).parent / "config.yaml"  # exe 同目录（dist/）
    return Path(__file__).resolve().parents[1] / "config.yaml"  # 开发：app/


def ensure_config() -> Path:
    """确保配置文件存在（首次运行生成默认配置），返回路径。"""
    path = config_path()
    if not path.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_default_config_text(), encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"无法生成默认配置文件 {path}：{exc}") from exc
    return path


def load_dns64() -> list[str]:
    """读取启用的 DNS64 地址列表（顺序即写入序）。

    解析失败或启用数不合法 → ConfigError（GUI 预览标红、[切换] 拒绝执行）。
    """
    path = ensure_config()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件 {path}：{exc}") from exc
    try:
        data = yaml.safe_load(text)
    except (yaml.YAMLError, RecursionError) as exc:
        raise ConfigError(f"配置文件 YAML 解析失败：{exc}") from exc

    if not isinstance(data, dict) or "dns64" not in data:
        raise ConfigError("配置文件缺少 dns64 列表（顶层键 dns64）")
    items = data["dns64"]
    if items is None:  # `dns64:` 后全部注释 → 视为空列表（全部停用）
        items = []
    if not isinstance(items, list):
        raise ConfigError("dns64 配置项必须是地址列表")

    servers: list[str] = []
    for i, item in enumerate(items):
        addr = str(item).strip()
        if not addr or addr.startswith("#"):
            continue
        try:
            ipaddress.IPv6Address(addr)
        except (ipaddress.AddressValueError, ValueError) as exc:
            raise ConfigError(f"dns64 第 {i + 1} 项（{addr}）不是合法 IPv6 地址：{exc}") from exc
        servers.append(addr)
        if len(servers) >= MAX_DNS64:
            break  # 按文件顺序取前 MAX_DNS64 条，其余忽略

    if not servers:
        raise ConfigError("dns64 列表为空：至少启用 1 个地址（行首 # 为停用）")
    return servers
