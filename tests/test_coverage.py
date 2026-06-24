from culprit import coverage

# A fix that adds two lines (2 and 3) to a.py.
_DIFF = (
    "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
    "@@ -1,1 +1,3 @@\n x = 1\n+y = 2\n+z = 3\n"
)


def test_lcov_uncovered_changed_lines(tmp_path):
    # line 2 covered, line 3 instrumented but not covered -> 3 is the uncovered change.
    lcov = "SF:a.py\nDA:1,5\nDA:2,1\nDA:3,0\nend_of_record\n"
    p = tmp_path / "cov.info"
    p.write_text(lcov)
    cov = coverage.parse(str(p))
    res = coverage.analyze(_DIFF, cov)
    assert res["uncovered"] == {"a.py": [3]}
    assert res["files_with_uncovered"] == 1


def test_cobertura_parsing(tmp_path):
    xml = (
        '<?xml version="1.0"?>\n<coverage>\n<packages><package><classes>'
        '<class filename="a.py"><lines>'
        '<line number="2" hits="1"/><line number="3" hits="0"/>'
        '</lines></class></classes></package></packages></coverage>\n'
    )
    p = tmp_path / "coverage.xml"
    p.write_text(xml)
    cov = coverage.parse(str(p))
    res = coverage.analyze(_DIFF, cov)
    assert res["uncovered"] == {"a.py": [3]}


def test_fully_covered_change_has_no_gap(tmp_path):
    lcov = "SF:a.py\nDA:2,1\nDA:3,4\nend_of_record\n"
    p = tmp_path / "cov.info"
    p.write_text(lcov)
    res = coverage.analyze(_DIFF, coverage.parse(str(p)))
    assert res["uncovered"] == {}
    assert res["files_with_uncovered"] == 0
