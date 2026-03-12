import sqlite3
from contextlib import suppress

from flask import Flask, current_app, g


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_error: BaseException | None = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app: Flask) -> None:
    with app.app_context():
        db = get_db()
        with app.open_resource("schema.sql") as f:
            db.executescript(f.read().decode("utf-8"))
        # Migrate: add columns that may not exist in older databases.
        for col in ("country", "city"):
            with suppress(sqlite3.OperationalError):
                db.execute(f"ALTER TABLE projects ADD COLUMN {col} TEXT")
        with suppress(sqlite3.OperationalError):
            db.execute(
                "ALTER TABLE project_places RENAME COLUMN artist_display TO location"
            )
        db.commit()


def sync_project_status(db: sqlite3.Connection, project_id: int) -> None:
    total = db.execute(
        "SELECT COUNT(*) FROM project_places WHERE project_id = ?", (project_id,)
    ).fetchone()[0]

    if total == 0:
        return

    unvisited = db.execute(
        "SELECT COUNT(*) FROM project_places WHERE project_id = ? AND visited = 0",
        (project_id,),
    ).fetchone()[0]

    new_status = "completed" if unvisited == 0 else "active"
    db.execute("UPDATE projects SET status = ? WHERE id = ?", (new_status, project_id))
