# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report privately via GitHub's [Report a vulnerability](https://github.com/noordeen123/culprit/security/advisories/new)
form, or email **noordeenm936@gmail.com**. Include a description, reproduction
steps, and the affected version. You can expect an initial response within a few
days, and we'll keep you updated as a fix is prepared and released.

## Supported versions

culprit is pre-1.0; only the latest released version on PyPI receives fixes.

## Security model

culprit is a **read-only** analysis tool, which keeps its attack surface small:

- It never modifies the target repository's working tree or the PR/MR. Its only
  writes are the report file you ask for (`--html`) and runs saved under
  `~/culprit/output/`.
- It runs local `git` (diff/blame/log) and, when available, `gh` / the GitHub or
  GitLab REST API. PR-by-number performs a read-only `git fetch` of the PR ref.
- The core engine has no third-party runtime dependencies (standard library +
  `git`). The Claude API reasoning adapter is an optional extra and is only used
  when you explicitly select `--mode api`.

### Things to be aware of

- **`serve` mode** binds to `127.0.0.1` and runs `git` against a local repo path
  you supply. Don't expose it to untrusted networks; treat the repo path as
  trusted input.
- The generated HTML report **embeds diff content and commit metadata** from the
  analyzed repo. Report text is HTML-escaped, but only open reports generated from
  repositories you trust.
- Tokens (`GITHUB_TOKEN` / `GITLAB_TOKEN` / `ANTHROPIC_API_KEY`) are read from the
  environment and never written to the report or saved output.
