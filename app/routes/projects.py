import sqlite3
from typing import Any, cast

from flask import Blueprint, current_app, jsonify, request

from app.auth import require_auth
from app.db import get_db
from app.services.nominatim import search_place

projects_bp = Blueprint("projects", __name__, url_prefix="/api/projects")


def _serialize_project(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "start_date": row["start_date"],
        "country": row["country"],
        "city": row["city"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


def _resolve_and_insert_place(
    db: sqlite3.Connection,
    project_id: int,
    name: str,
    city: str | None = None,
    country: str | None = None,
) -> tuple[dict[str, Any] | None, str | None, int | None]:
    place = search_place(name, city=city, country=country)
    if not place:
        return None, f"Could not find '{name}' via Nominatim.", 422

    # deduplicate by Nominatim place_id
    existing = db.execute(
        "SELECT id FROM project_places WHERE project_id = ? AND external_id = ?",
        (project_id, place["place_id"]),
    ).fetchone()
    if existing:
        return None, f"'{name}' is already in this project.", 409

    count = db.execute(
        "SELECT COUNT(*) FROM project_places WHERE project_id = ?",
        (project_id,),
    ).fetchone()[0]
    if count >= current_app.config["MAX_PLACES"]:
        return (
            None,
            f"Projects are capped at {current_app.config['MAX_PLACES']} places.",
            400,
        )

    db.execute(
        """INSERT INTO project_places (project_id, external_id, title, location)
           VALUES (?, ?, ?, ?)""",
        (project_id, place["place_id"], place["name"], place["location"]),
    )
    return place, None, None


@projects_bp.route("", methods=["POST"])
@require_auth
def create_project():
    body: dict[str, Any] = request.get_json(silent=True) or {}

    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required."}), 400

    description = (body.get("description") or "").strip() or None
    start_date = (body.get("start_date") or "").strip() or None
    country = (body.get("country") or "").strip() or None
    city = (body.get("city") or "").strip() or None
    places_raw: list[Any] = body.get("places") or []

    if not isinstance(places_raw, list):  # type: ignore
        return jsonify({"error": "places must be an array."}), 400

    if len(places_raw) > current_app.config["MAX_PLACES"]:
        return (
            jsonify(
                {
                    "error": f"Projects are capped at {current_app.config['MAX_PLACES']} places."
                }
            ),
            400,
        )

    db = get_db()

    cursor = db.execute(
        "INSERT INTO projects (name, description, start_date, country, city)"
        " VALUES (?, ?, ?, ?, ?)",
        (name, description, start_date, country, city),
    )
    project_id: int = cursor.lastrowid or 0

    errors: list[str] = []
    for item in places_raw:
        if not isinstance(item, dict):
            errors.append("Each place must have a name.")
            continue
        place_name: str = (cast(dict[str, Any], item).get("name") or "").strip()
        if not place_name:
            errors.append("Each place must have a name.")
            continue
        _, err, _ = _resolve_and_insert_place(
            db, project_id, place_name, city=city, country=country
        )
        if err:
            errors.append(err)

    # roll back the whole project if any place lookup failed
    if errors:
        db.rollback()
        return (
            jsonify({"error": "Failed to add one or more places.", "details": errors}),
            422,
        )

    db.commit()

    project = db.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    return jsonify(_serialize_project(project)), 201


@projects_bp.route("", methods=["GET"])
@require_auth
def list_projects():
    db = get_db()

    status_filter = request.args.get("status")
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(int(request.args.get("per_page", 10)), 100)
    offset = (page - 1) * per_page

    where_clause = "WHERE status = ?" if status_filter else ""
    params_count = (status_filter,) if status_filter else ()
    params_select = (
        (status_filter, per_page, offset) if status_filter else (per_page, offset)
    )

    total = db.execute(
        f"SELECT COUNT(*) FROM projects {where_clause}", params_count
    ).fetchone()[0]

    rows = db.execute(
        f"SELECT * FROM projects {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params_select,
    ).fetchall()

    return jsonify(
        {
            "data": [_serialize_project(r) for r in rows],
            "pagination": {"page": page, "per_page": per_page, "total": total},
        }
    )


@projects_bp.route("/<int:project_id>", methods=["GET"])
@require_auth
def get_project(project_id: int):
    db = get_db()
    row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        return jsonify({"error": "Project not found."}), 404
    return jsonify(_serialize_project(row))


@projects_bp.route("/<int:project_id>", methods=["PUT"])
@require_auth
def update_project(project_id: int):
    db = get_db()
    row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        return jsonify({"error": "Project not found."}), 404

    body: dict[str, Any] = request.get_json(silent=True) or {}
    name = (body.get("name") or row["name"]).strip()
    if not name:
        return jsonify({"error": "name cannot be empty."}), 400

    description = body.get("description", row["description"])
    start_date = body.get("start_date", row["start_date"])
    country = body.get("country", row["country"])
    city = body.get("city", row["city"])

    db.execute(
        "UPDATE projects SET name = ?, description = ?, start_date = ?,"
        " country = ?, city = ? WHERE id = ?",
        (name, description, start_date, country, city, project_id),
    )
    db.commit()

    updated = db.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    return jsonify(_serialize_project(updated))


@projects_bp.route("/<int:project_id>", methods=["DELETE"])
@require_auth
def delete_project(project_id: int):
    db = get_db()
    row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        return jsonify({"error": "Project not found."}), 404

    # don't allow deleting a project that has real travel history in it
    visited_count = db.execute(
        "SELECT COUNT(*) FROM project_places WHERE project_id = ? AND visited = 1",
        (project_id,),
    ).fetchone()[0]
    if visited_count > 0:
        return (
            jsonify({"error": "Cannot delete a project that has visited places."}),
            409,
        )

    db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    db.commit()
    return "", 204
