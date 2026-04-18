from flask import Blueprint, request, jsonify
from repositories.user_repository import UserRepository
from repositories.otp_repository  import OTPRepository
from services.otp_service         import OTPService
from utils.validator              import Validator
from utils.password_service       import PasswordService

auth_bp = Blueprint("auth", __name__)


# =============================================================
# AUTH CONTROLLER
# Responsibilities:
#   - Handle HTTP request/response for all auth routes
#   - Resolve role automatically from X-App-Source header
#   - Enforce source-based access control on login
#   - Orchestrate the two-phase registration flow:
#
#       PHASE 1 — register()
#         Validates input → hashes password → creates
#         PendingRegistration row → sends OTP.
#         NO User row is created yet.
#
#       PHASE 2 — verify_email()
#         Validates OTP against PendingRegistration →
#         creates real User row → deletes pending row →
#         commits atomically.
#
#     This guarantees that a User row only ever exists for
#     someone who has proven they own the email address.
#     Connection failures between Phase 1 and Phase 2 leave
#     only an expiring PendingRegistration row — fully retryable.
#
# OOP Principle: Single Responsibility, Dependency Injection
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
        Ensures SQLAlchemy has an active app context under Gunicorn workers.
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
        if source == self.SOURCE_WEB    and not user.is_admin():
            return False
        return True

    # ----------------------------------------------------------
    # REGISTER  (Phase 1 of 2)
    #
    # What changes vs old flow:
    #   OLD: create User → flush → send OTP → commit
    #        Problem: User exists even if OTP send fails
    #
    #   NEW: hash password → upsert PendingRegistration → send OTP → commit
    #        User row is NOT touched here at all.
    #        If OTP fails → pending row is rolled back → nothing persists
    #        If commit fails → nothing persists → user can retry freely
    # ----------------------------------------------------------
    def register(self):
        user_repo, otp_repo, otp_service, validator, password_service = self._get_deps()

        data     = request.get_json()
        username = data.get("username", "").strip()
        email    = data.get("email",    "").lower().strip()
        password = data.get("password", "")

        # --- Input validation ---
        error = validator.validate_registration(username, email, password)
        if error:
            return jsonify({"success": False, "message": error}), 400

        # --- Guard: email already taken by a VERIFIED user ---
        if user_repo.find_by_email(email):
            return jsonify({"success": False, "message": "Email already registered"}), 400

        # --- Guard: username already taken by a VERIFIED user ---
        if user_repo.find_by_username(username):
            return jsonify({"success": False, "message": "Username already taken"}), 400

        try:
            role      = self._resolve_role()
            hashed_pw = password_service.hash(password)
            otp_code  = otp_service.generate()

            # Upsert pending registration (handles the resend case too)
            otp_repo.upsert_pending(
                email           = email,
                username        = username,
                hashed_password = hashed_pw,
                role            = role,
                code            = otp_code,
            )

            # Send OTP — if this fails we raise and roll back the pending row
            sent = otp_service.send(email, username, otp_code)
            if not sent:
                raise Exception("Failed to send verification email")

            # Commit the pending row only after OTP confirmed sent
            user_repo.save()

            return jsonify({
                "success": True,
                "message": "Verification code sent to your email",
            }), 201

        except Exception as e:
            user_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # VERIFY EMAIL  (Phase 2 of 2)
    #
    # What changes vs old flow:
    #   OLD: look up existing User → mark verified → delete ResetCode → commit
    #
    #   NEW: look up PendingRegistration by email + code
    #        → check expiry
    #        → create real User row from pending payload
    #        → delete pending row
    #        → commit atomically
    #        User is born already verified (verified=True from the start)
    # ----------------------------------------------------------
    def verify_email(self):
        user_repo, otp_repo, _, _, _ = self._get_deps()

        data      = request.get_json()
        email     = data.get("email", "").lower().strip()
        user_code = data.get("code",  "").strip()

        # --- Look up the pending record ---
        pending = otp_repo.find_pending_by_email_and_code(email, user_code)
        if not pending:
            return jsonify({"success": False, "message": "Invalid verification code"}), 400

        if pending.is_expired():
            return jsonify({"success": False, "message": "Code has expired"}), 400

        try:
            payload = pending.to_user_payload()

            # Create the real User — already marked verified from the start
            user = user_repo.create(
                username        = payload["username"],
                email           = payload["email"],
                hashed_password = payload["hashed_password"],
                role            = payload["role"],
            )
            user.mark_verified()

            # Remove the pending row — it has served its purpose
            otp_repo.delete_pending(pending)

            # Single atomic commit: User created + pending deleted together
            user_repo.save()

            return jsonify({"success": True, "message": "Email verified successfully!",**user.to_dict()}), 200

        except Exception as e:
            user_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # LOGIN
    # Unchanged — only verified Users exist in the users table now,
    # so the is_verified() check is a safety net, not load-bearing.
    # ----------------------------------------------------------
    def login(self):
        user_repo, _, _, _, password_service = self._get_deps()

        data     = request.get_json()
        email    = data.get("email",    "").lower().strip()
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
    #
    # What changes vs old flow:
    #   OLD: find User → check not already verified → generate new OTP
    #        → upsert ResetCode → send → commit
    #
    #   NEW: find PendingRegistration → generate new OTP
    #        → update the pending row's code → send → commit
    #        No User row is involved at all.
    # ----------------------------------------------------------
    def resend_otp(self):
        user_repo, otp_repo, otp_service, _, _ = self._get_deps()

        data  = request.get_json()
        email = data.get("email", "").lower().strip()

        # Must have a pending registration to resend to
        pending = otp_repo.find_pending_by_email(email)
        if not pending:
            return jsonify({
                "success": False,
                "message": "No pending registration found for this email",
            }), 404

        try:
            otp_code = otp_service.generate()
            expiry   = otp_repo.get_expiry()
            pending.update_code(otp_code, expiry)

            sent = otp_service.send(email, pending.username, otp_code)
            if not sent:
                raise Exception("Failed to send verification email")

            user_repo.save()
            return jsonify({"success": True, "message": "New verification code sent"}), 200

        except Exception as e:
            user_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500


# =============================================================
# ROUTE REGISTRATION
# =============================================================
_controller = AuthController()

auth_bp.add_url_rule("/register",     view_func=_controller.register,     methods=["POST"])
auth_bp.add_url_rule("/verify-email", view_func=_controller.verify_email, methods=["POST"])
auth_bp.add_url_rule("/login",        view_func=_controller.login,        methods=["POST"])
auth_bp.add_url_rule("/resend-otp",   view_func=_controller.resend_otp,   methods=["POST"])