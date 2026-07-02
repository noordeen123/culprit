import os
import subprocess
import tempfile

from culprit import pr_context


def _repo_with_remote(url):
    d = tempfile.mkdtemp(prefix="culprit-host-")
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "remote", "add", "origin", url], check=True)
    return d


def test_github_links():
    d = _repo_with_remote("https://github.com/owner/repo.git")
    assert pr_context.host_kind(d) == "github"
    links = pr_context._links(d)
    assert links["commit"].endswith("/commit/{sha}")
    assert links["pr"].endswith("/pull/{pr}")
    assert links["pr_prefix"] == "#" and links["pr_term"] == "PR"


def test_gitlab_links():
    d = _repo_with_remote("git@gitlab.com:group/sub/repo.git")
    assert pr_context.host_kind(d) == "gitlab"
    links = pr_context._links(d)
    assert "/-/merge_requests/{pr}" in links["pr"]
    assert "/-/commit/{sha}" in links["commit"]
    assert links["pr_prefix"] == "!" and links["pr_term"] == "MR"


def test_bitbucket_links():
    d = _repo_with_remote("https://bitbucket.org/owner/repo.git")
    assert pr_context.host_kind(d) == "bitbucket"
    assert "/pull-requests/{pr}" in pr_context._links(d)["pr"]


def test_config_host_override_wins():
    # a GitHub URL but a self-hosted GitLab declared in config
    d = _repo_with_remote("https://git.internal.example.com/team/app.git")
    with open(os.path.join(d, ".culprit.toml"), "w") as fh:
        fh.write('host = "gitlab"\n')
    assert pr_context.host_kind(d) == "gitlab"
