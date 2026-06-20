"""Render a self-contained HTML RCA report from a structured result.

One file, no external CDN, no build step: the template ships as package data,
the result JSON and an optional narrative are injected as text nodes. Open the
output in any browser - works offline.
"""
from __future__ import annotations

import json
from typing import Any, Dict

try:  # Python 3.9+: importlib.resources.files
    from importlib.resources import files as _res_files

    def _template() -> str:
        return _res_files("culprit").joinpath("templates/report.html").read_text(encoding="utf-8")
except Exception:  # pragma: no cover - very old runtimes
    import os

    def _template() -> str:
        here = os.path.dirname(__file__)
        with open(os.path.join(here, "templates", "report.html"), encoding="utf-8") as fh:
            return fh.read()


def _safe_json(obj: Any) -> str:
    # Embedded in a <script type="application/json"> node read via JSON.parse;
    # the only sequence that can break out of the node is "</".
    return json.dumps(obj, default=str).replace("</", "<\\/")


def render(result: Dict[str, Any], narrative_md: str = "") -> str:
    tpl = _template()
    data = _safe_json(result)
    narrative = (narrative_md or "").replace("</script", "<\\/script")
    # Placeholders are unique literals in the template.
    return tpl.replace("__CULPRIT_DATA__", data).replace("__NARRATIVE__", narrative)
