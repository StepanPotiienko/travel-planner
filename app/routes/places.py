import sqlite3
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from app.auth import require_auth
from app.db import get_db, sync_project_status
from app.services.nominatim import search_place

places_bp = Blueprint(
    "places", __name__, url_prefix="/api/projects/<int:project_id>/places"
)

# notes are freeform but we don't want people pasting entire travel blogs
MAX_NOTES_LENGTH = 500


def _serialize_place(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "external_id": row["external_id"],
        "title": row["title"],
        "location": row["location"],
        "notes": row["notes"],
        "visited": bool(row["visited"]),
        "created_at": row["created_at"],
    }


def _load_project(db: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()


@places_bp.route("", methods=["POST"])
@require_auth
def add_place(project_id: int):
    db = get_db()

    project = _load_project(db, project_id)
    if project is None:
        return jsonify({"error": "Project not found."}), 404

    body: dict[str, Any] = request.get_json(silent=True) or {}
    name: str = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required."}), 400

    count = db.execute(
        "SELECT COUNT(*) FROM project_places WHERE project_id = ?", (project_id,)
    ).fetchone()[0]
    if count >= current_app.config["MAX_PLACES"]:
        return (
            jsonify(
                {
                    "error": f"Projects are capped at {current_app.config['MAX_PLACES']} places."
                }
            ),
            400,
        )

    # query Nominatim and bias results toward the project's city/country
    result = search_place(name, city=project["city"], country=project["country"])
    if not result:
        return jsonify({"error": f"Could not find '{name}' via Nominatim."}), 422

    # external_id is the Nominatim place_id — use it to prevent duplicates
    existing = db.execute(
        "SELECT id FROM project_places WHERE project_id = ? AND external_id = ?",
        (project_id, result["place_id"]),
    ).fetchone()
    if existing:
        return jsonify({"error": "This place is already in the project."}), 409

    cursor = db.execute(
        """INSERT INTO project_places (project_id, external_id, title, location)
           VALUES (?, ?, ?, ?)""",
        (project_id, result["place_id"], result["name"], result["location"]),
    )
    db.commit()

    place = db.execute(
        "SELECT * FROM project_places WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return jsonify(_serialize_place(place)), 201


@places_bp.route("", methods=["GET"])
@require_auth
def list_places(project_id: int):
    db = get_db()

    if _load_project(db, project_id) is None:
        return jsonify({"error": "Project not found."}), 404

    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(int(request.args.get("per_page", 20)), 100)
    offset = (page - 1) * per_page

    total = db.execute(
        "SELECT COUNT(*) FROM project_places WHERE project_id = ?", (project_id,)
    ).fetchone()[0]

    rows = db.execute(
        """SELECT * FROM project_places WHERE project_id = ?
           ORDER BY created_at ASC LIMIT ? OFFSET ?""",
        (project_id, per_page, offset),
    ).fetchall()

    return jsonify(
        {
            "data": [_serialize_place(r) for r in rows],
            "pagination": {"page": page, "per_page": per_page, "total": total},
        }
    )


@places_bp.route("/<int:place_id>", methods=["GET"])
@require_auth
def get_place(project_id: int, place_id: int):
    db = get_db()

    if _load_project(db, project_id) is None:
        return jsonify({"error": "Project not found."}), 404

    row = db.execute(
        "SELECT * FROM project_places WHERE id = ? AND project_id = ?",
        (place_id, project_id),
    ).fetchone()
    if row is None:
        return jsonify({"error": "Place not found."}), 404

    return jsonify(_serialize_place(row))


@places_bp.route("/<int:place_id>", methods=["PUT"])
@require_auth
def update_place(project_id: int, place_id: int):
    db = get_db()

    if _load_project(db, project_id) is None:
        return jsonify({"error": "Project not found."}), 404

    row = db.execute(
        "SELECT * FROM project_places WHERE id = ? AND project_id = ?",
        (place_id, project_id),
    ).fetchone()
    if row is None:
        return jsonify({"error": "Place not found."}), 404

    body: dict[str, Any] = request.get_json(silent=True) or {}
    notes: str | None = body.get("notes", row["notes"])
    visited: Any = body.get("visited", bool(row["visited"]))

    if not isinstance(visited, bool):
        return jsonify({"error": "visited must be a boolean."}), 400

    if notes is not None and len(notes) > MAX_NOTES_LENGTH:
        return (
            jsonify({"error": f"notes cannot exceed {MAX_NOTES_LENGTH} characters."}),
            400,
        )

    db.execute(
        "UPDATE project_places SET notes = ?, visited = ? WHERE id = ?",
        (notes, int(visited), place_id),
    )
    # keep parent project status in sync whenever visited flag changes
    sync_project_status(db, project_id)
    db.commit()

    updated = db.execute(
        "SELECT * FROM project_places WHERE id = ?", (place_id,)
    ).fetchone()
    return jsonify(_serialize_place(updated))


@places_bp.route("/<int:place_id>", methods=["DELETE"])
@require_auth
def delete_place(project_id: int, place_id: int):
    db = get_db()

    if _load_project(db, project_id) is None:
        return jsonify({"error": "Project not found."}), 404

    row = db.execute(
        "SELECT * FROM project_places WHERE id = ? AND project_id = ?",
        (place_id, project_id),
    ).fetchone()
    if row is None:
        return jsonify({"error": "Place not found."}), 404

    db.execute("DELETE FROM project_places WHERE id = ?", (place_id,))
    sync_project_status(db, project_id)
    db.commit()
    return "", 204
