from flask import Blueprint, request, jsonify
from repositories.user_repository import UserRepository
from repositories.otp_repository import OTPRepository
from services.otp_service import OTPService
from utils.validator import Validator
from utils.password_service import PasswordService

auth_bp = Blueprint("auth", __name__)


# =============================================================
# AUTH CONTROLLER
# Responsibilities:
#   - Handle HTTP request/response for all auth routes
#   - Resolve role automatically from X-App-Source header
#   - Enforce source-based access control on login
#   - Orchestrate collaboration between services & repositories
# OOP Principle: Single Responsibility, Dependency Injection
#
# NOTE: Dependencies are instantiated inside each route method
# (lazy initialization) so they are created inside an active
# Flask application context — required for SQLAlchemy to work
# correctly under Gunicorn workers.
# =============================================================
class AuthController:

    # Role constants
    ROLE_CLIENT = 'client'
    ROLE_ADMIN  = 'admin'

    # Source header constants
    SOURCE_MOBILE = 'mobile'
    SOURCE_WEB    = 'web'

    def _get_deps(self):
        """
        Lazily instantiate dependencies inside the request context.
        This ensures SQLAlchemy has an active app context when
        repositories are created — critical for Gunicorn workers.
        """
        return (
            UserRepository(),
            OTPRepository(),
            OTPService(),
            Validator(),
            PasswordService(),
        )

    # ----------------------------------------------------------
    # PRIVATE: Resolve role from request source header
    # ----------------------------------------------------------
    def _resolve_role(self) -> str:
        source = request.headers.get('X-App-Source', self.SOURCE_MOBILE).lower()
        return self.ROLE_ADMIN if source == self.SOURCE_WEB else self.ROLE_CLIENT

    # ----------------------------------------------------------
    # PRIVATE: Validate login source matches user role
    # ----------------------------------------------------------
    def _is_authorized_source(self, user) -> bool:
        source = request.headers.get('X-App-Source', self.SOURCE_MOBILE).lower()
        if source == self.SOURCE_MOBILE and not user.is_client():
            return False
        if source == self.SOURCE_WEB and not user.is_admin():
            return False
        return True

    # ----------------------------------------------------------
    # REGISTER
    # ----------------------------------------------------------
    def register(self):
        user_repo, otp_repo, otp_service, validator, password_service = self._get_deps()

        data     = request.get_json()
        username = data.get("username", "").strip()
        email    = data.get("email", "").lower().strip()
        password = data.get("password", "")

        error = validator.validate_registration(username, email, password)
        if error:
            return jsonify({"success": False, "message": error}), 400

        if user_repo.find_by_email(email):
            return jsonify({"success": False, "message": "Email already registered"}), 400
        if user_repo.find_by_username(username):
            return jsonify({"success": False, "message": "Username already taken"}), 400

        try:
            role      = self._resolve_role()
            hashed_pw = password_service.hash(password)

            user_repo.create(username, email, hashed_pw, role)
            user_repo.flush()

            otp_code = otp_service.generate()
            otp_repo.upsert(email, otp_code)

            sent = otp_service.send(email, username, otp_code)
            if not sent:
                raise Exception("Failed to send verification email")

            user_repo.save()
            return jsonify({
                "success": True,
                "message": "Verification code sent to your email",
            }), 201

        except Exception as e:
            user_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # VERIFY EMAIL
    # ----------------------------------------------------------
    def verify_email(self):
        user_repo, otp_repo, _, _, _ = self._get_deps()

        data      = request.get_json()
        email     = data.get("email", "").lower().strip()
        user_code = data.get("code", "").strip()

        record = otp_repo.find_by_email_and_code(email, user_code)
        if not record:
            return jsonify({"success": False, "message": "Invalid verification code"}), 400

        if record.is_expired():
            return jsonify({"success": False, "message": "Code has expired"}), 400

        user = user_repo.find_by_email(email)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        user.mark_verified()
        otp_repo.delete(record)
        user_repo.save()

        return jsonify({"success": True, "message": "Email verified successfully!"}), 200

    # ----------------------------------------------------------
    # LOGIN
    # ----------------------------------------------------------
    def login(self):
        user_repo, _, _, _, password_service = self._get_deps()

        data     = request.get_json()
        email    = data.get("email", "").lower().strip()
        password = data.get("password", "")

        user = user_repo.find_by_email(email)

        if not user or not password_service.verify(password, user.password):
            return jsonify({"success": False, "message": "Invalid email or password"}), 401

        if not self._is_authorized_source(user):
            return jsonify({
                "success": False,
                "message": "Access denied for this platform",
            }), 403

        if not user.is_verified():
            return jsonify({
                "success": False,
                "message": "Please verify your email first",
            }), 403

        return jsonify({"success": True, **user.to_dict()}), 200

    # ----------------------------------------------------------
    # RESEND OTP
    # ----------------------------------------------------------
    def resend_otp(self):
        user_repo, otp_repo, otp_service, _, _ = self._get_deps()

        data  = request.get_json()
        email = data.get("email", "").lower().strip()

        user = user_repo.find_by_email(email)
        if not user:
            return jsonify({"success": False, "message": "Email not registered"}), 404

        if user.is_verified():
            return jsonify({"success": False, "message": "Email is already verified"}), 400

        try:
            otp_code = otp_service.generate()
            otp_repo.upsert(email, otp_code)

            sent = otp_service.send(email, user.username, otp_code)
            if not sent:
                raise Exception("Failed to send verification email")

            user_repo.save()
            return jsonify({"success": True, "message": "New verification code sent"}), 200

        except Exception as e:
            user_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500


# =============================================================
# ROUTE REGISTRATION
# One controller instance — methods are bound per request so
# each call gets fresh dependencies inside the app context
# =============================================================
_controller = AuthController()

auth_bp.add_url_rule("/register",     view_func=_controller.register,     methods=["POST"])
auth_bp.add_url_rule("/verify-email", view_func=_controller.verify_email, methods=["POST"])
auth_bp.add_url_rule("/login",        view_func=_controller.login,         methods=["POST"])
auth_bp.add_url_rule("/resend-otp",   view_func=_controller.resend_otp,    methods=["POST"])