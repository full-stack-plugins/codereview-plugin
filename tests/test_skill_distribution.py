"""受管技能来源和提交前路由边界。"""

import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "scripts/vendor/skill_vendor.py"


def test_distribution_inventory_and_pins():
    lock = json.loads((ROOT / "skills.lock.json").read_text())
    local = json.loads((ROOT / "plugin-local-skills.json").read_text())
    assert local["skills"] == ["codereview"]
    assert {source["package"] for source in lock["sources"]} == {"codereview-skills", "open-code-review"}
    assert all(source["ref"].startswith("v") and len(source["sha"]) == 40 for source in lock["sources"])
    managed = {name for source in lock["sources"] for name in source["skills"]}
    assert len(managed) == 7
    assert managed.isdisjoint(local["skills"])
    assert {path.name for path in (ROOT / "skills").iterdir() if (path / "SKILL.md").exists()} == managed | set(local["skills"])
    result = subprocess.run([sys.executable, str(VENDOR), "check", "--offline"], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_vendor_detects_local_tamper(tmp_path):
    shutil.copy2(ROOT / "skills.lock.json", tmp_path / "skills.lock.json")
    shutil.copy2(ROOT / "plugin-local-skills.json", tmp_path / "plugin-local-skills.json")
    shutil.copytree(ROOT / "skills", tmp_path / "skills")
    target = tmp_path / "skills/codereview-context-impact/SKILL.md"
    target.write_text(target.read_text() + "\nnot upstream\n")
    result = subprocess.run([sys.executable, str(VENDOR), "check", "--offline", "--lock", str(tmp_path / "skills.lock.json")], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode != 0
    assert "codereview-context-impact content differs" in result.stdout


def test_commit_harness_does_not_dispatch_raw_upstream_review():
    harness = (ROOT / "skills/codereview/SKILL.md").read_text()
    assert "不能继承这里的提交授权" in harness
    assert "不在此步骤调用上游技能的裸 `ocr review`" in harness
    for name in ("open-code-review", "open-code-review-delegate"):
        assert (ROOT / "skills" / name / "SKILL.md").is_file()
