"""PyInstaller 打包前的 PySide6 裁剪（设计文档 §5.6 打包体积裁剪）。

原理：PyInstaller 按"插件目录整目录收集 + 二进制依赖扫描"打包 Qt，`--exclude-module`
拦不住这两条路径。本脚本把 venv 中确定不用的文件改名为 *.disabled（幂等、可逆：
把后缀改回即恢复），使其在依赖扫描时自然缺席。

裁剪对象与本工具的使用面（仅 QtWidgets/QtCore/Gui，QApplication 光栅渲染）：
- opengl32sw.dll                 软件渲染 OpenGL 回退（约 20MB）；GPU 环境无需
- platforminputcontexts/qtvirtualkeyboardplugin.dll
                                 虚拟键盘输入上下文 → 链 Qt6VirtualKeyboard →
                                 连坐拉入 Qt6Quick/Qt6Qml 全家族（约 20MB）
- imageformats/qpdf.dll          PDF 图像读取 → 拉入 Qt6Pdf（约 4.6MB）
- networkinformation/qnetworklistmanager.dll
                                 QNetworkInformation → 拉入 Qt6Network（约 1.8MB）
- generic/qtuiotouchplugin.dll   触摸输入插件 → 链 Qt6Network（Qt6Network 的另一引用源）
- platforms/qdirect2d.dll        备选 direct2d 平台插件；默认平台为 qwindows

仅影响 venv 内副本（exe 打包源），不影响已打出的 dist 产物；venv 重装后重跑
`make exe` 会再次裁剪。GUI/CLI 功能不受影响（pytest offscreen 用例验证）。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 相对 PySide6 包目录的待停用文件
TRIM_LIST = [
    "opengl32sw.dll",
    "plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll",
    "plugins/imageformats/qpdf.dll",
    "plugins/networkinformation/qnetworklistmanager.dll",
    "plugins/generic/qtuiotouchplugin.dll",
    "plugins/platforms/qdirect2d.dll",
]


def main() -> int:
    verbose = "-v" in sys.argv
    pkg = Path(sys.executable).resolve().parent.parent / "Lib" / "site-packages" / "PySide6"
    if not pkg.is_dir():
        print(f"[trim] PySide6 不存在（{pkg}），跳过")
        return 0
    disabled = 0
    for rel in TRIM_LIST:
        src = pkg / rel
        dst = src.with_name(src.name + ".disabled")
        if src.is_file():
            src.rename(dst)
            disabled += 1
            if verbose:
                print(f"[trim] 已停用 {rel}")
        elif dst.is_file():
            if verbose:
                print(f"[trim] 已是停用状态 {rel}")
        else:
            if verbose:
                print(f"[trim] 未找到（跳过） {rel}")
    print(f"[trim] 完成：本次停用 {disabled} 项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
