import os
from flask import Flask
from flask_cors import CORS
from models  import db
from auth    import auth_bp
from tickets import tickets_bp
from services_bp import services_bp
from dotenv  import load_dotenv
from utils.logger import setup_logger, log_request_info, log_response_info, logger

load_dotenv()


# =============================================================
# APPLICATION FACTORY
# Changes vs original:
#   - Registered services_bp at /api  (new)
#   - Added BASE_URL config for QR code URL generation (new)
#   - Updated health check to list all endpoints
# =============================================================
def create_app() -> Flask:
    app = Flask(__name__)

    # --- Database ---
    app.config['SQLALCHEMY_DATABASE_URI']        = os.getenv('DATABASE_URL')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS']  = False

    # --- Email ---
    app.config['BREVO_API_KEY']       = os.getenv('BREVO_API_KEY')
    app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_SENDER')

    # --- QR Code base URL (set in .env as BASE_URL) ---
    # Example: BASE_URL=https://tickety.app
    # The QR encodes: BASE_URL/scan/<service_token>
    app.config['BASE_URL'] = os.getenv('BASE_URL', 'http://localhost:5000')

    # --- Extensions ---
    db.init_app(app)

    # --- CORS Configuration ---
    cors_origins = os.getenv('CORS_ORIGINS', 'http://localhost:3000,http://localhost:5173').split(',')
    CORS(app, origins=cors_origins, supports_credentials=True)

    # --- Blueprints ---
    app.register_blueprint(auth_bp,     url_prefix='/api')
    app.register_blueprint(tickets_bp,  url_prefix='/api')
    app.register_blueprint(services_bp, url_prefix='/api')  # ← NEW

    # --- Request/Response Logging ---
    @app.before_request
    def before_request():
        log_request_info()

    @app.after_request
    def after_request(response):
        return log_response_info(response)

    # --- Health check ---
    @app.route('/')
    def index():
        return {
            'status':  'online',
            'message': 'TICKETY API running',
            'endpoints': {
                'auth': [
                    '/api/register',
                    '/api/login',
                    '/api/verify-email',
                    '/api/resend-otp',
                ],
                'tickets': [
                    'POST   /api/tickets',
                    'GET    /api/tickets?user_id=',
                    'GET    /api/tickets/all  (admin)',
                    'GET    /api/tickets/<id>',
                    'PATCH  /api/tickets/<id>',
                    'DELETE /api/tickets/<id>',
                ],
                'services': [
                    'POST   /api/services            (admin)',
                    'GET    /api/services            (all / active)',
                    'GET    /api/services/resolve?token=',
                    'GET    /api/services/<id>',
                    'PATCH  /api/services/<id>       (admin)',
                    'DELETE /api/services/<id>       (admin)',
                    'POST   /api/services/<id>/regenerate-qr (admin)',
                    'GET    /api/services/<id>/qr.png',
                ],
            },
        }

    return app


# =============================================================
# ENTRY POINT
# =============================================================
if __name__ == '__main__':
    app = create_app()

    with app.app_context():
        try:
            db.engine.connect()
            print('✅ Connected to MySQL database.')
            db.create_all()
            print('✅ All tables created / verified.')
        except Exception as e:
            logger.warning(f'⚠️  Database connection failed: {e}')
            print(f'⚠️  Database connection failed (app will start but DB operations will fail)')
            print(f'   Error: {e}')
            print(f'   → Check your DATABASE_URL in .env')
            print(f'   → Verify network connectivity to Aiven')

    print('🚀 TICKETY server starting on http://localhost:5000 ...')
    app.run(host='0.0.0.0', port=5000, debug=True)
