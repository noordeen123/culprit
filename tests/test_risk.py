from culprit import risk


def test_level_at_least_ordering():
    assert risk.level_at_least("high", "medium") is True
    assert risk.level_at_least("medium", "medium") is True
    assert risk.level_at_least("low", "medium") is False


def test_clean_one_liner_scores_low():
    result = {
        "target": {"changed_files": ["a.py"]},
        "bugfix": {
            "test_gap": {"untested": [], "covering_tests": ["a_test.py"]},
            "completeness": {"untouched_count": 0, "adds_test": True, "is_revert": False},
            "lifecycle": {"recurrence": {"is_hotspot": False, "fix_count": 0}},
        },
        "feature": None,
    }
    r = risk.score(result)
    assert r["level"] == "low"
    assert r["score"] < 30


def test_hotspot_with_gaps_scores_high():
    result = {
        "target": {"changed_files": ["a.py", "b.py", "c.py"]},
        "bugfix": {
            "test_gap": {"untested": ["a.py", "b.py", "c.py"]},
            "completeness": {"untouched_count": 5, "adds_test": False, "is_revert": False},
            "lifecycle": {"recurrence": {"is_hotspot": True, "fix_count": 7}},
        },
        "feature": None,
    }
    r = risk.score(result)
    assert r["level"] == "high"
    assert r["score"] >= 60
    names = {f["name"] for f in r["factors"]}
    assert {"test gap", "incomplete fix", "hotspot"} <= names


def test_feature_blast_radius_contributes():
    result = {
        "target": {"changed_files": ["lib/x.js"]},
        "bugfix": None,
        "feature": {"total_dependents": 40, "high_risk": ["lib/x.js", "core/y.js"]},
    }
    r = risk.score(result)
    names = {f["name"] for f in r["factors"]}
    assert "blast radius" in names and "high-risk modules" in names
    assert r["score"] > 0


def test_no_signals_scores_zero():
    r = risk.score({"target": {"changed_files": []}, "bugfix": None, "feature": None})
    assert r["score"] == 0 and r["level"] == "low" and r["factors"] == []
