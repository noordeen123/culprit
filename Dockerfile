# Minimal image for the culprit MCP server, used by directory listings (e.g. Glama)
# to start the server and run an MCP introspection check. This is the same stdio
# server you get from `uvx --from "culprit[mcp]" culprit-mcp`.
FROM python:3.12-slim

# culprit shells out to git (blame / log) for its analysis.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# The published package plus its MCP extra (mcp>=1.0).
RUN pip install --no-cache-dir "culprit[mcp]"

# stdio MCP server; the client speaks MCP over stdin/stdout.
ENTRYPOINT ["culprit-mcp"]
