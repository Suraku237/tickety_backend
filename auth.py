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
    # CHANGE PASSWORD
    # POST /api/change-password
    # Body: { user_id, current_password, new_password }
    # ----------------------------------------------------------
    def change_password(self):
        user_repo, _, _, _, password_service = self._get_deps()

        data = request.get_json() or {}
        user_id = data.get("user_id")
        current = data.get("current_password", "")
        new_pw = data.get("new_password", "")

        if not user_id or not current or not new_pw:
            return jsonify({"success": False, "message": "user_id, current_password and new_password are required"}), 400

        user = user_repo.find_by_id(int(user_id))
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        if not password_service.verify(current, user.password):
            return jsonify({"success": False, "message": "Current password is incorrect"}), 403

        try:
            user.password = password_service.hash(new_pw)
            user_repo.save()
            return jsonify({"success": True, "message": "Password changed"}), 200
        except Exception as e:
            user_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # DELETE ACCOUNT
    # POST /api/delete-account
    # Body: { user_id }
    # ----------------------------------------------------------
    def delete_account(self):
        user_repo, _, _, _, _ = self._get_deps()

        data = request.get_json() or {}
        user_id = data.get("user_id")
        if not user_id:
            return jsonify({"success": False, "message": "user_id is required"}), 400

        user = user_repo.find_by_id(int(user_id))
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        try:
            user_repo.delete(user)
            user_repo.save()
            return jsonify({"success": True, "message": "Account deleted"}), 200
        except Exception as e:
            user_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # FORGOT PASSWORD  (Step 1 of 3)
    # POST /api/forgot-password
    # Body: { email }
    # Checks the email exists, generates a ResetCode, sends it.
    # ----------------------------------------------------------
    def forgot_password(self):
        user_repo, otp_repo, otp_service, _, _ = self._get_deps()

        data  = request.get_json() or {}
        email = data.get("email", "").lower().strip()

        if not email:
            return jsonify({"success": False, "message": "Email is required"}), 400

        user = user_repo.find_by_email(email)
        if not user:
            # Return success to avoid email enumeration
            return jsonify({
                "success": True,
                "message": "If this email is registered, a reset code has been sent",
            }), 200

        try:
            otp_code = otp_service.generate()
            otp_repo.upsert_reset(email=email, code=otp_code)

            sent = otp_service.send_reset(email, user.username, otp_code)
            if not sent:
                raise Exception("Failed to send reset email")

            user_repo.save()
            return jsonify({
                "success": True,
                "message": "Reset code sent to your email",
            }), 200

        except Exception as e:
            user_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # VERIFY RESET CODE  (Step 2 of 3)
    # POST /api/verify-reset-code
    # Body: { email, code }
    # Validates the code; on success returns a one-time token
    # the client passes to /reset-password.
    # ----------------------------------------------------------
    def verify_reset_code(self):
        user_repo, otp_repo, _, _, _ = self._get_deps()

        data      = request.get_json() or {}
        email     = data.get("email", "").lower().strip()
        user_code = data.get("code",  "").strip()

        if not email or not user_code:
            return jsonify({"success": False, "message": "email and code are required"}), 400

        reset = otp_repo.find_reset_by_email_and_code(email, user_code)
        if not reset:
            return jsonify({"success": False, "message": "Invalid reset code"}), 400

        if reset.is_expired():
            return jsonify({"success": False, "message": "Reset code has expired"}), 400

        return jsonify({
            "success": True,
            "message": "Code verified",
            "email":   email,
        }), 200

    # ----------------------------------------------------------
    # RESET PASSWORD  (Step 3 of 3)
    # POST /api/reset-password
    # Body: { email, code, new_password }
    # Re-validates code, hashes + saves the new password,
    # deletes the reset record.
    # ----------------------------------------------------------
    def reset_password(self):
        user_repo, otp_repo, _, _, password_service = self._get_deps()

        data         = request.get_json() or {}
        email        = data.get("email",        "").lower().strip()
        user_code    = data.get("code",         "").strip()
        new_password = data.get("new_password", "")

        if not email or not user_code or not new_password:
            return jsonify({
                "success": False,
                "message": "email, code and new_password are required",
            }), 400

        if len(new_password) < 6:
            return jsonify({
                "success": False,
                "message": "Password must be at least 6 characters",
            }), 400

        reset = otp_repo.find_reset_by_email_and_code(email, user_code)
        if not reset:
            return jsonify({"success": False, "message": "Invalid or expired reset code"}), 400

        if reset.is_expired():
            return jsonify({"success": False, "message": "Reset code has expired"}), 400

        user = user_repo.find_by_email(email)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        try:
            user.password = password_service.hash(new_password)
            otp_repo.delete_reset(reset)
            user_repo.save()
            return jsonify({"success": True, "message": "Password reset successfully"}), 200
        except Exception as e:
            user_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

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
auth_bp.add_url_rule("/change-password", view_func=_controller.change_password, methods=["POST"])
auth_bp.add_url_rule("/delete-account",  view_func=_controller.delete_account,  methods=["POST"])
auth_bp.add_url_rule("/forgot-password",   view_func=_controller.forgot_password,   methods=["POST"])
auth_bp.add_url_rule("/verify-reset-code", view_func=_controller.verify_reset_code, methods=["POST"])
auth_bp.add_url_rule("/reset-password",    view_func=_controller.reset_password,    methods=["POST"])


# =============================================================
# EMAIL CHANGE ENDPOINTS  (3-step verified flow)
# These live in auth_bp but are separate from AuthController.
# =============================================================

from flask import Blueprint
from models import db, User, ResetCode
from repositories.user_repository import UserRepository
from repositories.otp_repository   import OTPRepository
from services.otp_service          import OTPService
from utils.password_service        import PasswordService
import secrets, string
from datetime import datetime, timedelta, timezone

# Temporary in-memory store for pending email changes:
#   { user_id: { 'new_email': str, 'old_code': str, 'new_code': str,
#                'old_verified': bool, 'expire_at': datetime } }
_pending_changes: dict = {}

def _gen_code() -> str:
    return str(secrets.randbelow(10 ** 6)).zfill(6)

def _expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=10)

class EmailChangeController:

    def _send(self, email: str, username: str, code: str, subject: str) -> bool:
        return OTPService().send_reset(email, username, code)

    # ----------------------------------------------------------
    # STEP 1 — initiate
    # POST /api/initiate-email-change
    # Body: { user_id, new_email }
    # ----------------------------------------------------------
    def initiate(self):
        data     = request.get_json() or {}
        user_id  = data.get('user_id')
        new_email = data.get('new_email', '').lower().strip()

        if not user_id or not new_email or '@' not in new_email:
            return jsonify({'success': False, 'message': 'user_id and valid new_email required'}), 400

        user = UserRepository().find_by_id(int(user_id))
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        if UserRepository().find_by_email(new_email):
            return jsonify({'success': False, 'message': 'That email is already in use'}), 400

        old_code = _gen_code()
        _pending_changes[str(user_id)] = {
            'new_email':    new_email,
            'old_code':     old_code,
            'new_code':     None,
            'old_verified': False,
            'expire_at':    _expiry(),
        }

        sent = OTPService().send_reset(user.email, user.username, old_code)
        if not sent:
            return jsonify({'success': False, 'message': 'Failed to send verification email'}), 500

        return jsonify({'success': True, 'message': 'Code sent to your current email'}), 200

    # ----------------------------------------------------------
    # STEP 2 — confirm old email
    # POST /api/confirm-old-email
    # Body: { user_id, code }
    # ----------------------------------------------------------
    def confirm_old(self):
        data    = request.get_json() or {}
        user_id = str(data.get('user_id', ''))
        code    = data.get('code', '').strip()

        pending = _pending_changes.get(user_id)
        if not pending:
            return jsonify({'success': False, 'message': 'No pending email change found'}), 404

        if pending['expire_at'].replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
            _pending_changes.pop(user_id, None)
            return jsonify({'success': False, 'message': 'Code has expired, please start again'}), 400

        if pending['old_code'] != code:
            return jsonify({'success': False, 'message': 'Incorrect code'}), 400

        # Send OTP to the new address
        user     = UserRepository().find_by_id(int(user_id))
        new_code = _gen_code()
        pending['new_code']     = new_code
        pending['old_verified'] = True
        pending['expire_at']    = _expiry()

        sent = OTPService().send_reset(pending['new_email'], user.username if user else 'User', new_code)
        if not sent:
            return jsonify({'success': False, 'message': 'Failed to send code to new email'}), 500

        return jsonify({'success': True, 'message': 'Code sent to your new email'}), 200

    # ----------------------------------------------------------
    # STEP 3 — confirm new email
    # POST /api/confirm-new-email
    # Body: { user_id, code }
    # ----------------------------------------------------------
    def confirm_new(self):
        data    = request.get_json() or {}
        user_id = str(data.get('user_id', ''))
        code    = data.get('code', '').strip()

        pending = _pending_changes.get(user_id)
        if not pending or not pending.get('old_verified'):
            return jsonify({'success': False, 'message': 'Please complete step 1 first'}), 400

        if pending['expire_at'].replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
            _pending_changes.pop(user_id, None)
            return jsonify({'success': False, 'message': 'Code has expired, please start again'}), 400

        if pending['new_code'] != code:
            return jsonify({'success': False, 'message': 'Incorrect code'}), 400

        user_repo = UserRepository()
        user      = user_repo.find_by_id(int(user_id))
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        try:
            user.email = pending['new_email']
            user_repo.save()
            _pending_changes.pop(user_id, None)
            return jsonify({'success': True, 'message': 'Email updated successfully'}), 200
        except Exception as e:
            user_repo.rollback()
            return jsonify({'success': False, 'message': str(e)}), 500


_email_ctrl = EmailChangeController()
auth_bp.add_url_rule('/initiate-email-change', view_func=_email_ctrl.initiate,     methods=['POST'])
auth_bp.add_url_rule('/confirm-old-email',     view_func=_email_ctrl.confirm_old,  methods=['POST'])
auth_bp.add_url_rule('/confirm-new-email',     view_func=_email_ctrl.confirm_new,  methods=['POST'])