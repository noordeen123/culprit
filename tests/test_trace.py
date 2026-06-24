import os
import subprocess
import tempfile

import pytest

from culprit import cli, trace


def _git(repo, *args, **kw):
    env = dict(os.environ, **kw.get("env", {}))
    subprocess.run(["git", "-C", repo, *args], check=True, env=env,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def test_parse_handles_multiple_languages():
    text = (
        'Traceback (most recent call last):\n'
        '  File "app/calc.py", line 3, in area\n'
        '    return w + h\n'
        'TypeError: bad\n'
        '    at run (/srv/app/service.js:12:9)\n'
        '\tat com.acme.Foo.bar(Foo.java:42)\n'
        '\t/go/src/app/main.go:7 +0x1d\n'
    )
    frames = trace.parse(text)
    langs = {f["lang"] for f in frames}
    assert {"python", "js", "java", "go"} <= langs
    py = next(f for f in frames if f["lang"] == "python")
    assert py["file"] == "app/calc.py" and py["line"] == 3


@pytest.fixture()
def crash_repo():
    """area() was correct, a 'perf' commit broke it; HEAD has the buggy line."""
    d = tempfile.mkdtemp(prefix="culprit-trace-")
    _git(d, "init", "-b", "main")
    _git(d, "config", "user.email", "t@t.test")
    _git(d, "config", "user.name", "Tester")
    app = os.path.join(d, "calc.py")

    def commit(body, msg, when):
        with open(app, "w") as fh:
            fh.write(body)
        _git(d, "add", "calc.py")
        _git(d, "commit", "-m", msg, env={"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when})

    commit("def area(w, h):\n    return w * h\n", "feat: add area", "2025-01-01T10:00:00")
    commit("def area(w, h):\n    return w + h\n", "perf: simplify area", "2025-06-01T10:00:00")
    return d


def test_resolve_files_matches_basename(crash_repo):
    frames = [{"file": "calc.py", "line": 2, "func": "area", "lang": "python"}]
    resolved, skipped = trace.resolve_files(crash_repo, frames)
    assert resolved and resolved[0]["file"] == "calc.py"
    assert not skipped


def test_rca_from_trace_blames_the_crashing_line(crash_repo):
    # A traceback pointing at the buggy return line should blame the 'perf' commit -
    # no fix, no PR, no test required.
    tb = 'Traceback (most recent call last):\n  File "calc.py", line 2, in area\n    return w + h\n'
    result = cli.analyze_trace(crash_repo, tb)
    sus = result["bugfix"]["suspects"]
    assert sus, "expected a suspect from the crashing line"
    assert "simplify area" in sus[0]["subject"]
    assert result["trace"]["frames"][0]["file"] == "calc.py"


def test_unresolved_trace_raises(crash_repo):
    with pytest.raises(SystemExit):
        cli.analyze_trace(crash_repo, 'File "nonexistent_xyz.py", line 9, in foo\n')


def test_resolve_preserves_leading_dot_dir(tmp_path):
    # A file under a dot-directory must resolve: the old lstrip("./") wrongly ate the
    # leading dot (".scripts/run.py" -> "scripts/run.py") and failed to match.
    d = str(tmp_path)
    _git(d, "init", "-b", "main")
    _git(d, "config", "user.email", "t@t.test")
    _git(d, "config", "user.name", "Tester")
    os.makedirs(os.path.join(d, ".scripts"))
    with open(os.path.join(d, ".scripts", "run.py"), "w") as fh:
        fh.write("x = 1\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-m", "init")
    resolved, skipped = trace.resolve_files(
        d, [{"file": ".scripts/run.py", "line": 1, "func": "f", "lang": "python"}])
    assert resolved and resolved[0]["file"] == ".scripts/run.py"
