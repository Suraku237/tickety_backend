from flask import Blueprint, request, jsonify, current_app
from repositories.user_repository    import UserRepository
from repositories.admin_repository   import AdminRepository
from repositories.invite_repository  import InviteRepository
from repositories.service_repository import ServiceRepository
from utils.password_service          import PasswordService
from utils.validator                 import Validator
from services.notification_service   import NotificationService

team_bp = Blueprint("team", __name__)

# =============================================================
# TEAM CONTROLLER — updated with notifications
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
            NotificationService(),
        )

    def _base_url(self):
        return current_app.config.get("BASE_URL", "https://tickety.app")

    def get_team(self):
        user_repo, admin_repo, _, _, _, _, _ = self._get_deps()
        service_id = request.args.get("service_id")
        if not service_id:
            return jsonify({"success": False, "message": "service_id is required"}), 400

        admins = admin_repo.find_by_service(int(service_id))
        team   = []
        for admin in admins:
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

    def remove_admin(self, admin_id):
        _, _, _, _, _, _, notif_svc = self._get_deps()
        from models import Admin
        admin = Admin.query.get(int(admin_id))
        if not admin:
            return jsonify({"success": False, "message": "Admin not found"}), 404
        if admin.is_boss():
            return jsonify({"success": False, "message": "Cannot remove the service owner"}), 403

        from models import User, db
        user       = User.query.get(admin.user_id)
        service_id = admin.service_id
        username   = user.username if user else "Unknown"

        try:
            db.session.delete(admin)
            db.session.commit()
            notif_svc.member_removed(service_id, username)
            return jsonify({"success": True, "message": "Admin removed from service"}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    def generate_invite(self):
        _, admin_repo, invite_repo, _, _, _, notif_svc = self._get_deps()
        data       = request.get_json()
        service_id = data.get("service_id")
        admin_role = data.get("admin_role", "agent").strip()

        if not service_id:
            return jsonify({"success": False, "message": "service_id is required"}), 400
        if admin_role not in {admin_repo.ROLE_MANAGER, admin_repo.ROLE_AGENT}:
            return jsonify({"success": False, "message": "admin_role must be 'manager' or 'agent'"}), 400

        try:
            invite = invite_repo.create(service_id=int(service_id), admin_role=admin_role)
            invite_repo.save()
            notif_svc.invite_generated(
                int(service_id), admin_role,
                invite.expires_at.strftime('%Y-%m-%d %H:%M UTC')
            )
            return jsonify({
                "success":    True,
                "invite":     invite.to_dict(self._base_url()),
                "invite_url": f"{self._base_url()}/invite/{invite.token}",
            }), 201
        except Exception as e:
            invite_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    def validate_invite(self, token):
        _, _, invite_repo, service_repo, _, _, _ = self._get_deps()
        invite = invite_repo.find_by_token(token)
        if not invite or not invite.is_valid():
            return jsonify({"success": False, "message": "This invite link is invalid or has expired"}), 400
        service = service_repo.find_by_id(invite.service_id)
        return jsonify({
            "success":      True,
            "token":        invite.token,
            "admin_role":   invite.admin_role,
            "service_name": service.name if service else "",
            "expires_at":   invite.expires_at.isoformat(),
        }), 200

    def complete_invite(self, token):
        user_repo, admin_repo, invite_repo, _, _, _, notif_svc = self._get_deps()
        data  = request.get_json()
        email = data.get("email", "").lower().strip()
        if not email:
            return jsonify({"success": False, "message": "Email is required"}), 400

        invite = invite_repo.find_by_token(token)
        if not invite or not invite.is_valid():
            return jsonify({"success": False, "message": "This invite link is invalid or has expired"}), 400

        user = user_repo.find_by_email(email)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404
        if not user.is_verified():
            return jsonify({"success": False, "message": "Email must be verified first"}), 403

        existing = admin_repo.find_by_user_and_service(user.id, invite.service_id)
        if existing:
            return jsonify({"success": False, "message": "This user is already a member of the service"}), 400

        try:
            admin_repo.create(user_id=user.id, service_id=invite.service_id, admin_role=invite.admin_role)
            invite_repo.consume(invite)
            admin_repo.save()
            notif_svc.team_joined(invite.service_id, user.username, invite.admin_role)

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


_controller = TeamController()

team_bp.add_url_rule("/team",                                view_func=_controller.get_team,        methods=["GET"])
team_bp.add_url_rule("/team/<int:admin_id>",                 view_func=_controller.remove_admin,    methods=["DELETE"])
team_bp.add_url_rule("/team/invite",                         view_func=_controller.generate_invite, methods=["POST"])
team_bp.add_url_rule("/team/invite/<string:token>",          view_func=_controller.validate_invite, methods=["GET"])
team_bp.add_url_rule("/team/invite/<string:token>/complete", view_func=_controller.complete_invite, methods=["POST"])