"""admin 模块用例（真实调用，只读，不触发 UAC）。"""

from v6switch import admin


def test_is_admin_returns_bool_without_raise():
    # TokenElevation 路径：pytest 进程通常未提权 → False；提权运行 → True
    assert isinstance(admin.is_admin(), bool)
