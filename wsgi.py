from app import create_app

# =============================================================
# WSGI ENTRY POINT
# Used by Gunicorn in production:
#   gunicorn wsgi:application
# =============================================================
application = create_app()