from flask import Blueprint, request, jsonify
from repositories.user_repository import UserRepository
from repositories.otp_repository  import OTPRepository
from services.otp_service         import OTPService
from utils.password_service       import PasswordService
from utils.validator              import Validator

profile_bp = Blueprint("profile", __name__)

# =============================================================
# PROFILE CONTROLLER
# Responsibilities:
#   - Update username
#   - Initiate email change (OTP to old email → OTP to new email)
#   - Confirm email change (verify new email OTP)
#   - Update password (requires current password confirmation)
#
# EMAIL CHANGE FLOW:
#   Step 1 — POST /api/profile/email/initiate
#             Sends OTP to the OLD email to confirm ownership.
#   Step 2 — POST /api/profile/email/confirm-old
#             Verifies old-email OTP, then sends OTP to NEW email.
#   Step 3 — POST /api/profile/email/confirm-new
#             Verifies new-email OTP and applies the change.
#
# OOP Principle: Single Responsibility, Dependency Injection
# =============================================================
class ProfileController:

    # Temporary in-memory store for pending email changes.
    # Maps old_email → { new_email, old_verified: bool }
    # In production, store this in Redis or a DB table.
    _pending_email_changes: dict = {}

    def _get_deps(self):
        return (
            UserRepository(),
            OTPRepository(),
            OTPService(),
            PasswordService(),
            Validator(),
        )

    # ----------------------------------------------------------
    # UPDATE USERNAME
    # PATCH /api/profile/username
    # Body: { user_id, username }
    # ----------------------------------------------------------
    def update_username(self):
        user_repo, _, _, _, validator = self._get_deps()

        data     = request.get_json()
        user_id  = data.get("user_id")
        username = (data.get("username") or "").strip()

        if not user_id:
            return jsonify({"success": False, "message": "user_id is required"}), 400

        err = validator.validate_username(username)
        if err:
            return jsonify({"success": False, "message": err}), 400

        from models import User
        user = User.query.get(int(user_id))
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        existing = user_repo.find_by_username(username)
        if existing and existing.id != user.id:
            return jsonify({"success": False, "message": "Username already taken"}), 400

        try:
            user.username = username
            user_repo.save()
            return jsonify({"success": True, "message": "Username updated", "username": username}), 200
        except Exception as e:
            user_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # STEP 1 — INITIATE EMAIL CHANGE
    # POST /api/profile/email/initiate
    # Body: { user_id, new_email }
    # Sends OTP to the OLD (current) email to confirm ownership.
    # ----------------------------------------------------------
    def initiate_email_change(self):
        user_repo, otp_repo, otp_service, _, validator = self._get_deps()

        data      = request.get_json()
        user_id   = data.get("user_id")
        new_email = (data.get("new_email") or "").lower().strip()

        if not user_id:
            return jsonify({"success": False, "message": "user_id is required"}), 400

        err = validator.validate_email(new_email)
        if err:
            return jsonify({"success": False, "message": err}), 400

        from models import User
        user = User.query.get(int(user_id))
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        if user.email == new_email:
            return jsonify({"success": False, "message": "New email must be different from current email"}), 400

        if user_repo.find_by_email(new_email):
            return jsonify({"success": False, "message": "This email is already in use"}), 400

        try:
            otp_code = otp_service.generate()
            expiry   = otp_repo.get_expiry()

            # Reuse reset OTP table for the old-email verification step
            otp_repo.upsert_reset(user.email, otp_code)
            user_repo.save()

            # Store pending change in memory
            ProfileController._pending_email_changes[user.email] = {
                "new_email":    new_email,
                "old_verified": False,
            }

            sent = otp_service.send(user.email, user.username, otp_code)
            if not sent:
                raise Exception("Failed to send verification email")

            return jsonify({
                "success": True,
                "message": f"Verification code sent to your current email ({user.email})",
            }), 200
        except Exception as e:
            user_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # STEP 2 — CONFIRM OLD EMAIL OTP
    # POST /api/profile/email/confirm-old
    # Body: { user_id, code }
    # Verifies the OTP sent to the OLD email.
    # On success, sends OTP to the NEW email.
    # ----------------------------------------------------------
    def confirm_old_email(self):
        user_repo, otp_repo, otp_service, _, _ = self._get_deps()

        data    = request.get_json()
        user_id = data.get("user_id")
        code    = (data.get("code") or "").strip()

        if not user_id or not code:
            return jsonify({"success": False, "message": "user_id and code are required"}), 400

        from models import User
        user = User.query.get(int(user_id))
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        pending = ProfileController._pending_email_changes.get(user.email)
        if not pending:
            return jsonify({"success": False, "message": "No pending email change found"}), 400

        reset = otp_repo.find_reset_by_email_and_code(user.email, code)
        if not reset:
            return jsonify({"success": False, "message": "Invalid verification code"}), 400

        if reset.is_expired():
            return jsonify({"success": False, "message": "Code has expired"}), 400

        try:
            # Clean up old OTP
            otp_repo.delete_reset(reset)
            user_repo.save()

            # Mark old email as verified in pending store
            pending["old_verified"] = True
            ProfileController._pending_email_changes[user.email] = pending

            # Send OTP to NEW email
            new_email = pending["new_email"]
            otp_code  = otp_service.generate()
            otp_repo.upsert_reset(new_email, otp_code)
            user_repo.save()

            sent = otp_service.send(new_email, user.username, otp_code)
            if not sent:
                raise Exception("Failed to send verification email to new address")

            return jsonify({
                "success": True,
                "message": f"Old email verified. Verification code sent to {new_email}",
            }), 200
        except Exception as e:
            user_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # STEP 3 — CONFIRM NEW EMAIL OTP
    # POST /api/profile/email/confirm-new
    # Body: { user_id, code }
    # Verifies the OTP sent to the NEW email and applies the change.
    # ----------------------------------------------------------
    def confirm_new_email(self):
        user_repo, otp_repo, _, _, _ = self._get_deps()

        data    = request.get_json()
        user_id = data.get("user_id")
        code    = (data.get("code") or "").strip()

        if not user_id or not code:
            return jsonify({"success": False, "message": "user_id and code are required"}), 400

        from models import User
        user = User.query.get(int(user_id))
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        pending = ProfileController._pending_email_changes.get(user.email)
        if not pending or not pending.get("old_verified"):
            return jsonify({"success": False, "message": "Please verify your current email first"}), 400

        new_email = pending["new_email"]
        reset     = otp_repo.find_reset_by_email_and_code(new_email, code)
        if not reset:
            return jsonify({"success": False, "message": "Invalid verification code"}), 400

        if reset.is_expired():
            return jsonify({"success": False, "message": "Code has expired"}), 400

        try:
            old_email  = user.email
            user.email = new_email
            otp_repo.delete_reset(reset)
            user_repo.save()

            # Clean up pending store
            ProfileController._pending_email_changes.pop(old_email, None)

            return jsonify({
                "success": True,
                "message": "Email updated successfully",
                "email":   new_email,
            }), 200
        except Exception as e:
            user_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # UPDATE PASSWORD
    # PATCH /api/profile/password
    # Body: { user_id, current_password, new_password }
    # ----------------------------------------------------------
    def update_password(self):
        user_repo, _, _, password_service, validator = self._get_deps()

        data             = request.get_json()
        user_id          = data.get("user_id")
        current_password = data.get("current_password", "")
        new_password     = data.get("new_password", "")

        if not user_id:
            return jsonify({"success": False, "message": "user_id is required"}), 400

        err = validator.validate_password(new_password)
        if err:
            return jsonify({"success": False, "message": err}), 400

        from models import User
        user = User.query.get(int(user_id))
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        if not password_service.verify(current_password, user.password):
            return jsonify({"success": False, "message": "Current password is incorrect"}), 400

        if current_password == new_password:
            return jsonify({"success": False, "message": "New password must be different from current password"}), 400

        try:
            user.password = password_service.hash(new_password)
            user_repo.save()
            return jsonify({"success": True, "message": "Password updated successfully"}), 200
        except Exception as e:
            user_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # PUSH HEALTH (#8 — is push working?)
    # GET /api/push/health?probe=1&user_id=<id>
    #   probe=1 actually contacts Google to mint a token (real test)
    # ----------------------------------------------------------
    def push_health(self):
        from services.push_service import PushService
        from models import DeviceToken
        svc   = PushService()
        probe = request.args.get("probe") == "1"
        info  = svc.probe() if probe else svc.health()

        try:
            info["device_tokens"] = DeviceToken.query.count()
            uid = request.args.get("user_id")
            if uid:
                info["my_device_tokens"] = DeviceToken.query.filter_by(user_id=int(uid)).count()
        except Exception:
            info["device_tokens"] = None

        if probe:
            info["status"] = ("working"      if info.get("token_ok")
                              else "misconfigured" if info["enabled"]
                              else "not_configured")
        else:
            info["status"] = "configured" if info["enabled"] else "not_configured"

        return jsonify({"success": True, **info}), 200

    # ----------------------------------------------------------
    # REGISTER DEVICE TOKEN (#8 push)
    # POST /api/profile/device-token  Body: { user_id, token, platform }
    # Upserts an FCM token so the backend can push to this device.
    # ----------------------------------------------------------
    def register_device_token(self):
        from models import DeviceToken, db
        data     = request.get_json() or {}
        user_id  = data.get("user_id")
        token    = (data.get("token") or "").strip()
        platform = (data.get("platform") or "").strip() or None

        if not user_id or not token:
            return jsonify({"success": False, "message": "user_id and token are required"}), 400

        try:
            existing = DeviceToken.query.filter_by(token=token).first()
            if existing:
                existing.user_id  = int(user_id)
                existing.platform = platform
            else:
                db.session.add(DeviceToken(user_id=int(user_id), token=token, platform=platform))
            db.session.commit()
            return jsonify({"success": True, "message": "Device registered"}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500


# =============================================================
# ROUTE REGISTRATION
# =============================================================
_controller = ProfileController()

profile_bp.add_url_rule("/profile/username",           view_func=_controller.update_username,      methods=["PATCH"])
profile_bp.add_url_rule("/profile/email/initiate",     view_func=_controller.initiate_email_change,methods=["POST"])
profile_bp.add_url_rule("/profile/email/confirm-old",  view_func=_controller.confirm_old_email,    methods=["POST"])
profile_bp.add_url_rule("/profile/email/confirm-new",  view_func=_controller.confirm_new_email,    methods=["POST"])
profile_bp.add_url_rule("/profile/password",           view_func=_controller.update_password,      methods=["PATCH"])
profile_bp.add_url_rule("/profile/device-token",       view_func=_controller.register_device_token,methods=["POST"])
profile_bp.add_url_rule("/push/health",                view_func=_controller.push_health,          methods=["GET"])