from flask import Blueprint, request, jsonify
from repositories.user_repository import UserRepository
from repositories.otp_repository import OTPRepository
from services.otp_service import OTPService
from utils.validator import Validator
from utils.password_service import PasswordService
from models import db

auth_bp = Blueprint("auth", __name__)


# =============================================================
# AUTH CONTROLLER
# Responsibilities:
#   - Handle HTTP request/response for all auth routes
#   - Resolve role automatically from X-App-Source header
#   - Enforce source-based access control on login
#   - Orchestrate collaboration between services & repositories
# OOP Principle: Single Responsibility, Dependency Injection
# =============================================================
class AuthController:

    # Role constants
    ROLE_CLIENT = 'client'
    ROLE_ADMIN  = 'admin'

    # Source header constants
    SOURCE_MOBILE = 'mobile'
    SOURCE_WEB    = 'web'

    def __init__(self):
        self.user_repo        = UserRepository()
        self.otp_repo         = OTPRepository()
        self.otp_service      = OTPService()
        self.validator        = Validator()
        self.password_service = PasswordService()

    # ----------------------------------------------------------
    # PRIVATE: Resolve role from request source header
    # mobile → client | web → admin
    # ----------------------------------------------------------
    def _resolve_role(self) -> str:
        source = request.headers.get('X-App-Source', self.SOURCE_MOBILE).lower()
        return self.ROLE_ADMIN if source == self.SOURCE_WEB else self.ROLE_CLIENT

    # ----------------------------------------------------------
    # PRIVATE: Validate that the login source matches the role
    # Prevents clients logging in via web and admins via mobile
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
    # Role is assigned automatically — never from user input
    # ----------------------------------------------------------
    def register(self):
        data     = request.get_json()
        username = data.get("username", "").strip()
        email    = data.get("email", "").lower().strip()
        password = data.get("password", "")

        # Validate inputs via Validator
        error = self.validator.validate_registration(username, email, password)
        if error:
            return jsonify({"success": False, "message": error}), 400

        # Check uniqueness via UserRepository
        if self.user_repo.find_by_email(email):
            return jsonify({"success": False, "message": "Email already registered"}), 400
        if self.user_repo.find_by_username(username):
            return jsonify({"success": False, "message": "Username already taken"}), 400

        try:
            # Resolve role from request source — no user input involved
            role      = self._resolve_role()
            hashed_pw = self.password_service.hash(password)

            # Create user with resolved role via UserRepository
            self.user_repo.create(username, email, hashed_pw, role)
            self.user_repo.flush()

            # Generate & store OTP via OTPRepository
            otp_code = self.otp_service.generate()
            self.otp_repo.upsert(email, otp_code)

            # Send OTP email via OTPService
            sent = self.otp_service.send(email, username, otp_code)
            if not sent:
                raise Exception("Failed to send verification email")

            self.user_repo.save()
            return jsonify({
                "success": True,
                "message": "Verification code sent to your email",
            }), 201

        except Exception as e:
            self.user_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # VERIFY EMAIL
    # ----------------------------------------------------------
    def verify_email(self):
        data      = request.get_json()
        email     = data.get("email", "").lower().strip()
        user_code = data.get("code", "").strip()

        record = self.otp_repo.find_by_email_and_code(email, user_code)
        if not record:
            return jsonify({"success": False, "message": "Invalid verification code"}), 400

        if record.is_expired():
            return jsonify({"success": False, "message": "Code has expired"}), 400

        user = self.user_repo.find_by_email(email)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        user.mark_verified()
        self.otp_repo.delete(record)
        self.user_repo.save()

        return jsonify({"success": True, "message": "Email verified successfully!"}), 200

    # ----------------------------------------------------------
    # LOGIN
    # Enforces source-based access control:
    #   mobile → only clients allowed
    #   web    → only admins allowed
    # ----------------------------------------------------------
    def login(self):
        data     = request.get_json()
        email    = data.get("email", "").lower().strip()
        password = data.get("password", "")

        user = self.user_repo.find_by_email(email)

        # Verify password via PasswordService
        if not user or not self.password_service.verify(password, user.password):
            return jsonify({"success": False, "message": "Invalid email or password"}), 401

        # Check source matches role — blocks cross-app login attempts
        if not self._is_authorized_source(user):
            return jsonify({
                "success": False,
                "message": "Access denied for this platform",
            }), 403

        # Check email verification
        if not user.is_verified():
            return jsonify({
                "success": False,
                "message": "Please verify your email first",
            }), 403

        # Serialize response — role included so frontend can use it
        return jsonify({"success": True, **user.to_dict()}), 200

    # ----------------------------------------------------------
    # RESEND OTP
    # ----------------------------------------------------------
    def resend_otp(self):
        data  = request.get_json()
        email = data.get("email", "").lower().strip()

        user = self.user_repo.find_by_email(email)
        if not user:
            return jsonify({"success": False, "message": "Email not registered"}), 404

        if user.is_verified():
            return jsonify({"success": False, "message": "Email is already verified"}), 400

        try:
            otp_code = self.otp_service.generate()
            self.otp_repo.upsert(email, otp_code)

            sent = self.otp_service.send(email, user.username, otp_code)
            if not sent:
                raise Exception("Failed to send verification email")

            self.user_repo.save()
            return jsonify({"success": True, "message": "New verification code sent"}), 200

        except Exception as e:
            self.user_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500


# =============================================================
# ROUTE REGISTRATION
# =============================================================
_controller = AuthController()

auth_bp.add_url_rule("/register",     view_func=_controller.register,     methods=["POST"])
auth_bp.add_url_rule("/verify-email", view_func=_controller.verify_email, methods=["POST"])
auth_bp.add_url_rule("/login",        view_func=_controller.login,         methods=["POST"])
auth_bp.add_url_rule("/resend-otp",   view_func=_controller.resend_otp,    methods=["POST"])