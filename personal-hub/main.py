"""Personal Hub: a remote MCP server (FastMCP over HTTP) for notes, tasks and quick utilities.

Run:  uv run python main.py
MCP:  http://localhost:8000/mcp   (health check: http://localhost:8000/health)
"""

import ast
import logging
import operator
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("personal_hub")


def _is_writable_dir(folder: Path) -> bool:
    # SQLite writes a journal file next to the db, so the folder itself must be writable.
    # Probe with a real file: os.access() is unreliable on read-only container mounts.
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write_test"
        probe.write_text("ok")
        probe.unlink()
        return True
    except OSError:
        return False


def _is_usable_db(path: Path) -> bool:
    # The folder must be writable, and so must the db file if it already exists
    # ("attempt to write a readonly database" means the file opened read-only).
    if not _is_writable_dir(path.parent):
        return False
    if path.exists():
        try:
            with open(path, "r+b"):
                pass
        except OSError:
            return False
    return True


def resolve_db_path() -> tuple[Path, bool]:
    """Pick where hub.db lives. Returns (path, is_ephemeral).

    1. HUB_DB_PATH env var, if set (use this to point at a persistent disk).
    2. Next to this script, if hub.db there can be written (normal local run).
    3. The system temp folder. Works on read-only cloud deploys, but the data is
       lost whenever the server restarts or redeploys.
    """
    env_path = os.environ.get("HUB_DB_PATH")
    if env_path:
        path = Path(env_path).expanduser().resolve()
        if not _is_usable_db(path):
            raise RuntimeError(f"HUB_DB_PATH is not writable: {path}")
        return path, False

    local = Path(__file__).resolve().parent / "hub.db"
    if _is_usable_db(local):
        return local, False

    fallback = Path(tempfile.gettempdir()) / "personal_hub" / "hub.db"
    log.warning(
        "%s is read-only, using %s instead. Data there is TEMPORARY and is "
        "lost on restart/redeploy. Set HUB_DB_PATH to a persistent location to keep it.",
        local, fallback,
    )
    _is_writable_dir(fallback.parent)
    return fallback, True


DB_PATH, DB_IS_EPHEMERAL = resolve_db_path()
log.info("Using database at %s", DB_PATH)

mcp = FastMCP("PersonalHub")


@contextmanager
def get_conn():
    """Open a connection, commit on success, roll back on error, always close."""
    if not DB_PATH.exists():
        log.warning("Database not found at %s, creating a new one", DB_PATH)
    elif DB_PATH.stat().st_size == 0:
        log.warning("Database at %s is empty, creating the tables", DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # Runs on every connection so a deleted or empty hub.db is rebuilt
        # instead of failing with "no such table". A no-op when tables exist.
        create_schema(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS notes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title      TEXT NOT NULL,
            content    TEXT NOT NULL DEFAULT '',
            tags       TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title      TEXT NOT NULL,
            due_date   TEXT,
            priority   TEXT NOT NULL DEFAULT 'medium',
            done       INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        """
    )


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def check_date(value: str) -> str:
    # Raises ValueError for anything that is not a real YYYY-MM-DD date.
    return date.fromisoformat(value).isoformat()


def clean_tags(tags: list[str] | None) -> str:
    return ",".join(sorted({t.strip().lower() for t in tags or [] if t.strip()}))


def note_row(row: sqlite3.Row) -> dict:
    note = dict(row)
    note["tags"] = [t for t in note["tags"].split(",") if t]
    return note


def task_row(row: sqlite3.Row) -> dict:
    task = dict(row)
    task["done"] = bool(task["done"])
    return task


# Opening one connection at startup creates hub.db and its tables if needed.
with get_conn():
    pass


# ---------- Notes ----------


@mcp.tool
def add_note(title: str, content: str = "", tags: list[str] | None = None) -> dict:
    """Save a note. tags is an optional list like ["work", "ideas"]."""
    if not title.strip():
        raise ValueError("title cannot be empty")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO notes (title, content, tags, created_at) VALUES (?, ?, ?, ?)",
            (title.strip(), content, clean_tags(tags), now_iso()),
        )
        return {"status": "ok", "id": cur.lastrowid}


@mcp.tool
def search_notes(query: str = "", tag: str | None = None, limit: int = 20) -> list[dict]:
    """Find notes whose title or content contains query (empty query = newest notes)."""
    sql = "SELECT * FROM notes WHERE (title LIKE ? OR content LIKE ?)"
    params: list = [f"%{query}%", f"%{query}%"]
    if tag:
        # Tags are stored comma-separated, so wrap in commas to match whole tags only.
        sql += " AND ',' || tags || ',' LIKE ?"
        params.append(f"%,{tag.strip().lower()},%")
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(limit, 100)))
    with get_conn() as conn:
        return [note_row(row) for row in conn.execute(sql, params)]


@mcp.tool
def get_note(note_id: int) -> dict:
    """Get one note by its id."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    if row is None:
        raise ValueError(f"No note with id {note_id}")
    return note_row(row)


@mcp.tool
def delete_note(note_id: int) -> dict:
    """Delete one note by its id."""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        if cur.rowcount == 0:
            raise ValueError(f"No note with id {note_id}")
    return {"status": "ok", "deleted_id": note_id}


# ---------- Tasks ----------

PRIORITIES = ("high", "medium", "low")


@mcp.tool
def add_task(title: str, due_date: str | None = None, priority: str = "medium") -> dict:
    """Add a to-do. due_date is optional YYYY-MM-DD; priority is high, medium or low."""
    if not title.strip():
        raise ValueError("title cannot be empty")
    priority = priority.strip().lower()
    if priority not in PRIORITIES:
        raise ValueError(f"priority must be one of: {', '.join(PRIORITIES)}")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (title, due_date, priority, created_at) VALUES (?, ?, ?, ?)",
            (title.strip(), check_date(due_date) if due_date else None, priority, now_iso()),
        )
        return {"status": "ok", "id": cur.lastrowid}


@mcp.tool
def list_tasks(status: str = "open") -> list[dict]:
    """List tasks. status is open, done, overdue or all. Sorted by due date, then priority."""
    status = status.strip().lower()
    where = {
        "open": "done = 0",
        "done": "done = 1",
        "overdue": "done = 0 AND due_date IS NOT NULL AND due_date < ?",
        "all": "1 = 1",
    }.get(status)
    if where is None:
        raise ValueError("status must be one of: open, done, overdue, all")
    params = [date.today().isoformat()] if status == "overdue" else []
    sql = (
        f"SELECT * FROM tasks WHERE {where} ORDER BY due_date IS NULL, due_date, "
        "CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, id"
    )
    with get_conn() as conn:
        return [task_row(row) for row in conn.execute(sql, params)]


@mcp.tool
def complete_task(task_id: int) -> dict:
    """Mark a task as done."""
    with get_conn() as conn:
        cur = conn.execute("UPDATE tasks SET done = 1 WHERE id = ?", (task_id,))
        if cur.rowcount == 0:
            raise ValueError(f"No task with id {task_id}")
    return {"status": "ok", "completed_id": task_id}


@mcp.tool
def delete_task(task_id: int) -> dict:
    """Delete a task by its id."""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        if cur.rowcount == 0:
            raise ValueError(f"No task with id {task_id}")
    return {"status": "ok", "deleted_id": task_id}


# ---------- Utilities ----------


@mcp.tool
def world_time(timezones: list[str] | None = None) -> dict:
    """Current time in IANA timezones, e.g. ["Asia/Kolkata", "America/New_York"]."""
    result = {}
    for tz in timezones or ["Asia/Kolkata", "UTC", "America/New_York", "Europe/London"]:
        try:
            result[tz] = datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M (%a)")
        except (ZoneInfoNotFoundError, ValueError):
            result[tz] = "unknown timezone"
    return result


@mcp.tool
def days_between(start_date: str, end_date: str | None = None) -> dict:
    """Days from start_date to end_date (YYYY-MM-DD; end defaults to today)."""
    start = date.fromisoformat(check_date(start_date))
    end = date.fromisoformat(check_date(end_date)) if end_date else date.today()
    days = (end - start).days
    return {"start": start.isoformat(), "end": end.isoformat(), "days": days, "weeks": round(days / 7, 1)}


# Only plain arithmetic is allowed, so the calculator can never run arbitrary code.
_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        if isinstance(node.op, ast.Pow) and abs(_eval(node.right)) > 100:
            raise ValueError("exponent too large")
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("only numbers and + - * / // % ** ( ) are allowed")


@mcp.tool
def calculate(expression: str) -> float:
    """Evaluate an arithmetic expression, e.g. "(1200 * 12) * 0.18"."""
    return _eval(ast.parse(expression, mode="eval").body)


# ---------- Resources and health check ----------


@mcp.resource("hub://today")
def today_overview() -> str:
    """Open tasks due today or earlier, plus counts."""
    overdue = list_tasks("overdue")
    today = date.today().isoformat()
    with get_conn() as conn:
        due_today = [task_row(r) for r in conn.execute(
            "SELECT * FROM tasks WHERE done = 0 AND due_date = ?", (today,)
        )]
        notes = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        open_tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE done = 0").fetchone()[0]
    lines = [f"Today: {today}", f"Open tasks: {open_tasks}  |  Notes: {notes}"]
    if DB_IS_EPHEMERAL:
        lines.append("WARNING: storage is temporary; data is lost when the server restarts.")
    lines += [f"OVERDUE: {t['title']} (due {t['due_date']})" for t in overdue]
    lines += [f"DUE TODAY: {t['title']}" for t in due_today]
    return "\n".join(lines)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> PlainTextResponse:
    # Something a browser can open to confirm the server is up (/mcp only talks MCP).
    storage = "TEMPORARY (lost on restart)" if DB_IS_EPHEMERAL else "persistent"
    return PlainTextResponse(
        "OK - PersonalHub MCP server is running. Connect clients to /mcp\n"
        f"Database: {DB_PATH} ({storage})"
    )


if __name__ == "__main__":
    # host="0.0.0.0" lets other machines reach it; use "127.0.0.1" for local only.
    mcp.run(transport="http", host="0.0.0.0", port=8000)
