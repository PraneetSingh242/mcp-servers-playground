# Expense Tracker MCP server (FastMCP + SQLite) on Windows

Tested 2026-10-21 with **fastmcp 4.1.3** (pulls in mcp 2.3.0), Python 3.13, over real stdio.
All 5 tools + the categories resource worked, including error cases (bad date, unknown category, missing id).

**Which package?** This uses the standalone `fastmcp` package (`from fastmcp import FastMCP`), not the
official `mcp` SDK. The `mcp` SDK 2.x renamed its built-in class to `MCPServer`, which is why old
`from mcp.server.fastmcp import FastMCP` tutorials break. [Certain for the versions above]
The CampusX video code may differ slightly (older fastmcp 2.x). The `@mcp.tool` / `@mcp.resource` /
`mcp.run()` pattern is the same. [Likely]

Files in this folder: `main.py`, `categories.json`, this guide.

---

## 1. Install uv (once)

In PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen the terminal, then check: `uv --version`.
Find its full path (you need it in step 6): `where.exe uv`
Usually `C:\Users\psingh1\.local\bin\uv.exe`. [Likely]

## 2. Create the project

```powershell
cd C:\Users\psingh1
uv init expense-tracker --python 3.13
cd expense-tracker
uv add "fastmcp==4.1.3"
```

The version is pinned on purpose: fastmcp has changed its API between major versions.

## 3. Add the code

- Delete the `main.py` that `uv init` created, and put this folder's `main.py` there instead.
- Put `categories.json` next to it.

Final layout:

```
C:\Users\psingh1\expense-tracker\
  main.py            <- the server
  categories.json    <- allowed categories (edit freely)
  pyproject.toml     <- created by uv, has fastmcp==4.1.3
  .venv\             <- created by uv
  expenses.db        <- created automatically on first run
```

The DB path is built from `Path(__file__)`, so `expenses.db` always lands next to `main.py`,
whatever folder Claude Desktop starts the server from. No hard-coded path in the code.

## 4. What the server exposes

| Tool | What it does |
|---|---|
| `add_expense(date, amount, category, subcategory="", note="")` | Insert one row, returns its id |
| `list_expenses(start_date, end_date, category=None)` | Rows in a date range (inclusive) |
| `summarize(start_date, end_date, category=None)` | Total + count per category, plus grand total |
| `edit_expense(expense_id, ...any field)` | Change only the fields you pass |
| `delete_expense(expense_id)` | Delete one row |

Resource: `expense://categories` returns `categories.json`, so Claude knows the valid categories.
Dates must be `YYYY-MM-DD`. Category is validated against `categories.json` (case-insensitive).

## 5. Test with MCP Inspector (before touching Claude Desktop)

Needs Node.js installed (`node --version`).

```powershell
cd C:\Users\psingh1\expense-tracker
uv run fastmcp dev inspector main.py
```

A browser tab opens. Click **Connect**, then **Tools > List Tools**, pick `add_expense`, fill the
fields, **Run Tool**. Then try `summarize` with this month's dates. Check **Resources** for
`expense://categories`.

Quick sanity check without the Inspector: `uv run main.py` should sit silently waiting
(it is talking stdio). Ctrl+C to stop. If it prints an error instead, fix that first.

## 6. Connect to Claude Desktop

1. Quit Claude fully: tray icon > Quit, and check Task Manager that no Claude process is left.
2. Open `%APPDATA%\Claude\claude_desktop_config.json`.
3. **Do not replace the file.** It also holds app `preferences`. Add an `expense-tracker` entry
   inside `mcpServers` (next to `manim-server`). Example of the result:

```json
{
  "mcpServers": {
    "manim-server": { "...": "leave your existing entry as it is" },
    "expense-tracker": {
      "command": "C:\\Users\\psingh1\\.local\\bin\\uv.exe",
      "args": [
        "run",
        "--project",
        "C:\\Users\\psingh1\\expense-tracker",
        "C:\\Users\\psingh1\\expense-tracker\\main.py"
      ]
    }
  },
  "preferences": { "...": "leave as it is" }
}
```

Use the real `uv.exe` path from `where.exe uv`. Double backslashes are required in JSON.
`--project` makes uv use this project's `.venv` with the pinned fastmcp. (I tested this exact
command from a different working directory and it started fine.) [Certain on Linux, Likely on Windows]

4. Start Claude Desktop. Settings > Developer should show `expense-tracker` as running.
5. Try: "Add 250 rupees for groceries today", then "Summarize my spending this month".

Shortcut alternative: `uv run fastmcp install claude-desktop main.py --name expense-tracker`
writes the config for you, but it uses `uv run --with fastmcp` (unpinned), so I prefer the manual
entry above. [Certain: checked the generated JSON]

## 7. If it does not show up

- Run the exact command from the config in cmd and read the error:
  `C:\Users\psingh1\.local\bin\uv.exe run --project C:\Users\psingh1\expense-tracker C:\Users\psingh1\expense-tracker\main.py`
- Logs: `%APPDATA%\Claude\logs\mcp-server-expense-tracker.log` [Likely file name]
- JSON error (missing comma, single backslash) makes Claude ignore the whole config.
- Edited the config while Claude was running? Quit fully and edit again.

## How the code works (short)

- `FastMCP("ExpenseTracker")` creates the server. Each `@mcp.tool` function becomes a tool;
  FastMCP builds the input schema from the type hints and the docstring becomes its description.
- `get_conn()` opens SQLite, commits on success, rolls back on error, always closes.
  All SQL uses `?` placeholders, so no SQL injection from Claude's inputs.
- Raising `ValueError` in a tool sends a clean error message back to Claude instead of crashing.
- `mcp.run()` defaults to stdio transport, which is what Claude Desktop uses.

UiPath analogy: each tool is like a published process with typed In arguments; Claude is the
orchestrator deciding which one to call and with what arguments.

## Next steps to try

- Add a `credit` table (income) and a `balance` tool.
- Add a prompt with `@mcp.prompt` for a "monthly report".
- Switch to remote: `mcp.run(transport="http", port=8000)` (later CampusX videos cover this).
