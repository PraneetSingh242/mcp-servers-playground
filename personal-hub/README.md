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

## Where the data is stored

The server picks the database location at startup (see `resolve_db_path()` in `main.py`):

1. `HUB_DB_PATH` environment variable, if set. Use this to point at a persistent disk.
2. `hub.db` next to `main.py`, if it can be written (normal local run).
3. Otherwise the system temp folder (`/tmp/personal_hub/hub.db` on Linux). This keeps a
   read-only cloud deploy working instead of failing with "attempt to write a readonly
   database", but **that data is temporary**: it is lost on every restart or redeploy.

`GET /health` and the `hub://today` resource show which location is in use and whether it is temporary.

For data that survives redeploys on a cloud host, use a hosted database (for example Turso/libSQL
or Supabase Postgres, both have free tiers) instead of a local SQLite file.
