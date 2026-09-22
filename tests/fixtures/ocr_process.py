"""仅用于离线子进程契约测试，不是生产引擎。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

args = sys.argv[1:]
if args == ["--version"]:
    print("open-code-review v1.12.9 (fixture) darwin/arm64")
elif args == ["review", "--help"]:
    print("--commit --repo --format --audience --preview --output --model --background")
elif args in (["delegate", "preview", "--help"], ["delegate", "rule", "--help"]):
    print("--commit --repo --format")
else:
    assert args[0] == "review"
    assert args[args.index("--format") + 1] == "json"
    assert args[args.index("--audience") + 1] == "agent"
    repo = Path(args[args.index("--repo") + 1])
    commit = args[args.index("--commit") + 1]
    assert repo == Path.cwd()
    subprocess.run(["git", "cat-file", "-e", commit + "^{commit}"], check=True)
    if "--preview" in args:
        print(os.environ.get("FIXTURE_PREVIEW") or json.dumps({"files": [{"path": "a.py", "status": "modified", "insertions": 1,
            "deletions": 1, "will_review": True}], "total_files": 1, "reviewable_count": 1,
            "excluded_count": 0, "total_insertions": 1, "total_deletions": 1}))
    else:
        marker = os.environ.get("FIXTURE_MARKER")
        if marker:
            with open(marker, "a") as stream:
                stream.write("review\n")
        time.sleep(float(os.environ.get("FIXTURE_DELAY", "0")))
        output = os.environ.get("FIXTURE_OUTPUT") or json.dumps({"status": "success", "comments": None,
            "summary": {"files_reviewed": 1, "comments": 0, "total_tokens": 10,
                        "input_tokens": 8, "output_tokens": 2, "elapsed": "0s"},
            "tool_calls": {"total": 1, "by_tool": {"file_read": 1}}})
        Path(args[args.index("--output") + 1]).write_text(output)
        print("progress")
