import os
from flask import Flask
from flask_cors import CORS
from models import db
from auth          import auth_bp
from service       import service_bp
from queues        import queue_bp
from counter       import counter_bp
from team          import team_bp
from analytics     import analytics_bp
from schedule      import schedule_bp
from profile       import profile_bp
from notifications import notifications_bp
from swap          import swap_bp
from scheduler     import init_scheduler
from dotenv import load_dotenv

load_dotenv()


# =============================================================
# APPLICATION FACTORY
# OOP Principle: Factory Pattern, Single Responsibility
# =============================================================
def create_app() -> Flask:
    app = Flask(__name__)

    # --- MySQL ---
    app.config["SQLALCHEMY_DATABASE_URI"]        = os.getenv("DATABASE_URL")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # --- Brevo ---
    app.config["BREVO_API_KEY"]       = os.getenv("BREVO_API_KEY")
    app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_SENDER")

    # --- Base URL ---
    # LOCAL DEV:  set BASE_URL=http://localhost:5173 in your .env
    # PRODUCTION: set BASE_URL=https://tickety.app   in your .env
    # Fallback ensures invite + QR links work out-of-the-box locally
    # without needing to edit any Python file.
    app.config["BASE_URL"] = os.getenv("BASE_URL", "http://localhost:5173")

    # --- Extensions ---
    db.init_app(app)

    CORS(app, supports_credentials=True, origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "*",   # restrict in production
    ])

    # --- Blueprints ---
    app.register_blueprint(auth_bp,          url_prefix="/api")
    app.register_blueprint(service_bp,       url_prefix="/api")
    app.register_blueprint(queue_bp,         url_prefix="/api")
    app.register_blueprint(counter_bp,       url_prefix="/api")
    app.register_blueprint(team_bp,          url_prefix="/api")
    app.register_blueprint(analytics_bp,     url_prefix="/api")
    app.register_blueprint(schedule_bp,      url_prefix="/api")
    app.register_blueprint(profile_bp,       url_prefix="/api")
    app.register_blueprint(notifications_bp, url_prefix="/api")
    app.register_blueprint(swap_bp,          url_prefix="/api")   # merged from mobile backend

    # --- Background scheduler (carry-over requeue) ---
    # Guard against Werkzeug reloader spawning a second scheduler process
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        init_scheduler(app)

    # --- Health check ---
    @app.route("/")
    def index():
        return {
            "status":          "online",
            "message":         "TICKETY API running",
            "db_connected":    True,
            "auth_configured": bool(app.config["BREVO_API_KEY"]),
            "base_url":        app.config["BASE_URL"],
        }

    return app


# =============================================================
# ENTRY POINT
# =============================================================
if __name__ == "__main__":
    app = create_app()

    with app.app_context():
        try:
            db.engine.connect()
            print("✅ Connected to MySQL database.")
        except Exception as e:
            print(f"❌ Database connection failed: {e}")

    print(f"🚀 TICKETY server starting on http://localhost:5000 ...")
    print(f"🔗 BASE_URL = {os.getenv('BASE_URL', 'http://localhost:5173')}")
    app.run(host="0.0.0.0", port=5000, debug=True)