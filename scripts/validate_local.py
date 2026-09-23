"""仓库自带的离线打包前检查，不宣称宿主加载成功。"""
import json
from pathlib import Path
import re
import tomllib


def validate(root):
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    for name in [".codex-plugin/plugin.json", ".zcode-plugin/plugin.json", "kimi.plugin.json"]:
        manifest = json.loads((root / name).read_text())
        assert manifest["name"] == "codereview-plugin", name
        assert manifest["version"] == version, name
        assert (root / manifest["skills"]).is_dir(), name
        assert "[TODO:" not in json.dumps(manifest), name
    assert "hooks" not in json.loads((root / ".codex-plugin/plugin.json").read_text())
    inventory = json.loads((root / "plugin-local-skills.json").read_text())
    lock = json.loads((root / "skills.lock.json").read_text())
    assert inventory == {"version": 1, "dest": "skills/", "skills": ["codereview"]}
    assert lock["version"] == 1
    managed = [name for source in lock["sources"] for name in source["skills"]]
    assert len(managed) == len(set(managed)) == 7
    assert sorted(source["package"] for source in lock["sources"]) == ["codereview-skills", "open-code-review"]
    assert "codereview" not in managed
    actual = sorted(p.parent.name for p in (root / "skills").glob("*/SKILL.md"))
    assert actual == sorted(managed + inventory["skills"])
    for skill in (root / "skills").glob("*/SKILL.md"):
        text = skill.read_text()
        assert text.startswith("---\nname: " + skill.parent.name + "\n")
        assert "\ndescription: " in text.split("---", 2)[1]
        assert len(text.splitlines()) < 500
        assert "[TODO:" not in text
    for md in (root / "skills").rglob("*.md"):
        for link in re.findall(r"\]\(([^)]+)\)", md.read_text()):
            if "://" in link or link.startswith("#"):
                continue
            target = (md.parent / link.split("#")[0]).resolve()
            skill_root = root / "skills" / md.relative_to(root / "skills").parts[0]
            assert target.is_relative_to(skill_root.resolve()), link
            assert target.exists(), link
    shared = json.loads((root / "hooks/hooks.json").read_text())["hooks"]
    kimi = json.loads((root / "kimi.plugin.json").read_text())["hooks"]
    expected = {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"}
    assert set(shared) == {item["event"] for item in kimi} == expected
    assert (root / "hooks/entry.py").is_file()
    assert (root / "scripts/codereview.py").is_file()
    return version


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    print("Local structure valid:", validate(root), "(host runtime UNVERIFIED)")
