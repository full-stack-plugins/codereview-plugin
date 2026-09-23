#!/usr/bin/env python3
"""OCR v1.12.x 双模式协议夹具；不访问网络或模型。"""
import json
import os
from pathlib import Path
import sys


args = sys.argv[1:]
if args == ["--version"]:
    print(os.environ.get("OCR_FIXTURE_VERSION") or "open-code-review v1.12.9")
    raise SystemExit(0)

if args == ["review", "--help"]:
    print("--repo --commit --format --audience --preview --output")
    raise SystemExit(0)

if args in (["delegate", "preview", "--help"], ["delegate", "rule", "--help"]):
    print("--repo --commit --format")
    raise SystemExit(0)

if args[:2] == ["delegate", "preview"]:
    recorded = os.environ.get("OCR_FIXTURE_PREVIEW_FILE")
    if recorded:
        print(Path(recorded).read_text())
        raise SystemExit(0)
    # 与真实 v1.12.9 (bccbc15) 输出同形：schema_version + 整数 group_id（见验收记录）。
    print(json.dumps({
        "schema_version": "1",
        "mode": "commit",
        "repository": args[args.index("--repo") + 1],
        "commit": args[args.index("--commit") + 1],
        "background": "baseline",
        "total_files": 1,
        "reviewable_count": 1,
        "excluded_count": 0,
        "total_insertions": 1,
        "total_deletions": 1,
        "reviewable_files": [{"path": "a.py", "status": "modified",
                              "insertions": 1, "deletions": 1}],
        "excluded_files": [],
    }))
    raise SystemExit(0)

if args[:2] == ["delegate", "rule"]:
    recorded = os.environ.get("OCR_FIXTURE_RULE_FILE")
    if recorded:
        print(Path(recorded).read_text())
        raise SystemExit(0)
    print(json.dumps({
        "schema_version": "1",
        "groups": [{
            "group_id": 1,
            "source": "system",
            "pattern": "**/*.py",
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
    recorded = os.environ.get("OCR_FIXTURE_RESULT_FILE")
    if recorded:
        output.write_text(Path(recorded).read_text())
    else:
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
