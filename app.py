import os
from flask import Flask
from flask_cors import CORS
from models import db
from auth import auth_bp
from dotenv import load_dotenv

load_dotenv()


# =============================================================
# APPLICATION FACTORY
# Responsibilities:
#   - Bootstrap and configure the Flask application
#   - Register all blueprints and extensions
# =============================================================
def create_app() -> Flask:
    app = Flask(__name__)

    # --- MySQL Database Configuration ---
    app.config["SQLALCHEMY_DATABASE_URI"]  = os.getenv("DATABASE_URL")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # --- Brevo Email Configuration ---
    app.config["BREVO_API_KEY"]       = os.getenv("BREVO_API_KEY")
    app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_SENDER")

    # --- Initialize Extensions ---
    db.init_app(app)
    CORS(app, supports_credentials=True)

    # --- Register Blueprints ---
    app.register_blueprint(auth_bp, url_prefix="/api")

    # --- Health Check Route ---
    @app.route("/")
    def index():
        return {
            "status":           "online",
            "message":          "QLINE Auth API running locally (MySQL)",
            "db_connected":     True,
            "auth_configured":  bool(app.config["BREVO_API_KEY"]),
        }

    return app


# =============================================================
# ENTRY POINT
# =============================================================
if __name__ == "__main__":
    app = create_app()

    # Verify DB connection on startup
    with app.app_context():
        try:
            db.engine.connect()
            print("✅ Connected to MySQL database.")
        except Exception as e:
            print(f"❌ Database connection failed: {e}")

    print("🚀 QLINE server starting on http://localhost:5000 ...")
    app.run(host="192.168.1.151", port=5000, debug=True)