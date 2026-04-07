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
# auth.py
class AuthController:
    # ... constructor and helpers ...

    def register(self):
        data = request.get_json()
        email = data.get("email", "").lower().strip()
        username = data.get("username", "").strip()

        # Check if user already exists
        if self.user_repo.find_by_email(email):
            return jsonify({"success": False, "message": "Email already registered"}), 400

        try:
            otp_code = self.otp_service.generate()
            self.otp_repo.upsert(email, otp_code) # Save OTP to 'resets' table
            
            # Send from kwetejunior9@gmail.com via OTPService
            sent = self.otp_service.send(email, username, otp_code)
            if not sent:
                raise Exception("Email service failed")

            db.session.commit()
            return jsonify({"success": True, "message": "Verification code sent"}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    def verify_email(self):
        data = request.get_json()
        email = data.get("email", "").lower().strip()
        code = data.get("code", "").strip()
        # Received from Flutter in memory
        username = data.get("username", "").strip()
        password = data.get("password", "")

        otp_record = self.otp_repo.find_by_email_and_code(email, code) #
        if not otp_record or otp_record.is_expired(): #
            return jsonify({"success": False, "message": "Invalid or expired code"}), 400

        try:
            # ONLY NOW: Create the user in MySQL
            role = self._resolve_role()
            hashed_password = self.password_service.hash_password(password)
            
            new_user = self.user_repo.create(
                username=username,
                email=email,
                hashed_password=hashed_password,
                role=role
            )
            new_user.mark_verified() #
            
            db.session.delete(otp_record)
            self.user_repo.save()

            return jsonify({
                "success": True, 
                "message": "Account verified and created",
                "user": new_user.to_dict()
            }), 201
        except Exception as e:
            self.user_repo.rollback() #
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