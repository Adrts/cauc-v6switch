"""CAUC IPv6 Switch 应用层包。

两个入口共用 bindings（ctypes FFI）与 core_ops（切换/重置编排）：
- GUI（唯一交付入口）：python -m v6switch
- CLI（开发期工具，不随包分发）：python -m v6switch.cli
"""

__version__ = "0.1.0"
