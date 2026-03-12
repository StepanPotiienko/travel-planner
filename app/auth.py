from functools import wraps
from typing import Any, Callable

from flask import current_app, jsonify, redirect, request, session, url_for


def require_auth(f: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        auth = request.authorization
        if (
            not auth
            or auth.username != current_app.config["ADMIN_USERNAME"]
            or auth.password != current_app.config["ADMIN_PASSWORD"]
        ):
            return (
                jsonify({"error": "Unauthorized"}),
                401,
                {"WWW-Authenticate": 'Basic realm="TravelPlanner API"'},
            )
        return f(*args, **kwargs)

    return decorated


def require_login(f: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        if not session.get("logged_in"):
            return redirect(url_for("web.login"))
        return f(*args, **kwargs)

    return decorated
