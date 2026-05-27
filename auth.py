from flask import Blueprint, request, jsonify
from repositories.user_repository    import UserRepository
from repositories.otp_repository     import OTPRepository
from repositories.admin_repository   import AdminRepository
from repositories.service_repository import ServiceRepository
from services.otp_service            import OTPService
from utils.validator                 import Validator
from utils.password_service          import PasswordService

auth_bp = Blueprint("auth", __name__)


# =============================================================
# AUTH CONTROLLER
# =============================================================
class AuthController:

    ROLE_CLIENT   = 'client'
    ROLE_ADMIN    = 'admin'
    SOURCE_MOBILE = 'mobile'
    SOURCE_WEB    = 'web'

    def _get_deps(self):
        return (
            UserRepository(),
            OTPRepository(),
            OTPService(),
            Validator(),
            PasswordService(),
        )

    def _resolve_role(self) -> str:
        source = request.headers.get('X-App-Source', self.SOURCE_MOBILE).lower()
        return self.ROLE_ADMIN if source == self.SOURCE_WEB else self.ROLE_CLIENT

    def _is_authorized_source(self, user) -> bool:
        source = request.headers.get('X-App-Source', self.SOURCE_MOBILE).lower()
        if source == self.SOURCE_MOBILE and not user.is_client():
            return False
        if source == self.SOURCE_WEB    and not user.is_admin():
            return False
        return True

    # ----------------------------------------------------------
    # PRIVATE: Build full session payload for a user
    # Looks up admin entry + service so every login response
    # includes admin_role, service_id and service_name —
    # exactly what the frontend session needs.
    # ----------------------------------------------------------
    def _build_session_payload(self, user) -> dict:
        """
        Return the full dict the frontend stores in sessionStorage.
        Merges user.to_dict() with admin role + service info.
        """
        admin_repo   = AdminRepository()
        service_repo = ServiceRepository()

        admin_entries = admin_repo.find_by_user(user.id)
        admin_entry   = admin_entries[0] if admin_entries else None

        service_id   = admin_entry.service_id if admin_entry else None
        admin_role   = admin_entry.admin_role  if admin_entry else None
        service      = service_repo.find_by_id(service_id) if service_id else None
        service_name = service.name if service else None

        return {
            **user.to_dict(),
            "admin_role":   admin_role,
            "service_id":   str(service_id)  if service_id   else None,
            "service_name": service_name,
        }

    # ----------------------------------------------------------
    # REGISTER  (Phase 1 of 2)
    # ----------------------------------------------------------
    def register(self):
        user_repo, otp_repo, otp_service, validator, password_service = self._get_deps()

        data     = request.get_json()
        username = data.get("username", "").strip()
        email    = data.get("email",    "").lower().strip()
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
            otp_code  = otp_service.generate()

            otp_repo.upsert_pending(
                email           = email,
                username        = username,
                hashed_password = hashed_pw,
                role            = role,
                code            = otp_code,
            )

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
    # VERIFY EMAIL  (Phase 2 of 2)
    # Returns full session payload so frontend can store
    # admin_role + service info immediately after verification.
    # ----------------------------------------------------------
    def verify_email(self):
        user_repo, otp_repo, _, _, _ = self._get_deps()

        data      = request.get_json()
        email     = data.get("email", "").lower().strip()
        user_code = data.get("code",  "").strip()

        pending = otp_repo.find_pending_by_email_and_code(email, user_code)
        if not pending:
            return jsonify({"success": False, "message": "Invalid verification code"}), 400

        if pending.is_expired():
            return jsonify({"success": False, "message": "Code has expired"}), 400

        try:
            payload = pending.to_user_payload()
            user    = user_repo.create(
                username        = payload["username"],
                email           = payload["email"],
                hashed_password = payload["hashed_password"],
                role            = payload["role"],
            )
            user.mark_verified()
            otp_repo.delete_pending(pending)
            user_repo.save()

            return jsonify({
                "success": True,
                "message": "Email verified successfully!",
                **user.to_dict(),
            }), 200

        except Exception as e:
            user_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # LOGIN
    # Now returns full session payload including admin_role,
    # service_id and service_name so the frontend has everything
    # it needs without requiring a separate API call.
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

        session_payload = self._build_session_payload(user)

        return jsonify({
            "success": True,
            **session_payload,
        }), 200

    # ----------------------------------------------------------
    # RESEND OTP
    # ----------------------------------------------------------
    def resend_otp(self):
        user_repo, otp_repo, otp_service, _, _ = self._get_deps()

        data  = request.get_json()
        email = data.get("email", "").lower().strip()

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