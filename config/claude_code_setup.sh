#!/usr/bin/env sh
# Register both Rhino MCP servers with Claude Code. Run from the repo root.
claude mcp add rhino -- uvx rhinomcp@latest
claude mcp add rhino-ai-mods -- uv run --directory "$(pwd)" rhino-ai-mcp
