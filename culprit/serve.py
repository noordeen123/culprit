"""Interactive local web UI: `rca serve`.

A zero-dependency local app (stdlib http.server) that lets you pick the base
branch from a dropdown and run a fresh analysis on demand, which a static HTML
file can't do. Binds to localhost only; it runs git against a local repo.

Routes:
  GET /                       landing form (repo, PR/branch, base picker, options)
  GET /api/bases?repo=PATH    JSON list of candidate base refs for a repo
  GET /report?...             runs the analysis, returns the full HTML report
"""
from __future__ import annotations

import html
import json
import os
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from . import _proc, cli, config, htmlreport, reasoning

# Credentials entered through the UI. Kept in this server process's memory ONLY -
# never written to disk and never placed in a URL (they arrive via POST). The
# GitHub token authenticates gh/REST; the Anthropic key powers the API narrative.
_CREDS = {"github_token": "", "anthropic_key": ""}


def _apply_creds() -> None:
    """Expose the GitHub token to child gh/git/REST calls via the environment."""
    if _CREDS["github_token"]:
        os.environ["GH_TOKEN"] = _CREDS["github_token"]
        os.environ["GITHUB_TOKEN"] = _CREDS["github_token"]


def _creds_view():
    """(status line, github placeholder, anthropic placeholder) - never echoes values."""
    status = "GitHub: {} · Anthropic: {}".format(
        "set" if _CREDS["github_token"] else "not set",
        "set" if _CREDS["anthropic_key"] else "not set")
    gh_ph = "saved - leave blank to keep" if _CREDS["github_token"] else "ghp_... or github_pat_..."
    ak_ph = "saved - leave blank to keep" if _CREDS["anthropic_key"] else "sk-ant-..."
    return status, gh_ph, ak_ph


# -- base-branch discovery ----------------------------------------------------

def candidate_bases(repo: str) -> List[str]:
    """Ordered, de-duplicated candidate base refs for a repo.

    configured base (.culprit.toml / CULPRIT_BASE) -> default branch -> all local
    and remote branches. This is what populates the base picker.
    """
    out: List[str] = []

    def add(ref: Optional[str]):
        ref = (ref or "").strip()
        if ref and ref not in out:
            out.append(ref)

    add(config.repo_base(repo))

    # default branch via origin/HEAD, else common names
    head = _proc.git(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], repo, check=False).strip()
    if head.startswith("refs/remotes/"):
        add(head[len("refs/remotes/"):])
    for alt in ("origin/main", "origin/master", "main", "master"):
        if _proc.git(["rev-parse", "--verify", "--quiet", alt], repo, check=False).strip():
            add(alt)

    refs = _proc.git(
        ["for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes"],
        repo, check=False,
    )
    for r in refs.splitlines():
        r = r.strip()
        if r and not r.endswith("/HEAD"):
            add(r)
    return out[:60]


# -- HTML (form + small error page) -------------------------------------------

_STYLE = """
  body{margin:0;background:#0f1115;color:#e6e9ef;
    font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
  .wrap{max-width:640px;margin:0 auto;padding:48px 20px;}
  .brand{font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:#9aa3b2;}
  h1{font-size:24px;margin:6px 0 4px;font-weight:650;}
  .sub{color:#9aa3b2;margin-bottom:26px;}
  label{display:block;font-size:12.5px;color:#9aa3b2;margin:14px 0 5px;text-transform:uppercase;letter-spacing:.04em;}
  input,select{width:100%;background:#1d212b;color:#e6e9ef;border:1px solid #2a2f3a;
    border-radius:8px;padding:9px 11px;font-size:14px;}
  .row{display:flex;gap:12px;} .row>div{flex:1;}
  .hint{color:#6b7180;font-size:12px;margin-top:4px;}
  button{margin-top:24px;background:#2b3a63;color:#cfe0ff;border:1px solid #3a4f86;
    border-radius:9px;padding:11px 18px;font-size:14px;font-weight:600;cursor:pointer;width:100%;}
  button:hover{border-color:#6ea8fe;}
  a{color:#6ea8fe;}
  .err{background:#241419;border:1px solid #f06a6a;border-radius:10px;padding:14px 16px;margin:20px 0;}
  code{background:#1d212b;padding:1px 6px;border-radius:4px;font-family:ui-monospace,Menlo,monospace;}
  details.creds{margin-top:24px;border:1px solid #2a2f3a;border-radius:9px;padding:10px 14px;background:#171a21;}
  details.creds summary{cursor:pointer;color:#9aa3b2;font-size:13px;}
  details.creds[open] summary{color:#e6e9ef;margin-bottom:6px;}
  details.creds button{margin-top:14px;}
  .ok{color:#4cc38a;}
"""


def _opts(values: List[str], selected: Optional[str]) -> str:
    out = []
    for v in values:
        sel = " selected" if v == selected else ""
        out.append('<option value="{0}"{1}>{0}</option>'.format(html.escape(v), sel))
    return "".join(out)


_FORM_TPL = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>culprit</title><style>__STYLE__</style></head><body><div class="wrap">
  <div class="brand">culprit · root-cause analysis</div>
  <h1>Analyze a PR or branch</h1>
  <div class="sub">Pick the base branch, run a fresh RCA, get the visual timeline.</div>
  <form action="/report" method="get">
    <label>Repository path</label>
    <input name="repo" id="repo" value="__REPO__" spellcheck="false">
    <div class="row">
      <div><label>PR number <span class="hint">(needs gh auth)</span></label>
        <input name="pr" placeholder="optional, e.g. 16889"></div>
      <div><label>Head ref <span class="hint">(branch/sha)</span></label>
        <input name="head" placeholder="optional, default current branch"></div>
    </div>
    <label>Base branch</label>
    <select name="base" id="base">__BASE_OPTS__</select>
    <div class="hint"><b>auto</b> analyzes just your latest commit (one change); pick a branch
      to compare your whole branch against it. Default is <code>.culprit.toml</code>/<code>CULPRIT_BASE</code>
      or the repo's default branch.</div>
    <div class="row">
      <div><label>Classification</label>
        <select name="force">
          <option value="">auto-detect</option>
          <option value="bugfix">force bugfix</option>
          <option value="feature">force feature</option>
        </select></div>
      <div><label>Reasoning</label>
        <select name="mode">
          <option value="harness">structured only (no API key)</option>
          <option value="api">Claude API narrative</option>
        </select></div>
    </div>
    <button type="submit">Run analysis &rarr;</button>
  </form>
  <details class="creds"__CREDS_OPEN__>
    <summary>Credentials (optional) &mdash; __CREDS_STATUS__</summary>
    <form action="/config" method="post" autocomplete="off">
      <label>GitHub token <span class="hint">(enables the PR field + private repos; same as <code>gh auth</code>)</span></label>
      <input name="github_token" type="password" placeholder="__GH_PH__" autocomplete="off">
      <label>Anthropic API key <span class="hint">(enables the "Claude API narrative" reasoning)</span></label>
      <input name="anthropic_key" type="password" placeholder="__KEY_PH__" autocomplete="off">
      <button type="submit">Save credentials</button>
      <div class="hint">Stored in this server's memory only &mdash; never written to disk, never in a URL.
        Leave a field blank to keep its current value.</div>
    </form>
  </details>__SAVED__
  <script>
    // Repopulate the base picker when the repo path changes.
    var repoEl=document.getElementById('repo'), baseEl=document.getElementById('base');
    repoEl.addEventListener('change', function(){
      fetch('/api/bases?repo='+encodeURIComponent(repoEl.value))
        .then(function(r){return r.json();})
        .then(function(d){
          var cur=baseEl.value;
          baseEl.innerHTML='<option value="">auto &mdash; latest commit (HEAD~1)</option>'+
            (d.bases||[]).map(function(b){return '<option value="'+b+'"'+(b===(d.default||'')?' selected':'')+'>'+b+'</option>';}).join('');
          if(cur) baseEl.value=cur;
        }).catch(function(){});
    });
  </script>
</div></body></html>"""


def form_page(repo: str, saved: bool = False) -> str:
    bases = candidate_bases(repo)
    cfg = config.repo_base(repo)
    base_opts = ('<option value="">auto &mdash; latest commit (HEAD~1)</option>'
                 + _opts(bases, cfg))
    status, gh_ph, ak_ph = _creds_view()
    saved_html = ('<div class="hint ok" style="margin-top:10px">&check; credentials saved.</div>'
                  if saved else "")
    return (_FORM_TPL
            .replace("__STYLE__", _STYLE)
            .replace("__REPO__", html.escape(repo))
            .replace("__BASE_OPTS__", base_opts)
            .replace("__CREDS_STATUS__", html.escape(status))
            .replace("__GH_PH__", html.escape(gh_ph))
            .replace("__KEY_PH__", html.escape(ak_ph))
            .replace("__CREDS_OPEN__", " open" if saved else "")
            .replace("__SAVED__", saved_html))


def _error_page(msg: str) -> str:
    return ("""<!DOCTYPE html><html><head><meta charset="utf-8"><title>culprit - error</title>
<style>{style}</style></head><body><div class="wrap">
  <div class="brand">culprit</div><h1>Analysis failed</h1>
  <div class="err">{msg}</div><p><a href="/"><- Back</a></p>
</div></body></html>""").format(style=_STYLE, msg=html.escape(msg))


def _back_bar() -> str:
    return ('<div style="max-width:1000px;margin:0 auto;padding:14px 20px 0">'
            '<a href="/" style="color:#6ea8fe;text-decoration:none"><- New analysis</a></div>')


# -- analysis for the report route --------------------------------------------

def run_report(params: Dict[str, List[str]]) -> str:
    def g(k, default=None):
        v = params.get(k, [default])
        return v[0] if v else default

    repo = os.path.abspath(os.path.expanduser(g("repo", ".") or "."))
    pr = g("pr") or None
    pr_int = int(pr) if (pr and str(pr).isdigit()) else None
    head = g("head") or None
    base = g("base") or None       # "" -> None -> latest commit
    force = g("force") or None
    mode = g("mode", "harness")

    result = cli.analyze(repo, pr=pr_int, base=base, head=head, force=force)

    narrative = ""
    if mode == "api":
        try:
            # Prefer a key entered in the UI; otherwise fall back to the environment.
            adapter = reasoning.ClaudeAPIAdapter(api_key=_CREDS["anthropic_key"] or None)
            narrative = adapter.explain(result)
        except Exception as exc:  # missing key / SDK - degrade gracefully
            narrative = "_(API narrative unavailable: {})_".format(exc)

    doc = htmlreport.render(result, narrative)
    return doc.replace('<div class="wrap" id="app">', _back_bar() + '<div class="wrap" id="app">', 1)


# -- server -------------------------------------------------------------------

def make_handler(default_repo: str):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: str, status: int = 200, ctype: str = "text/html"):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            u = urlparse(self.path)
            try:
                if u.path == "/config":
                    length = int(self.headers.get("Content-Length", 0) or 0)
                    body = self.rfile.read(length).decode("utf-8") if length else ""
                    fields = parse_qs(body)
                    gh = (fields.get("github_token", [""])[0] or "").strip()
                    ak = (fields.get("anthropic_key", [""])[0] or "").strip()
                    if gh:
                        _CREDS["github_token"] = gh
                    if ak:
                        _CREDS["anthropic_key"] = ak
                    _apply_creds()
                    self.send_response(303)            # redirect back to the form
                    self.send_header("Location", "/?saved=1")
                    self.end_headers()
                else:
                    self._send(_error_page("Not found: " + u.path), status=404)
            except Exception as exc:
                self._send(_error_page("{}: {}".format(type(exc).__name__, exc)), status=500)

        def do_GET(self):
            u = urlparse(self.path)
            params = parse_qs(u.query)
            try:
                if u.path == "/":
                    self._send(form_page(default_repo, saved="saved" in params))
                elif u.path == "/api/bases":
                    repo = os.path.abspath(os.path.expanduser((params.get("repo", ["."])[0]) or "."))
                    bases = candidate_bases(repo)
                    self._send(json.dumps({"bases": bases, "default": config.repo_base(repo) or ""}),
                               ctype="application/json")
                elif u.path == "/report":
                    self._send(run_report(params))
                elif u.path == "/favicon.ico":
                    self._send("", status=204)
                else:
                    self._send(_error_page("Not found: " + u.path), status=404)
            except Exception as exc:  # never crash the dev server
                self._send(_error_page("{}: {}".format(type(exc).__name__, exc)), status=500)

        def log_message(self, *args):  # quiet
            pass

    return Handler


def run(repo: str = ".", host: str = "127.0.0.1", port: int = 8722, open_browser: bool = True) -> int:
    repo = os.path.abspath(os.path.expanduser(repo))
    httpd = ThreadingHTTPServer((host, port), make_handler(repo))
    url = "http://{}:{}/".format(host, port)
    print("culprit serve -> {}  (repo: {})".format(url, repo))
    print("Press Ctrl+C to stop.")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()
    return 0
