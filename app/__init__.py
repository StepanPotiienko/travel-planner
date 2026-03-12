import os

from dotenv import load_dotenv
from flask import Flask

from app.db import close_db, init_db
from config import config_map

load_dotenv()


def create_app():
    app = Flask(__name__, instance_relative_config=False)

    env = os.environ.get("FLASK_ENV", "development")
    app.config.from_object(config_map.get(env, config_map["development"]))

    app.teardown_appcontext(close_db)
    init_db(app)

    # Deferred to avoid circular imports at module load time
    from app.routes.places import places_bp
    from app.routes.projects import projects_bp
    from app.routes.web import web_bp

    app.register_blueprint(projects_bp)
    app.register_blueprint(places_bp)
    app.register_blueprint(web_bp)

    return app
