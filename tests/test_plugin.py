"""The Claude Code plugin manifests must stay valid and internally consistent.

These are cheap structural guards, not a substitute for `claude plugin validate`
or a manual install smoke test: they catch a typo'd JSON file, a renamed source
path, or a dropped MCP command before it ships to users.
"""
import json
import os

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(*parts):
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as fh:
        return json.load(fh)


def test_marketplace_points_at_the_plugin():
    mkt = _load(".claude-plugin", "marketplace.json")
    assert mkt["name"] == "culprit"
    assert "owner" in mkt and mkt["owner"].get("name")
    entries = mkt["plugins"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["name"] == "culprit"
    # Relative source so `/plugin marketplace add owner/repo` resolves it in-repo.
    assert entry["source"] == "./plugin"
    # The source path must actually contain a plugin manifest.
    assert os.path.isfile(os.path.join(_ROOT, "plugin", ".claude-plugin", "plugin.json"))


def test_plugin_manifest_declares_the_mcp_server():
    plug = _load("plugin", ".claude-plugin", "plugin.json")
    assert plug["name"] == "culprit"
    assert plug.get("version")
    server = plug["mcpServers"]["culprit"]
    assert server["command"] == "uvx"
    # Zero-install launch of the published package's MCP entry point.
    assert server["args"] == ["--from", "culprit[mcp]", "culprit-mcp"]


def test_marketplace_and_plugin_versions_do_not_conflict():
    # The version lives in plugin.json only; a marketplace entry that also pins a
    # version silently overrides nothing but invites drift, so it must be absent.
    mkt = _load(".claude-plugin", "marketplace.json")
    assert "version" not in mkt["plugins"][0]


def test_bundled_skill_is_present_and_described():
    skill = os.path.join(_ROOT, "plugin", "skills", "rca", "SKILL.md")
    assert os.path.isfile(skill)
    with open(skill, encoding="utf-8") as fh:
        text = fh.read()
    # YAML frontmatter with a non-empty description drives auto-invocation.
    assert text.startswith("---")
    front = text.split("---", 2)[1]
    assert "description:" in front
    desc = front.split("description:", 1)[1].strip()
    assert len(desc) > 40
    # No leftover template placeholders in the shipped skill.
    for placeholder in ("<REPO_PATH>", "<BASE_BRANCH>", "<RCA>"):
        assert placeholder not in text


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
