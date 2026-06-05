import os
from flask import Flask
from flask_cors import CORS
from models import db
from auth     import auth_bp
from service  import service_bp
from queues    import queue_bp
from counter  import counter_bp
from team     import team_bp
from analytics import analytics_bp
from schedule import schedule_bp
from dotenv import load_dotenv

load_dotenv()


# =============================================================
# APPLICATION FACTORY
# =============================================================
def create_app() -> Flask:
    app = Flask(__name__)

    # --- Database ---
    app.config["SQLALCHEMY_DATABASE_URI"]        = os.getenv("DATABASE_URL")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # --- Brevo ---
    app.config["BREVO_API_KEY"]       = os.getenv("BREVO_API_KEY")
    app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_SENDER")

    # --- Base URL (used for QR join links + invite links) ---
    app.config["BASE_URL"] = os.getenv("BASE_URL", "http://109.199.120.38:5000")

    # --- Extensions ---
    db.init_app(app)

    cors_origins = os.getenv("CORS_ORIGINS", "").split(",")
    CORS(app, supports_credentials=True, origins=cors_origins)

    # --- Blueprints ---
    app.register_blueprint(auth_bp,      url_prefix="/api")
    app.register_blueprint(service_bp,   url_prefix="/api")
    app.register_blueprint(queue_bp,     url_prefix="/api")
    app.register_blueprint(counter_bp,   url_prefix="/api")
    app.register_blueprint(team_bp,      url_prefix="/api")
    app.register_blueprint(analytics_bp, url_prefix="/api")
    app.register_blueprint(schedule_bp,  url_prefix="/api")

    # --- Health check ---
    @app.route("/")
    def index():
        return {
            "status":          "online",
            "message":         "TICKETY API running",
            "db_connected":    True,
            "auth_configured": bool(app.config["BREVO_API_KEY"]),
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
            print("✅ Connected to database.")
        except Exception as e:
            print(f"❌ Database connection failed: {e}")

    print("🚀 TICKETY server starting on http://109.199.120.38:5000 ...")
    app.run(host="0.0.0.0", port=5000, debug=False)