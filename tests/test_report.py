from culprit import report


def _bugfix_result(intent_body):
    return {
        "target": {"changed_files": [], "base_ref": "main", "head_ref": "x",
                   "pr_number": None, "title": None},
        "classification": {"verdict": "bugfix", "confidence": 0.6, "score": 1, "evidence": []},
        "bugfix": {
            "suspects": [{"short": "abc", "author": "a", "subject": "s", "pr_number": None,
                          "lines": 1, "weight": 1.0, "files": ["f.py"],
                          "intent": {"body": intent_body, "pr": None, "linked_issues": []}}],
            "lifecycle": {"releases": [], "commits_span": None, "recurrence": None, "notes": []},
            "completeness": {"symbols": [], "other_call_sites": {}, "untouched_count": 0,
                             "adds_test": False, "is_revert": False},
            "timeline": {"ranges": [], "notes": []},
            "test_gap": {"untested": [], "covering_tests": []},
            "notes": [],
        },
        "feature": None,
    }


def test_markdown_skeleton_handles_whitespace_intent_body():
    # A whitespace-only body must not crash (no first line to index) and must
    # not emit a bogus "Stated intent" line.
    md = report.markdown_skeleton(_bugfix_result("   "))
    assert "## Introduced" in md
    assert "Stated intent" not in md


def test_markdown_skeleton_emits_stated_intent_when_body_present():
    md = report.markdown_skeleton(_bugfix_result("Refactor the widget.\nmore"))
    assert "Stated intent: Refactor the widget." in md
