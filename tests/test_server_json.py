"""server.json must stay valid and consistent with the PyPI ownership marker.

The official MCP registry runs the real schema check at `mcp-publisher publish`
time; these are offline guards so an obvious mistake (a renamed package, a broken
run command, a name that no longer matches the README marker) cannot ship. See
docs/PUBLISHING.md for the publish flow.
"""
import json
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(_ROOT, "server.json"), encoding="utf-8") as _fh:
    SERVER = json.load(_fh)


def test_top_level_required_fields():
    assert SERVER["$schema"].startswith("https://static.modelcontextprotocol.io/")
    # Reverse-DNS GitHub namespace, proven by GitHub OAuth (no DNS step).
    assert SERVER["name"] == "io.github.noordeen123/culprit"
    assert re.fullmatch(r"\d+\.\d+\.\d+", SERVER["version"])
    assert SERVER["repository"]["source"] == "github"
    assert SERVER["packages"], "at least one package entry is required"


def test_name_matches_the_pypi_ownership_marker():
    # The registry verifies ownership by finding `mcp-name: <name>` in the PyPI
    # README (the repo README). If the two drift, publishing silently fails.
    with open(os.path.join(_ROOT, "README.md"), encoding="utf-8") as fh:
        readme = fh.read()
    assert "mcp-name: {}".format(SERVER["name"]) in readme


def test_pypi_package_reconstructs_the_run_command():
    pkg = SERVER["packages"][0]
    assert pkg["registryType"] == "pypi"
    assert pkg["identifier"] == "culprit"
    assert pkg["runtimeHint"] == "uvx"
    assert pkg["transport"]["type"] == "stdio"
    # The package version must match the server version (one PyPI release).
    assert pkg["version"] == SERVER["version"]

    command = [pkg["runtimeHint"]]
    for arg in pkg.get("runtimeArguments", []):
        if arg["type"] == "named":
            command.append(arg["name"])
            if "value" in arg:
                command.append(arg["value"])
        else:  # positional
            command.append(arg["value"])
    assert command == ["uvx", "--from", "culprit[mcp]", "culprit-mcp"]
