"""pytest 共享配置：源码路径注入 + 真实 DLL 相关 fixture。"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "app", ROOT / "tests" / "python"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

DLL_PATH = ROOT / "dist" / "v6core.dll"

# 真实 DLL 端到端用例标记：dist/v6core.dll 不存在时整组跳过
requires_dll = pytest.mark.skipif(
    not DLL_PATH.is_file(), reason="需要真实 dist/v6core.dll（先执行 make dll）"
)


@pytest.fixture(scope="session")
def real_dll_path() -> Path:
    return DLL_PATH
