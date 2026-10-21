# PersonalHub (remote MCP server)

FastMCP server over Streamable HTTP with SQLite storage (`hub.db`, created on first run, git-ignored).

**Tools (11):** `add_note`, `search_notes`, `get_note`, `delete_note`, `add_task`, `list_tasks`, `complete_task`, `delete_task`, `world_time`, `days_between`, `calculate`
**Resource:** `hub://today` (today's overview)
**Route:** `GET /health`

## Run

```powershell
uv sync
uv run main.py
```

Server URL: http://localhost:8000/mcp

## Connect

- MCP Inspector: `npx @modelcontextprotocol/inspector`, transport "Streamable HTTP", URL http://localhost:8000/mcp
- Claude Desktop, via mcp-remote:

```json
"personal-hub": {
  "command": "npx",
  "args": ["mcp-remote", "http://localhost:8000/mcp"]
}
```
