"""把 PyInstaller onedir 产物同步到 dist/v6switch（就地运行，不再解压到临时目录）。

同步规则：
- 保留目标目录中的 config.yaml（用户 DNS64 配置）与 v6core.dll，其余旧文件先清空再复制；
- DLL 由 Makefile 直接链接到 exe 同目录（bindings 按 sys.executable 所在目录探测），此处仅在
  `--dll` 指向其他路径时补拷；
- 首次从单文件分发迁移时，若 dist/config.yaml 存在则移动到新目录（不覆盖已有配置）。
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="同步 PyInstaller onedir 产物")
    parser.add_argument("--src", required=True, help="PyInstaller 输出目录（含 v6switch.exe）")
    parser.add_argument("--dst", required=True, help="交付目录（dist/v6switch）")
    parser.add_argument("--dll", required=True, help="编译产物 v6core.dll")
    parser.add_argument("--config", required=True, help="旧版同目录 config.yaml（可不存在）")
    args = parser.parse_args()

    src = Path(args.src).resolve()
    dst = Path(args.dst).resolve()
    if not (src / "v6switch.exe").is_file():
        raise SystemExit(f"未找到 PyInstaller 产物：{src / 'v6switch.exe'}")

    dst.mkdir(parents=True, exist_ok=True)
    for entry in dst.iterdir():
        if entry.name in ("config.yaml", "v6core.dll"):
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    shutil.copytree(src, dst, dirs_exist_ok=True)

    dll = Path(args.dll).resolve()
    if not dll.is_file():
        raise SystemExit(f"未找到 {dll}")
    if dll != (dst / "v6core.dll").resolve():
        shutil.copy2(dll, dst / "v6core.dll")

    legacy = Path(args.config).resolve()
    target = dst / "config.yaml"
    if legacy.is_file() and not target.exists():
        shutil.move(str(legacy), str(target))
        print(f"CONFIG 已迁移 {legacy} -> {target}")

    print(f"SYNC {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
