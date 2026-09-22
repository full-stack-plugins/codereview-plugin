#!/usr/bin/env python3
"""OCR v1.12.x 双模式协议夹具；不访问网络或模型。"""
import json
import os
from pathlib import Path
import sys


args = sys.argv[1:]
if args == ["--version"]:
    print("open-code-review v1.12.9")
    raise SystemExit(0)

if args == ["review", "--help"]:
    print("--repo --commit --format --audience --preview --output")
    raise SystemExit(0)

if args in (["delegate", "preview", "--help"], ["delegate", "rule", "--help"]):
    print("--repo --commit --format")
    raise SystemExit(0)

if args[:2] == ["delegate", "preview"]:
    print(json.dumps({
        "version": "1",
        "mode": "commit",
        "repository": args[args.index("--repo") + 1],
        "commit": args[args.index("--commit") + 1],
        "reviewable_files": [{"path": "a.py", "status": "modified"}],
        "excluded_files": [],
    }))
    raise SystemExit(0)

if args[:2] == ["delegate", "rule"]:
    print(json.dumps({
        "version": "1",
        "groups": [{
            "group_id": "default",
            "source": "builtin",
            "pattern": "*",
            "files": ["a.py"],
            "rule": "Review correctness, security, performance, and compatibility.",
        }],
    }))
    raise SystemExit(0)

if args and args[0] == "review" and "--preview" in args:
    print(json.dumps({"files": [{"path": "a.py", "will_review": True}]}))
    raise SystemExit(0)

if args and args[0] == "review" and "--output" in args:
    output = Path(args[args.index("--output") + 1])
    output.write_text(json.dumps({
        "status": "success",
        "comments": [],
        "summary": {"files_reviewed": 1},
        "warnings": [],
    }))
    marker = os.environ.get("OCR_TEST_ARGS_FILE")
    if marker:
        Path(marker).write_text(json.dumps(args))
    print("non-json progress is intentionally ignored")
    raise SystemExit(0)

print("unsupported fixture invocation", file=sys.stderr)
raise SystemExit(2)
