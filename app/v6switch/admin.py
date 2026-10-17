"""提权检测与 runas 重启自身（设计文档 FR-5 / §5.2）。

应用启动时自检管理员权限（GUI/CLI 均同），无权限以 runas 重启自身
（一次 UAC），拒绝降权运行；DLL 侧另有 V6_ERR_ADMIN 防御位兜底。
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

_SW_SHOWNORMAL = 1
_MB_ICONERROR = 0x10
_TOKEN_QUERY = 0x0008
_TOKEN_ELEVATION = 20  # TOKEN_INFORMATION_CLASS.TokenElevation


def is_admin() -> bool:
    """当前进程令牌是否已提权（TokenElevation，与 DLL 侧 is_elevated 同源判定）。

    不用 shell32.IsUserAnAdmin()：微软文档已标注其"可能被修改或不可用"。
    """
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        advapi32.OpenProcessToken.argtypes = (
            wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)
        )
        advapi32.OpenProcessToken.restype = wintypes.BOOL
        advapi32.GetTokenInformation.argtypes = (
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        )
        advapi32.GetTokenInformation.restype = wintypes.BOOL

        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)):
            return False
        try:
            elevation = wintypes.DWORD()
            needed = wintypes.DWORD()
            if not advapi32.GetTokenInformation(
                token, _TOKEN_ELEVATION, ctypes.byref(elevation),
                ctypes.sizeof(elevation), ctypes.byref(needed),
            ):
                return False
            return bool(elevation.value)
        finally:
            kernel32.CloseHandle(token)
    except Exception:
        return False


def relaunch_as_admin(module_args: list[str]) -> bool:
    """以 runas 重启自身（触发一次 UAC）。

    module_args：开发期为 `-m` 之后的模块参数（如 ["v6switch"] 或
    ["v6switch.cli", ...]）；frozen（exe）时忽略，按 sys.argv[1:] 透传。
    返回 True 表示已成功发起重启；False 表示用户拒绝或启动失败。
    """
    if getattr(sys, "frozen", False):
        exe = sys.executable
        params = subprocess.list2cmdline(sys.argv[1:])
        work_dir = None
    else:
        exe = sys.executable
        params = subprocess.list2cmdline(["-m", *module_args])
        # 显式指定包目录为工作目录，保证提权后的 `python -m v6switch` 能找到包
        work_dir = str(Path(__file__).resolve().parents[1])
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", exe, params, work_dir, _SW_SHOWNORMAL
    )
    return ret > 32  # >32 成功；否则为 SE_ERR_*（含拒绝 UAC 的 ACCESSDENIED）


def ensure_admin(module_args: list[str], gui: bool = False) -> None:
    """启动自检（FR-5）：无权限 → runas 重启自身（本进程退出）；拒绝提权 → 提示后退出。"""
    if is_admin():
        return
    if relaunch_as_admin(module_args):
        sys.exit(0)  # 新进程已发起，本进程退出
    msg = "需要管理员权限才能修改网络配置。已取消提权，程序即将退出。"
    if gui:
        ctypes.windll.user32.MessageBoxW(
            None, msg, "CAUC IPv6 Switch", _MB_ICONERROR
        )
    else:
        print(msg, file=sys.stderr)
    sys.exit(1)
