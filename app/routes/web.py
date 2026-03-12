from typing import Any

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app.auth import require_login
from app.db import get_db, sync_project_status
from app.services.nominatim import search_place, search_places

web_bp = Blueprint("web", __name__)


@web_bp.route("/login", methods=["GET"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("web.dashboard"))
    return render_template("login.html")


@web_bp.route("/login", methods=["POST"])
def login_post():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    if (
        username == current_app.config["ADMIN_USERNAME"]
        and password == current_app.config["ADMIN_PASSWORD"]
    ):
        session["logged_in"] = True
        return redirect(url_for("web.dashboard"))

    flash("Invalid username or password.", "error")
    return redirect(url_for("web.login"))


@web_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("web.login"))


@web_bp.route("/")
@require_login
def dashboard():
    db = get_db()
    status_filter = request.args.get("status")

    where_clause = "WHERE status = ?" if status_filter else ""
    params = (status_filter,) if status_filter else ()

    projects = db.execute(
        f"SELECT * FROM projects {where_clause} ORDER BY created_at DESC", params
    ).fetchall()

    if not projects:
        return render_template(
            "dashboard.html", projects=[], status_filter=status_filter
        )

    project_ids = [p["id"] for p in projects]
    ph = ",".join("?" * len(project_ids))

    counts: dict[int, dict[str, int]] = {}
    for r in db.execute(
        f"SELECT project_id, COUNT(*) AS total, SUM(visited) AS visited"
        f" FROM project_places WHERE project_id IN ({ph}) GROUP BY project_id",
        project_ids,
    ):
        counts[r["project_id"]] = {"total": r["total"], "visited": r["visited"] or 0}

    previews: dict[int, list[dict[str, Any]]] = {pid: [] for pid in project_ids}
    for row in db.execute(
        f"SELECT id, project_id, title FROM project_places"
        f" WHERE project_id IN ({ph}) AND visited = 0 ORDER BY project_id, created_at",
        project_ids,
    ):
        bucket = previews[row["project_id"]]
        if len(bucket) < 3:
            bucket.append(dict(row))

    enriched: list[dict[str, Any]] = [
        {
            "project": dict(p),
            "total": counts.get(p["id"], {}).get("total", 0),
            "visited": counts.get(p["id"], {}).get("visited", 0),
            "unvisited_places": previews.get(p["id"], []),
        }
        for p in projects
    ]

    return render_template(
        "dashboard.html", projects=enriched, status_filter=status_filter
    )


@web_bp.route("/projects/new", methods=["GET"])
@require_login
def new_project():
    return render_template("project_form.html", project=None)


@web_bp.route("/projects/new", methods=["POST"])
@require_login
def create_project():
    db = get_db()

    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Project name is required.", "error")
        return redirect(url_for("web.new_project"))

    description = (request.form.get("description") or "").strip() or None
    start_date = (request.form.get("start_date") or "").strip() or None
    country = (request.form.get("country") or "").strip() or None
    city = (request.form.get("city") or "").strip() or None

    cursor = db.execute(
        "INSERT INTO projects (name, description, start_date, country, city)"
        " VALUES (?, ?, ?, ?, ?)",
        (name, description, start_date, country, city),
    )
    db.commit()
    flash("Project created successfully.", "success")
    return redirect(url_for("web.project_detail", project_id=cursor.lastrowid))


@web_bp.route("/projects/<int:project_id>", methods=["GET"])
@require_login
def project_detail(project_id: int):
    db = get_db()
    project = db.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        flash("Project not found.", "error")
        return redirect(url_for("web.dashboard"))

    places = db.execute(
        "SELECT * FROM project_places WHERE project_id = ? ORDER BY created_at ASC",
        (project_id,),
    ).fetchall()

    total = len(places)
    visited = sum(1 for p in places if p["visited"])

    return render_template(
        "project.html",
        project=dict(project),
        places=[dict(p) for p in places],
        total=total,
        visited=visited,
        max_places=current_app.config["MAX_PLACES"],
    )


@web_bp.route("/projects/<int:project_id>/edit", methods=["GET"])
@require_login
def edit_project(project_id: int):
    db = get_db()
    project = db.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        flash("Project not found.", "error")
        return redirect(url_for("web.dashboard"))
    return render_template("project_form.html", project=dict(project))


@web_bp.route("/projects/<int:project_id>/edit", methods=["POST"])
@require_login
def update_project(project_id: int):
    db = get_db()
    project = db.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        flash("Project not found.", "error")
        return redirect(url_for("web.dashboard"))

    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Project name is required.", "error")
        return redirect(url_for("web.edit_project", project_id=project_id))

    description = (request.form.get("description") or "").strip() or None
    start_date = (request.form.get("start_date") or "").strip() or None
    country = (request.form.get("country") or "").strip() or None
    city = (request.form.get("city") or "").strip() or None

    db.execute(
        "UPDATE projects SET name = ?, description = ?, start_date = ?,"
        " country = ?, city = ? WHERE id = ?",
        (name, description, start_date, country, city, project_id),
    )
    db.commit()
    flash("Project updated.", "success")
    return redirect(url_for("web.project_detail", project_id=project_id))


@web_bp.route("/projects/<int:project_id>/delete", methods=["POST"])
@require_login
def delete_project(project_id: int):
    db = get_db()
    project = db.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        flash("Project not found.", "error")
        return redirect(url_for("web.dashboard"))

    visited_count = db.execute(
        "SELECT COUNT(*) FROM project_places WHERE project_id = ? AND visited = 1",
        (project_id,),
    ).fetchone()[0]
    if visited_count > 0:
        flash("Cannot delete a project that has visited places.", "error")
        return redirect(url_for("web.project_detail", project_id=project_id))

    db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    db.commit()
    flash("Project deleted.", "success")
    return redirect(url_for("web.dashboard"))


@web_bp.route("/projects/<int:project_id>/places", methods=["POST"])
@require_login
def add_place(project_id: int):
    db = get_db()

    project = db.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        flash("Project not found.", "error")
        return redirect(url_for("web.dashboard"))

    place_name = (request.form.get("name") or "").strip()
    if not place_name:
        flash("Place name is required.", "error")
        return redirect(url_for("web.project_detail", project_id=project_id))

    count = db.execute(
        "SELECT COUNT(*) FROM project_places WHERE project_id = ?", (project_id,)
    ).fetchone()[0]
    if count >= current_app.config["MAX_PLACES"]:
        flash(
            f"A project cannot have more than {current_app.config['MAX_PLACES']} places.",
            "error",
        )
        return redirect(url_for("web.project_detail", project_id=project_id))

    found = search_place(place_name, city=project["city"], country=project["country"])
    if not found:
        flash(f"'{place_name}' could not be found. Try a more specific name.", "error")
        return redirect(url_for("web.project_detail", project_id=project_id))

    existing = db.execute(
        "SELECT id FROM project_places WHERE project_id = ? AND external_id = ?",
        (project_id, found["place_id"]),
    ).fetchone()
    if existing:
        flash("This place is already in the project.", "error")
        return redirect(url_for("web.project_detail", project_id=project_id))

    db.execute(
        """INSERT INTO project_places (project_id, external_id, title, location)
           VALUES (?, ?, ?, ?)""",
        (project_id, found["place_id"], found["name"], found["location"]),
    )
    db.commit()
    flash(f"'{found['name']}' added to the project.", "success")
    return redirect(url_for("web.project_detail", project_id=project_id))


@web_bp.route(
    "/projects/<int:project_id>/places/<int:place_id>/update", methods=["POST"]
)
@require_login
def update_place(project_id: int, place_id: int):
    db = get_db()

    place = db.execute(
        "SELECT * FROM project_places WHERE id = ? AND project_id = ?",
        (place_id, project_id),
    ).fetchone()
    if place is None:
        flash("Place not found.", "error")
        return redirect(url_for("web.project_detail", project_id=project_id))

    notes = request.form.get("notes", place["notes"])
    visited = request.form.get("visited") == "1"

    db.execute(
        "UPDATE project_places SET notes = ?, visited = ? WHERE id = ?",
        (notes, int(visited), place_id),
    )
    sync_project_status(db, project_id)
    db.commit()

    flash("Place updated.", "success")
    next_url = request.form.get("next", "").strip()
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    return redirect(url_for("web.project_detail", project_id=project_id))


@web_bp.route(
    "/projects/<int:project_id>/places/<int:place_id>/delete", methods=["POST"]
)
@require_login
def delete_place(project_id: int, place_id: int):
    db = get_db()

    place = db.execute(
        "SELECT * FROM project_places WHERE id = ? AND project_id = ?",
        (place_id, project_id),
    ).fetchone()
    if place is None:
        flash("Place not found.", "error")
        return redirect(url_for("web.project_detail", project_id=project_id))

    db.execute("DELETE FROM project_places WHERE id = ?", (place_id,))
    sync_project_status(db, project_id)
    db.commit()
    flash(f"'{place['title']}' removed from the project.", "success")
    return redirect(url_for("web.project_detail", project_id=project_id))


@web_bp.route("/projects/<int:project_id>/places/autocomplete")
@require_login
def autocomplete_places(project_id: int):
    db = get_db()
    project = db.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        return jsonify([]), 404

    query = (request.args.get("q") or "").strip()
    if len(query) < 2:
        return jsonify([])

    suggestions = search_places(query, city=project["city"], country=project["country"])
    return jsonify(
        [{"name": s["name"], "location": s["location"]} for s in suggestions]
    )
