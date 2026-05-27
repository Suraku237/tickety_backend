from flask import Blueprint, request, jsonify, current_app
from repositories.user_repository    import UserRepository
from repositories.admin_repository   import AdminRepository
from repositories.invite_repository  import InviteRepository
from repositories.service_repository import ServiceRepository
from utils.password_service          import PasswordService
from utils.validator                 import Validator

team_bp = Blueprint("team", __name__)

# =============================================================
# TEAM CONTROLLER
# Responsibilities:
#   - Get all admins for a service with their user info
#   - Remove an admin from a service
#   - Generate an invite link (token) with a pre-set role
#   - Register a new admin via an invite link
# OOP Principle: Single Responsibility, Dependency Injection
# =============================================================
class TeamController:

    def _get_deps(self):
        return (
            UserRepository(),
            AdminRepository(),
            InviteRepository(),
            ServiceRepository(),
            PasswordService(),
            Validator(),
        )

    def _base_url(self):
        return current_app.config.get("BASE_URL", "https://tickety.app")

    # ----------------------------------------------------------
    # GET TEAM
    # GET /api/team?service_id=<id>
    # Returns all admins for the service with user details
    # ----------------------------------------------------------
    def get_team(self):
        user_repo, admin_repo, _, _, _, _ = self._get_deps()

        service_id = request.args.get("service_id")
        if not service_id:
            return jsonify({"success": False, "message": "service_id is required"}), 400

        admins = admin_repo.find_by_service(int(service_id))

        team = []
        for admin in admins:
            user = user_repo.find_by_email(
                # Load via relationship if available, fallback to query
                admin.user.email if hasattr(admin, 'user') and admin.user else None
            )
            if not user:
                from models import User
                user = User.query.get(admin.user_id)
            if user:
                team.append({
                    "admin_id":   str(admin.id),
                    "user_id":    str(user.id),
                    "username":   user.username,
                    "email":      user.email,
                    "admin_role": admin.admin_role,
                    "joined_at":  admin.created_at.isoformat(),
                })

        return jsonify({"success": True, "team": team}), 200

    # ----------------------------------------------------------
    # REMOVE ADMIN
    # DELETE /api/team/<admin_id>
    # Cannot remove the boss
    # ----------------------------------------------------------
    def remove_admin(self, admin_id):
        _, admin_repo, _, _, _, _ = self._get_deps()

        admin = admin_repo.find_by_user_and_service(
            *self._parse_admin_id(admin_id)
        ) if False else None

        # Direct lookup by admin primary key
        from models import Admin
        admin = Admin.query.get(int(admin_id))

        if not admin:
            return jsonify({"success": False, "message": "Admin not found"}), 404

        if admin.is_boss():
            return jsonify({"success": False, "message": "Cannot remove the service owner"}), 403

        try:
            from models import db
            db.session.delete(admin)
            db.session.commit()
            return jsonify({"success": True, "message": "Admin removed from service"}), 200
        except Exception as e:
            from models import db
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # GENERATE INVITE LINK
    # POST /api/team/invite
    # Body: { service_id, admin_role: 'manager' | 'agent' }
    # Returns a single-use invite URL valid for 48 hours
    # ----------------------------------------------------------
    def generate_invite(self):
        _, admin_repo, invite_repo, _, _, _ = self._get_deps()

        data       = request.get_json()
        service_id = data.get("service_id")
        admin_role = data.get("admin_role", "agent").strip()

        if not service_id:
            return jsonify({"success": False, "message": "service_id is required"}), 400

        if admin_role not in {admin_repo.ROLE_MANAGER, admin_repo.ROLE_AGENT}:
            return jsonify({
                "success": False,
                "message": "admin_role must be 'manager' or 'agent'",
            }), 400

        try:
            invite = invite_repo.create(
                service_id = int(service_id),
                admin_role = admin_role,
            )
            invite_repo.save()

            return jsonify({
                "success":    True,
                "invite":     invite.to_dict(self._base_url()),
                "invite_url": f"{self._base_url()}/invite/{invite.token}",
            }), 201
        except Exception as e:
            invite_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # VALIDATE INVITE TOKEN (frontend calls this on page load)
    # GET /api/team/invite/<token>
    # Returns the role and service name so the UI can pre-fill
    # ----------------------------------------------------------
    def validate_invite(self, token):
        _, _, invite_repo, service_repo, _, _ = self._get_deps()

        invite = invite_repo.find_by_token(token)
        if not invite or not invite.is_valid():
            return jsonify({
                "success": False,
                "message": "This invite link is invalid or has expired",
            }), 400

        service = service_repo.find_by_id(invite.service_id)
        return jsonify({
            "success":      True,
            "token":        invite.token,
            "admin_role":   invite.admin_role,
            "service_name": service.name if service else "",
            "expires_at":   invite.expires_at.isoformat(),
        }), 200

    # ----------------------------------------------------------
    # REGISTER VIA INVITE
    # POST /api/team/invite/<token>/register
    # Body: { username, email, password }
    # Creates a User + Admin row with the pre-set role.
    # Two-phase like normal registration:
    #   Phase 1: create PendingRegistration + send OTP
    #   Phase 2: /verify-email (reuses existing route)
    #   Phase 3 (here): on verify success, create Admin row
    #
    # For simplicity and code reuse, Phase 1 + 2 are handled
    # by the existing /register and /verify-email routes with
    # the invite token stored in the pending row's role field
    # as a special marker. After verification, the admin row
    # is created by a separate endpoint below.
    # ----------------------------------------------------------
    def complete_invite(self, token):
        """
        POST /api/team/invite/<token>/complete
        Body: { email }
        Called AFTER email verification succeeds.
        Creates the Admin row linking the verified user
        to the service with the pre-set role.
        """
        user_repo, admin_repo, invite_repo, _, _, _ = self._get_deps()

        data  = request.get_json()
        email = data.get("email", "").lower().strip()

        if not email:
            return jsonify({"success": False, "message": "Email is required"}), 400

        invite = invite_repo.find_by_token(token)
        if not invite or not invite.is_valid():
            return jsonify({
                "success": False,
                "message": "This invite link is invalid or has expired",
            }), 400

        user = user_repo.find_by_email(email)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        if not user.is_verified():
            return jsonify({"success": False, "message": "Email must be verified first"}), 403

        # Guard: already a member of this service
        existing = admin_repo.find_by_user_and_service(user.id, invite.service_id)
        if existing:
            return jsonify({
                "success": False,
                "message": "This user is already a member of the service",
            }), 400

        try:
            admin_repo.create(
                user_id    = user.id,
                service_id = invite.service_id,
                admin_role = invite.admin_role,
            )
            invite_repo.consume(invite)
            admin_repo.save()

            service = ServiceRepository().find_by_id(invite.service_id)
            return jsonify({
                "success":      True,
                "message":      f"Welcome to {service.name if service else 'the service'}!",
                "admin_role":   invite.admin_role,
                "service_id":   str(invite.service_id),
                "service_name": service.name if service else "",
            }), 200
        except Exception as e:
            admin_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500


# =============================================================
# ROUTE REGISTRATION
# =============================================================
_controller = TeamController()

team_bp.add_url_rule("/team",                               view_func=_controller.get_team,        methods=["GET"])
team_bp.add_url_rule("/team/<int:admin_id>",                view_func=_controller.remove_admin,    methods=["DELETE"])
team_bp.add_url_rule("/team/invite",                        view_func=_controller.generate_invite, methods=["POST"])
team_bp.add_url_rule("/team/invite/<string:token>",         view_func=_controller.validate_invite, methods=["GET"])
team_bp.add_url_rule("/team/invite/<string:token>/complete",view_func=_controller.complete_invite, methods=["POST"])