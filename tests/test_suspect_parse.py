from culprit import suspect


def test_parse_removed_lines():
    diff = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -10,4 +10,4 @@ def f():
 keep
-buggy line one
-buggy line two
+fixed line
 keep
"""
    files = suspect._parse_hunks(diff)
    assert len(files) == 1
    f = files[0]
    assert f["old_path"] == "app.py"
    # removed run covers old lines 11..12
    assert (11, 12) in f["removed_ranges"]


def test_pure_addition_uses_context():
    diff = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -5,3 +5,4 @@ def g():
 a
+added guard
 b
 c
"""
    files = suspect._parse_hunks(diff)
    f = files[0]
    assert f["removed_ranges"] == []
    assert f["context_ranges"] == [(5, 7)]
