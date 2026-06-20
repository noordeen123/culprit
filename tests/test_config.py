import os
import tempfile

from culprit import config


def test_reads_base_from_toml():
    d = tempfile.mkdtemp(prefix="culprit-cfg-")
    with open(os.path.join(d, ".culprit.toml"), "w") as fh:
        fh.write('# comment\nbase = "origin/release-2.x"  # trailing comment\n')
    assert config.repo_base(d) == "origin/release-2.x"


def test_env_overrides_toml(monkeypatch):
    d = tempfile.mkdtemp(prefix="culprit-cfg-")
    with open(os.path.join(d, ".culprit.toml"), "w") as fh:
        fh.write('base = "develop"\n')
    monkeypatch.setenv("CULPRIT_BASE", "main")
    assert config.repo_base(d) == "main"


def test_none_when_absent(monkeypatch):
    monkeypatch.delenv("CULPRIT_BASE", raising=False)
    d = tempfile.mkdtemp(prefix="culprit-cfg-")
    assert config.repo_base(d) is None
