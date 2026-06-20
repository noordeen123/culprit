from culprit import htmlreport


def _result():
    return {
        "target": {"pr_number": 16889, "title": "Fix: dynamic height", "base_ref": "main",
                   "head_ref": "fix/x", "changed_files": ["a.jsx"], "commit_count": 1},
        "classification": {"verdict": "bugfix", "confidence": 0.6, "score": 1,
                           "evidence": ["title reads like a fix"]},
        "bugfix": {
            "suspects": [{"short": "41eef80849", "subject": "added dynamic height",
                          "author": "Shaurya", "date": "2026-01-20T00:00:00Z",
                          "lines": 6, "weight": 0.5, "pr_number": 14996}],
            "notes": ["pure-addition fix; blaming surrounding context"],
            "timeline": {"ranges": [{
                "file": "a.jsx", "range": [70, 78], "truncated": False,
                "steps": [
                    {"short": "2f0d1a6", "subject": "json explorer added", "role": "origin",
                     "date": "2026-01-18T00:00:00Z", "diff": "@@ -70 +70 @@\n+height: '100%'"},
                    {"short": "41eef80", "subject": "added dynamic height", "role": "suspect",
                     "date": "2026-01-20T00:00:00Z", "diff": "@@ -75 +75 @@\n-old\n+bug"},
                    {"short": "0ece39f", "subject": "THE FIX", "role": "fix",
                     "date": None, "diff": "@@ -76 +77 @@\n+minHeight"},
                ],
            }]},
        },
        "feature": None,
    }


def test_render_is_self_contained_and_has_markers():
    html = htmlreport.render(_result(), narrative_md="## Root cause\nThe `height:100%` had no floor.")
    assert html.startswith("<!DOCTYPE html>")
    assert "__CULPRIT_DATA__" not in html  # placeholder was replaced
    assert "__NARRATIVE__" not in html
    # data + narrative embedded
    assert "41eef80" in html and "json explorer added" in html
    assert "Root cause" in html
    # no external resource loads (offline-safe)
    assert "http://" not in html and "https://" not in html
    assert "src=" not in html  # no external scripts/images


def test_github_deeplinks_when_repo_url_present():
    r = _result()
    r["target"]["repo_url"] = "https://github.com/acme/widget"
    r["target"]["head_sha"] = "0ece39fc10"
    r["target"]["head_date"] = "2026-06-19T00:00:00Z"
    r["target"]["repo_host"] = "github"
    r["target"]["links"] = {
        "commit": "https://github.com/acme/widget/commit/{sha}",
        "pr": "https://github.com/acme/widget/pull/{pr}",
        "file": "https://github.com/acme/widget/blob/{ref}/{path}",
        "pr_prefix": "#", "pr_term": "PR",
    }
    r["bugfix"]["suspects"][0]["hash"] = "41eef80849071ac967581feffbc3579db3f144ac"
    html = htmlreport.render(r)
    # the templates are embedded so the JS builds links at runtime
    assert "https://github.com/acme/widget/commit/{sha}" in html
    assert "ghCommit" in html and "humanAge" in html and "buildMarkdown" in html


def test_gitlab_link_templates_carry_mr_prefix():
    r = _result()
    r["target"]["links"] = {
        "commit": "https://gitlab.com/g/p/-/commit/{sha}",
        "pr": "https://gitlab.com/g/p/-/merge_requests/{pr}",
        "file": "https://gitlab.com/g/p/-/blob/{ref}/{path}",
        "pr_prefix": "!", "pr_term": "MR",
    }
    html = htmlreport.render(r)
    assert "/-/merge_requests/{pr}" in html
    assert '"pr_prefix": "!"' in html or '"pr_prefix":"!"' in html


def test_render_escapes_script_breakout():
    r = _result()
    r["target"]["title"] = "Fix </script><b>x"
    html = htmlreport.render(r)
    # the raw breakout sequence must not appear verbatim in the data node
    assert "</script><b>x" not in html
