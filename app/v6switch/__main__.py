"""GUI 入口：python -m v6switch（唯一交付入口，§5.2）。"""

import sys

from .gui import run

if __name__ == "__main__":
    sys.exit(run())
