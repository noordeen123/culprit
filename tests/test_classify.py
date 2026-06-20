from culprit import classify


def test_bugfix_from_branch_and_title():
    ctx = {
        "head_ref": "fix/module-preview-size",
        "title": "fix: module preview should match rendered box size",
        "labels": ["bug"],
        "commits": [{"subject": "fix: clamp box height"}],
    }
    r = classify.classify(ctx)
    assert r["verdict"] == "bugfix"
    assert r["confidence"] > 0.6
    assert r["evidence"]


def test_feature_from_branch_and_label():
    ctx = {
        "head_ref": "feat/global-settings",
        "title": "Add global setting to module editor",
        "labels": ["enhancement"],
        "commits": [{"subject": "feat: add global setting"}],
    }
    r = classify.classify(ctx)
    assert r["verdict"] == "feature"


def test_bugfix_tolerates_leading_punctuation():
    ctx = {
        "head_ref": "module-bug-fixes",
        "title": None,
        "labels": [],
        "commits": [{"subject": "- fix : Module preview should match rendered box size"}],
    }
    r = classify.classify(ctx)
    assert r["verdict"] == "bugfix"


def test_unknown_when_no_signal():
    r = classify.classify({"head_ref": "wip", "title": "", "labels": [], "commits": []})
    assert r["verdict"] == "unknown"
    assert r["confidence"] == 0.0
