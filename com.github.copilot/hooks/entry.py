"""快速 Hook 入口；不运行审查、不询问终端。"""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codereview_core.cli import error_code
from codereview_core.hosts import handle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", choices=["codex", "zcode", "kimi"])
    args = parser.parse_args()
    host = args.host or ("zcode" if os.environ.get("ZCODE_PLUGIN_ROOT") else "codex")
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise ValueError("request_too_large")
        code, output = handle(host, json.loads(raw))
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as exc:
        code, output = 0, "CodeReview UNVERIFIED: " + error_code(exc) + "; 使用 recover 或手动审查。"
    if output:
        print(output, file=sys.stderr if code == 2 else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
