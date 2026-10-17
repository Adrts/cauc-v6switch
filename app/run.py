"""PyInstaller 打包专用入口（设计文档 §5.6，--onefile --noconsole）。

打包入口必须是"脚本"而非"包内模块"：以 app/v6switch/__main__.py 为入口时，
PyInstaller 将其作为无包上下文的顶层脚本执行，包内相对导入
（from .gui import ...）会失败（attempted relative import with no known
parent package）。本文件位于包外，经绝对导入加载 v6switch 包。

开发期入口不变：python -m v6switch（GUI）／python -m v6switch.cli（CLI）。
"""

import sys

from v6switch.gui import run

if __name__ == "__main__":
    sys.exit(run())
