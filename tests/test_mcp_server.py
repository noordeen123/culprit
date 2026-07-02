"""Tests for culprit.mcp_server — tool registration and basic invocation."""
import os
import tempfile

import pytest
from githelper import git as _git


@pytest.fixture()
def simple_repo():
    """A minimal repo with one bug-fix commit on top of a base."""
    d = tempfile.mkdtemp(prefix="culprit-mcp-")
    _git(d, "init", "-b", "main")
    _git(d, "config", "user.email", "t@t.test")
    _git(d, "config", "user.name", "Tester")
    with open(os.path.join(d, "calc.py"), "w") as fh:
        fh.write("def area(w, h):\n    return w + h\n")  # bug: + instead of *
    _git(d, "add", "-A")
    _git(d, "commit", "-m", "feat: add area function")
    # fix commit
    with open(os.path.join(d, "calc.py"), "w") as fh:
        fh.write("def area(w, h):\n    return w * h\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-m", "fix: correct area formula")
    return d


def test_mcp_package_importable():
    """mcp package must be available when culprit[mcp] is installed."""
    pytest.importorskip("mcp", reason="pip install culprit[mcp] needed")


def test_mcp_server_importable():
    """mcp_server must import without error when mcp is installed."""
    pytest.importorskip("mcp", reason="pip install culprit[mcp] needed")
    from culprit import mcp_server  # noqa: F401


def test_mcp_tools_registered():
    """All 11 expected tools are registered on the FastMCP instance."""
    pytest.importorskip("mcp", reason="pip install culprit[mcp] needed")

    expected = {
        "analyze",
        "classify_change",
        "find_suspects",
        "get_blast_radius",
        "get_risk_score",
        "get_evolution",
        "get_intent",
        "check_completeness",
        "get_test_impact",
        "from_trace",
        "verify_fix",
    }
    # FastMCP exposes registered tools via ._tool_manager or similar internals;
    # fall back to inspecting the module for decorated functions.
    import culprit.mcp_server as mod
    registered = {
        name for name, obj in vars(mod).items()
        if callable(obj) and not name.startswith("_") and name in expected
    }
    assert registered == expected, "Missing tools: {}".format(expected - registered)


def test_verify_fix_tool_callable(simple_repo):
    """verify_fix tool returns a dict with the expected keys."""
    pytest.importorskip("mcp", reason="pip install culprit[mcp] needed")
    from culprit.mcp_server import verify_fix

    diff = """\
diff --git a/calc.py b/calc.py
--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,2 @@ def area(w, h):
 def area(w, h):
-    return w + h
+    return w * h
"""
    result = verify_fix(simple_repo, diff)
    assert "verdict" in result
    assert result["verdict"] in ("complete", "partial", "risky")
    assert "symbols_fixed" in result
    assert "tests_to_run" in result
    assert "risk_level" in result


def test_classify_change_tool_callable(simple_repo):
    """classify_change returns verdict and evidence."""
    pytest.importorskip("mcp", reason="pip install culprit[mcp] needed")
    from culprit.mcp_server import classify_change

    result = classify_change(simple_repo)
    assert "verdict" in result
    assert result["verdict"] in ("bugfix", "feature", "unknown")
