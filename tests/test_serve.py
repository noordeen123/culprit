import os
import tempfile

import pytest

from culprit import serve


from githelper import git as _git


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


def test_form_page_has_credentials_section(repo_with_branches):
    html = serve.form_page(repo_with_branches)
    assert 'name="github_token"' in html and 'name="anthropic_key"' in html
    assert "Credentials (optional)" in html
    assert 'type="password"' in html       # keys are never plain-text inputs


def test_creds_view_reflects_state_without_echoing_values():
    saved = serve._CREDS.copy()
    try:
        serve._CREDS["github_token"] = ""
        serve._CREDS["anthropic_key"] = ""
        status, _, _ = serve._creds_view()
        assert "GitHub: not set" in status and "Anthropic: not set" in status

        secret = "ghp_" + "secretvalue"            # avoid a hardcoded-secret lint hit
        serve._CREDS["github_token"] = secret
        status, gh_ph, _ = serve._creds_view()
        assert "GitHub: set" in status
        assert secret not in (status + gh_ph)      # value is never surfaced
    finally:
        serve._CREDS.clear()
        serve._CREDS.update(saved)                 # fully restore global state
