"""Expense Tracker MCP server (FastMCP + SQLite)."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from fastmcp import FastMCP

# Files live next to this script, so the path works no matter which folder
# Claude Desktop starts the server from.
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "expenses.db"
CATEGORIES_PATH = BASE_DIR / "categories.json"

mcp = FastMCP("ExpenseTracker")


@contextmanager
def get_conn():
    """Open a connection, commit on success, roll back on error, always close."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date        TEXT NOT NULL,
                amount      REAL NOT NULL CHECK (amount > 0),
                category    TEXT NOT NULL,
                subcategory TEXT DEFAULT '',
                note        TEXT DEFAULT ''
            )
            """
        )


def load_categories() -> dict:
    return json.loads(CATEGORIES_PATH.read_text(encoding="utf-8"))


def check_date(value: str) -> str:
    # Raises ValueError for anything that is not a real YYYY-MM-DD date.
    return date.fromisoformat(value).isoformat()


def check_category(category: str) -> str:
    category = category.strip().lower()
    allowed = load_categories()
    if category not in allowed:
        raise ValueError(
            f"Unknown category '{category}'. Allowed: {', '.join(allowed)}"
        )
    return category


init_db()


@mcp.tool
def add_expense(
    date: str,
    amount: float,
    category: str,
    subcategory: str = "",
    note: str = "",
) -> dict:
    """Add a new expense. date is YYYY-MM-DD, amount is in rupees."""
    if amount <= 0:
        raise ValueError("amount must be greater than 0")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO expenses (date, amount, category, subcategory, note) "
            "VALUES (?, ?, ?, ?, ?)",
            (check_date(date), amount, check_category(category), subcategory, note),
        )
        return {"status": "ok", "id": cur.lastrowid}


@mcp.tool
def list_expenses(
    start_date: str, end_date: str, category: str | None = None
) -> list[dict]:
    """List expenses between start_date and end_date (inclusive, YYYY-MM-DD)."""
    sql = "SELECT * FROM expenses WHERE date BETWEEN ? AND ?"
    params: list = [check_date(start_date), check_date(end_date)]
    if category:
        sql += " AND category = ?"
        params.append(check_category(category))
    sql += " ORDER BY date, id"
    with get_conn() as conn:
        return [dict(row) for row in conn.execute(sql, params)]


@mcp.tool
def summarize(
    start_date: str, end_date: str, category: str | None = None
) -> dict:
    """Total spend per category between start_date and end_date (inclusive)."""
    sql = (
        "SELECT category, ROUND(SUM(amount), 2) AS total, COUNT(*) AS count "
        "FROM expenses WHERE date BETWEEN ? AND ?"
    )
    params: list = [check_date(start_date), check_date(end_date)]
    if category:
        sql += " AND category = ?"
        params.append(check_category(category))
    sql += " GROUP BY category ORDER BY total DESC"
    with get_conn() as conn:
        rows = [dict(row) for row in conn.execute(sql, params)]
    return {
        "by_category": rows,
        "grand_total": round(sum(r["total"] for r in rows), 2),
    }


@mcp.tool
def edit_expense(
    expense_id: int,
    date: str | None = None,
    amount: float | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    note: str | None = None,
) -> dict:
    """Update an expense. Only the fields you pass are changed."""
    updates: dict = {}
    if date is not None:
        updates["date"] = check_date(date)
    if amount is not None:
        if amount <= 0:
            raise ValueError("amount must be greater than 0")
        updates["amount"] = amount
    if category is not None:
        updates["category"] = check_category(category)
    if subcategory is not None:
        updates["subcategory"] = subcategory
    if note is not None:
        updates["note"] = note
    if not updates:
        raise ValueError("Nothing to update: pass at least one field")

    # Column names come from the fixed keys above, never from user input.
    set_clause = ", ".join(f"{col} = ?" for col in updates)
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE expenses SET {set_clause} WHERE id = ?",
            [*updates.values(), expense_id],
        )
        if cur.rowcount == 0:
            raise ValueError(f"No expense with id {expense_id}")
    return {"status": "ok", "id": expense_id, "updated": list(updates)}


@mcp.tool
def delete_expense(expense_id: int) -> dict:
    """Delete one expense by its id."""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        if cur.rowcount == 0:
            raise ValueError(f"No expense with id {expense_id}")
    return {"status": "ok", "deleted_id": expense_id}


@mcp.resource("expense://categories", mime_type="application/json")
def categories() -> str:
    """Allowed categories and their subcategories."""
    return CATEGORIES_PATH.read_text(encoding="utf-8")


if __name__ == "__main__":
    mcp.run()
