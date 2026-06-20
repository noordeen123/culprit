import os
import subprocess
import tempfile

import pytest

from culprit import serve


def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


@pytest.fixture()
def repo_with_branches():
    d = tempfile.mkdtemp(prefix="culprit-serve-")
    _git(d, "init", "-b", "main")
    _git(d, "config", "user.email", "t@t.test")
    _git(d, "config", "user.name", "Tester")
    app = os.path.join(d, "calc.py")
    with open(app, "w") as fh:
        fh.write("def area(w, h):\n    return w + h\n")
    _git(d, "add", "calc.py"); _git(d, "commit", "-m", "feat: add area")
    _git(d, "checkout", "-b", "fix/area")
    with open(app, "w") as fh:
        fh.write("def area(w, h):\n    return w * h\n")
    _git(d, "add", "calc.py"); _git(d, "commit", "-m", "fix: area multiply")
    return d


def test_candidate_bases_includes_main(repo_with_branches):
    bases = serve.candidate_bases(repo_with_branches)
    assert "main" in bases
    assert "fix/area" in bases  # local branches are offered too


def test_candidate_bases_prefers_config(repo_with_branches):
    with open(os.path.join(repo_with_branches, ".culprit.toml"), "w") as fh:
        fh.write('base = "main"\n')
    bases = serve.candidate_bases(repo_with_branches)
    assert bases[0] == "main"  # configured base leads


def test_form_page_renders_base_picker(repo_with_branches):
    html = serve.form_page(repo_with_branches)
    assert "<form" in html and 'name="base"' in html
    assert "main" in html


def test_run_report_produces_html(repo_with_branches):
    html = serve.run_report({
        "repo": [repo_with_branches], "base": ["main"], "head": ["fix/area"],
        "force": ["bugfix"], "mode": ["harness"],
    })
    assert html.startswith("<!DOCTYPE html>")
    assert "New analysis" in html          # back-link injected
    assert "How it broke" in html          # timeline rendered
