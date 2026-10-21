# MCP Servers Playground

MCP (Model Context Protocol) servers I'm building with [FastMCP](https://gofastmcp.com) while learning MCP, following the CampusX MCP playlist.

| Folder | What it is | Transport | Storage |
|---|---|---|---|
| [`expense-tracker/`](expense-tracker/) | Add, edit, delete, list and summarize expenses, plus a categories resource | stdio (local, Claude Desktop) | SQLite (`expenses.db`) |
| [`personal-hub/`](personal-hub/) | Notes, tasks, world time, date maths and a safe calculator (11 tools), a `hub://today` resource and a `/health` route | Streamable HTTP (`/mcp`) | SQLite (`hub.db`) |

Tested with **fastmcp 4.1.3** and Python 3.13 on Windows.

## Run locally

Each folder is its own [uv](https://docs.astral.sh/uv/) project:

```powershell
cd expense-tracker   # or personal-hub
uv sync
uv run main.py
```

See each folder's README for Claude Desktop and MCP Inspector setup.

## Data

Database files (`*.db`) are created on first run and are git-ignored, so no personal data is committed.
