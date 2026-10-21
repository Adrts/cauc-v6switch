"""生成 build/compile_commands.json，供 clangd 使用。

由根 Makefile 的 `compile-db` 目标调用。仅依赖标准库，不进入应用依赖。
每个源文件对应一条与 Makefile 编译命令一致的条目（clangd 需要 -I/-D 与目标平台选项）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 clangd 编译数据库")
    parser.add_argument("--cxx", required=True, help="编译器完整路径")
    parser.add_argument("--root", default=".", help="项目根目录")
    parser.add_argument("--out", required=True, help="输出文件（如 build/compile_commands.json）")
    parser.add_argument("--cxxflags", default="", help="编译选项（空格分隔）")
    parser.add_argument("--include", action="append", default=[], help="头文件搜索目录，可重复")
    parser.add_argument("--define", action="append", default=[], help="预定义宏，可重复")
    parser.add_argument("sources", nargs="+", help="源文件列表（相对项目根）")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out = Path(args.out)
    if not out.is_absolute():
        out = (root / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    base_flags = args.cxxflags.split()
    include_flags = [f"-I{path}" for path in args.include]
    define_flags = [f"-D{name}" for name in args.define]

    entries = []
    for source in args.sources:
        src = Path(source)
        if not src.is_absolute():
            src = root / src
        src = src.resolve()
        obj = root / "build" / "obj" / (src.stem + ".o")
        argv = [
            args.cxx,
            *base_flags,
            *include_flags,
            *define_flags,
            "-c",
            str(src),
            "-o",
            str(obj),
        ]
        entries.append(
            {
                "directory": str(root),
                "file": str(src),
                "command": subprocess.list2cmdline(argv),
            }
        )

    out.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"compile_commands: {len(entries)} entries -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
