# Publishing culprit's MCP server to the registries

culprit is on PyPI and installable as a Claude Code plugin. This is the checklist
for listing the MCP server in the discovery registries so agents and users can find
it. The official MCP registry is the hub: PulseMCP and most directories crawl it, so
do the registry first and the rest are downstream.

## Prerequisites

- The `mcp-publisher` CLI: https://github.com/modelcontextprotocol/registry/releases
  (or `brew install mcp-publisher` where available).
- A GitHub account that owns `github.com/noordeen123` (the `io.github.noordeen123/*`
  namespace is proven by GitHub OAuth, so no DNS or domain step is needed).
- Push access to PyPI for the `culprit` package.

## One-time-per-release flow

The registry proves you own the package by fetching `pypi.org/pypi/culprit/json` and
checking the README for the marker `mcp-name: io.github.noordeen123/culprit`. That
marker lives in `README.md` (an HTML comment near the top) and only counts once it is
on PyPI, so the registry version must be a release that carries it.

1. **Cut a release that carries the marker.** The marker is already in `README.md`, so
   any release from `main` after it landed will do. Tag and publish as usual:

   ```bash
   git tag vX.Y.Z && git push origin vX.Y.Z
   # build + upload to PyPI (setuptools-scm derives the version from the tag)
   ```

   Confirm the marker is live: it must appear in `info.description` at
   `https://pypi.org/pypi/culprit/json`.

2. **Point `server.json` at that release.** Set both `version` and
   `packages[0].version` in `server.json` to `X.Y.Z` (must match a real PyPI release).

3. **Publish to the official registry.**

   ```bash
   mcp-publisher login github        # opens GitHub OAuth for the io.github.* namespace
   mcp-publisher publish             # validates server.json + the PyPI marker, then lists
   ```

   Verify: `https://registry.modelcontextprotocol.io/v0/servers?search=culprit`.

## Downstream directories (after the registry lists it)

- **PulseMCP** crawls the official registry. Once culprit appears there, claim the
  listing at https://www.pulsemcp.com/submit.
- **awesome-mcp-servers** (punkpeye): a one-line PR adds culprit to the list. See the
  open PR linked from the repo, or add the line yourself following that repo's
  CONTRIBUTING format.

## Notes

- Re-run steps 2 and 3 on every release you want reflected in the registry. The
  registry keeps version history, so publishing a newer `server.json` supersedes the
  old one without removing it.
- `server.json` is validated in CI by `tests/test_server_json.py` (shape, and that its
  name matches the README marker), so a typo cannot ship.
