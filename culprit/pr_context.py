"""Resolve the analysis target into a normalized context dict.

Two sources, in priority order:
  1. A GitHub PR via ``gh`` (title, body, labels, refs, commits, files, diff).
  2. Local git only (current/named branch vs a base) when there's no PR or no
     gh auth — fully offline, loses PR title/labels/linked-issue signal.

The returned dict is the single input every downstream step consumes, so the
rest of the engine never cares which source produced it.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from . import _proc

# git's well-known empty-tree object, used to diff a root commit against nothing.
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _changed_files(repo: str, base: str, head: str) -> List[str]:
    out = _proc.git(["diff", "--name-only", "{}...{}".format(base, head)], repo)
    return [line for line in out.splitlines() if line.strip()]


def _rev(repo: str, ref: str) -> Optional[str]:
    try:
        return _proc.git(["rev-parse", ref], repo).strip()
    except _proc.ProcError:
        return None


def _remote_web_url(repo: str) -> Optional[str]:
    """Normalize `origin` to a browseable web URL (for deep links). Best-effort."""
    try:
        url = _proc.git(["remote", "get-url", "origin"], repo).strip()
    except _proc.ProcError:
        return None
    if not url:
        return None
    if url.startswith("ssh://"):
        url = url[len("ssh://"):]
    if url.startswith("git@") and ":" in url:           # git@github.com:owner/repo.git
        host, path = url[4:].split(":", 1)
        url = "https://{}/{}".format(host, path)
    elif url.startswith("git@"):
        url = "https://" + url[4:]
    if url.endswith(".git"):
        url = url[:-4]
    return url if url.startswith("http") else None


def _commit_date(repo: str, rev: Optional[str]) -> Optional[str]:
    if not rev:
        return None
    out = _proc.git(["show", "-s", "--format=%aI", str(rev)], repo, check=False).strip()
    return out.splitlines()[0] if out else None


# ── host detection + deep-link templates (multi-forge) ───────────────────────

def _remote_parts(repo: str):
    """(host, 'owner/repo', web_url) from origin, or None."""
    url = _remote_web_url(repo)
    if not url:
        return None
    m = re.match(r"https?://([^/]+)/(.+)", url)
    if not m:
        return None
    return m.group(1), m.group(2), url


def host_kind(repo: str) -> str:
    """github | gitlab | bitbucket | gitea | generic (config override wins)."""
    from . import config
    override = config.repo_host(repo)
    if override:
        return override.lower()
    parts = _remote_parts(repo)
    host = (parts[0] if parts else "").lower()
    if "github" in host:
        return "github"
    if "gitlab" in host:
        return "gitlab"
    if "bitbucket" in host:
        return "bitbucket"
    if "gitea" in host or "gogs" in host or "codeberg" in host:
        return "gitea"
    return "generic"


_LINK_TEMPLATES = {
    "github":    {"commit": "/commit/{sha}", "pr": "/pull/{pr}", "file": "/blob/{ref}/{path}",
                  "pr_prefix": "#", "pr_term": "PR"},
    "gitea":     {"commit": "/commit/{sha}", "pr": "/pulls/{pr}", "file": "/src/commit/{ref}/{path}",
                  "pr_prefix": "#", "pr_term": "PR"},
    "gitlab":    {"commit": "/-/commit/{sha}", "pr": "/-/merge_requests/{pr}", "file": "/-/blob/{ref}/{path}",
                  "pr_prefix": "!", "pr_term": "MR"},
    "bitbucket": {"commit": "/commits/{sha}", "pr": "/pull-requests/{pr}", "file": "/src/{ref}/{path}",
                  "pr_prefix": "#", "pr_term": "PR"},
    "generic":   {"commit": "/commit/{sha}", "pr": "/pull/{pr}", "file": "/blob/{ref}/{path}",
                  "pr_prefix": "#", "pr_term": "PR"},
}


def _links(repo: str) -> Dict[str, Optional[str]]:
    """Deep-link URL templates ({sha}/{pr}/{ref}/{path} placeholders) for the host."""
    url = _remote_web_url(repo)
    t = _LINK_TEMPLATES.get(host_kind(repo), _LINK_TEMPLATES["generic"])
    base = (url or "").rstrip("/")
    return {
        "commit": (base + t["commit"]) if url else None,
        "pr": (base + t["pr"]) if url else None,
        "file": (base + t["file"]) if url else None,
        "pr_prefix": t["pr_prefix"],
        "pr_term": t["pr_term"],
    }


def _local_commits(repo: str, base: str, head: str) -> List[Dict[str, str]]:
    fmt = "%H%x1f%an%x1f%aI%x1f%s"
    out = _proc.git(
        ["log", "--no-merges", "--pretty=format:" + fmt, "{}..{}".format(base, head)],
        repo,
        check=False,
    )
    commits = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\x1f")
        if len(parts) == 4:
            commits.append(
                {"sha": parts[0], "author": parts[1], "date": parts[2], "subject": parts[3]}
            )
    return commits


def from_local(repo: str, base: Optional[str] = None, head: Optional[str] = None) -> Dict[str, Any]:
    """Build context from local git alone (no PR API).

    ``base`` None means "the change I just made" — the latest commit
    (``<head>~1``). This is bounded and is almost always what you want for a
    local branch whose upstream base may be far behind. Pass an explicit
    ``base`` (e.g. ``develop``) to analyze a whole branch instead.
    """
    if head is None:
        head = _proc.git(["rev-parse", "--abbrev-ref", "HEAD"], repo).strip()
    if base is None:
        # latest commit only
        base = head + "~1"
        if _rev(repo, base) is None:  # root commit has no parent
            base = _EMPTY_TREE
    elif _rev(repo, base) is None:
        # An explicit base that doesn't exist — fall back to main/master.
        for alt in ("main", "master", "origin/HEAD"):
            if _rev(repo, alt) is not None:
                base = alt
                break
    diff = _proc.git(["diff", "{}...{}".format(base, head)], repo, check=False)
    return {
        "source": "local",
        "kind": "branch",
        "pr_number": None,
        "title": None,
        "body": None,
        "labels": [],
        "head_ref": head,
        "base_ref": base,
        "head_sha": _rev(repo, head),
        "base_sha": _rev(repo, base),
        "head_date": _commit_date(repo, _rev(repo, head)),
        "repo_url": _remote_web_url(repo),
        "repo_host": host_kind(repo),
        "links": _links(repo),
        "commits": _local_commits(repo, base, head),
        "changed_files": _changed_files(repo, base, head),
        "diff": diff,
    }


def from_pr(repo: str, pr: Optional[int] = None) -> Dict[str, Any]:
    """Build context from a GitHub PR via gh. ``pr`` None means the current branch's PR."""
    fields = "title,body,labels,headRefName,baseRefName,commits,files,number"
    args = ["pr", "view"]
    if pr is not None:
        args.append(str(pr))
    args += ["--json", fields]
    meta = json.loads(_proc.gh(args, repo))

    base_ref = meta.get("baseRefName") or "develop"
    head_ref = meta.get("headRefName")
    # Fetch the PR diff text directly from gh (works even without local refs).
    diff_args = ["pr", "diff"]
    if pr is not None:
        diff_args.append(str(pr))
    diff = _proc.gh(diff_args, repo, check=False)

    # Resolve SHAs locally when possible; harmless if the refs aren't fetched.
    base_sha = _rev(repo, base_ref) or _rev(repo, "origin/" + base_ref)
    head_sha = _rev(repo, head_ref) or _rev(repo, "origin/" + (head_ref or ""))

    commits = [
        {
            "sha": c.get("oid"),
            "author": (c.get("authors") or [{}])[0].get("name"),
            "date": c.get("committedDate"),
            "subject": (c.get("messageHeadline") or ""),
        }
        for c in meta.get("commits", [])
    ]
    changed_files = [f.get("path") for f in meta.get("files", []) if f.get("path")]

    return {
        "source": "gh",
        "kind": "pr",
        "pr_number": meta.get("number"),
        "title": meta.get("title"),
        "body": meta.get("body"),
        "labels": [l.get("name") for l in meta.get("labels", []) if l.get("name")],
        "head_ref": head_ref,
        "base_ref": base_ref,
        "head_sha": head_sha,
        "base_sha": base_sha,
        "head_date": _commit_date(repo, head_sha),
        "repo_url": _remote_web_url(repo),
        "repo_host": host_kind(repo),
        "links": _links(repo),
        "commits": commits,
        "changed_files": changed_files,
        "diff": diff,
    }


def _api_get(url: str, headers: Dict[str, str]) -> Optional[Dict[str, Any]]:
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, OSError):
        return None


def _build_rest(repo: str, source: str, pr_number, title, body, labels,
                head_ref, base_ref, pr_ref: str) -> Optional[Dict[str, Any]]:
    """Shared tail: read-only fetch of PR head + base, then assemble the context."""
    _proc.git(["fetch", "origin", pr_ref], repo, check=False)
    head_sha = _proc.git(["rev-parse", "FETCH_HEAD"], repo, check=False).strip()
    _proc.git(["fetch", "origin", base_ref], repo, check=False)
    base_sha = (_proc.git(["rev-parse", "FETCH_HEAD"], repo, check=False).strip()
                or _rev(repo, "origin/" + base_ref))
    if not head_sha or not base_sha:
        return None
    diff = _proc.git(["diff", "{}...{}".format(base_sha, head_sha)], repo, check=False)
    return {
        "source": source, "kind": "pr",
        "pr_number": pr_number, "title": title, "body": body, "labels": labels,
        "head_ref": head_ref, "base_ref": base_ref,
        "head_sha": head_sha, "base_sha": base_sha,
        "head_date": _commit_date(repo, head_sha),
        "repo_url": _remote_web_url(repo),
        "repo_host": host_kind(repo),
        "links": _links(repo),
        "commits": _local_commits(repo, base_sha, head_sha),
        "changed_files": _changed_files(repo, base_sha, head_sha),
        "diff": diff,
    }


def from_pr_rest(repo: str, pr: int) -> Optional[Dict[str, Any]]:
    """Public-repo PR/MR context with no ``gh`` auth: the forge's REST API for
    metadata + a read-only ``git fetch`` of the PR head and base. Supports GitHub
    and GitLab; returns None for other hosts or on any failure (→ local fallback).
    """
    parts = _remote_parts(repo)
    if parts is None:
        return None
    host, path, _ = parts
    kind = host_kind(repo)

    if kind == "github":
        headers = {"User-Agent": "culprit", "Accept": "application/vnd.github+json"}
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = "Bearer " + token
        meta = _api_get("https://api.github.com/repos/{}/pulls/{}".format(path, pr), headers)
        if not meta:
            return None
        return _build_rest(
            repo, "github-rest", meta.get("number"), meta.get("title"), meta.get("body"),
            [l.get("name") for l in meta.get("labels", []) if l.get("name")],
            (meta.get("head") or {}).get("ref"), (meta.get("base") or {}).get("ref") or "main",
            "pull/{}/head".format(pr))

    if kind == "gitlab":
        headers = {"User-Agent": "culprit"}
        token = os.environ.get("GITLAB_TOKEN")
        if token:
            headers["PRIVATE-TOKEN"] = token
        enc = urllib.parse.quote(path, safe="")
        meta = _api_get("https://{}/api/v4/projects/{}/merge_requests/{}".format(host, enc, pr), headers)
        if not meta:
            return None
        labels = meta.get("labels") or []  # GitLab returns a list of strings
        return _build_rest(
            repo, "gitlab-rest", meta.get("iid"), meta.get("title"), meta.get("description"),
            labels, meta.get("source_branch"), meta.get("target_branch") or "main",
            "merge-requests/{}/head".format(pr))

    return None


def resolve(repo: str, pr: Optional[int] = None, base: Optional[str] = None,
            head: Optional[str] = None) -> Dict[str, Any]:
    """Pick the best available source.

    For an explicit PR: try ``gh``, then the unauthenticated GitHub REST API,
    then local git. Otherwise use ``gh`` for the current branch's PR if authed,
    else local git.
    """
    if pr is not None:
        if _proc.have_gh():
            try:
                return from_pr(repo, pr)
            except _proc.ProcError:
                pass
        rest = from_pr_rest(repo, pr)
        if rest is not None:
            return rest
        return from_local(repo, base=base, head=head)

    if _proc.have_gh():
        try:
            return from_pr(repo, None)
        except _proc.ProcError:
            pass
    return from_local(repo, base=base, head=head)
