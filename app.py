import os
from flask import Flask
from flask_cors import CORS
from models import db
from auth    import auth_bp
from tickets import tickets_bp
from dotenv  import load_dotenv

load_dotenv()


# =============================================================
# APPLICATION FACTORY
# Responsibilities:
#   - Bootstrap and configure the Flask application
#   - Register all blueprints and extensions
# Changes vs original:
#   - Registered tickets_bp at /api so all ticket routes
#     are available under /api/tickets
# =============================================================
def create_app() -> Flask:
    app = Flask(__name__)

    # --- MySQL Database Configuration ---
    app.config["SQLALCHEMY_DATABASE_URI"]       = os.getenv("DATABASE_URL")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # --- Brevo Email Configuration ---
    app.config["BREVO_API_KEY"]       = os.getenv("BREVO_API_KEY")
    app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_SENDER")

    # --- Initialize Extensions ---
    db.init_app(app)
    CORS(app, supports_credentials=True)

    # --- Register Blueprints ---
    app.register_blueprint(auth_bp,    url_prefix="/api")
    app.register_blueprint(tickets_bp, url_prefix="/api")   # ← NEW

    # --- Health Check Route ---
    @app.route("/")
    def index():
        return {
            "status":          "online",
            "message":         "TICKETY API running",
            "db_connected":    True,
            "auth_configured": bool(app.config["BREVO_API_KEY"]),
            "endpoints": {
                "auth":    ["/api/register", "/api/login",
                            "/api/verify-email", "/api/resend-otp"],
                "tickets": ["/api/tickets (GET, POST)",
                            "/api/tickets/<id> (GET, PATCH, DELETE)"],
            },
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
            # Create all tables (including the new 'tickets' table)
            db.create_all()
            print("✅ All tables created / verified.")
        except Exception as e:
            print(f"❌ Database connection failed: {e}")

    print("🚀 TICKETY server starting on http://localhost:5000 ...")
    app.run(host="0.0.0.0", port=5000, debug=True)
