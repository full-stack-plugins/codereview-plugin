"""直接运行插件 CLI，不需要 pip 安装。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codereview_core.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
