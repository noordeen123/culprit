"""Per-repo configuration so culprit can track a repo's real base branch (and host).

Resolution order for the default base (local mode only - a PR always carries
its own base):
  1. ``--base`` on the CLI (handled by the caller)
  2. ``CULPRIT_BASE`` environment variable
  3. ``base = "..."`` in a ``.culprit.toml`` at the repo root
  4. None -> fall back to the latest commit (HEAD~1)

``host`` (``CULPRIT_HOST`` / ``host = "gitlab"``) overrides host auto-detection
for self-hosted forges where the URL alone can't tell GitHub from GitLab/Gitea.

The ``.culprit.toml`` parse is intentionally tiny (one regex, no TOML dep) so
the package stays dependency-free on Python 3.9.
"""
from __future__ import annotations

import os
import re
from typing import Optional


def _get(repo: str, key: str, env: str) -> Optional[str]:
    val = os.environ.get(env)
    if val:
        return val.strip()
    path = os.path.join(repo, ".culprit.toml")
    try:
        with open(path) as fh:
            text = fh.read()
    except (IOError, OSError):
        return None
    m = re.search(r"""^\s*{}\s*=\s*['"]?([^'"\n#]+?)['"]?\s*(?:#.*)?$""".format(re.escape(key)),
                  text, re.M)
    return m.group(1).strip() if m else None


def repo_base(repo: str) -> Optional[str]:
    return _get(repo, "base", "CULPRIT_BASE")


def repo_host(repo: str) -> Optional[str]:
    return _get(repo, "host", "CULPRIT_HOST")
