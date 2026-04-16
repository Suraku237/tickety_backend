from flask import Blueprint, request, jsonify
from repositories.user_repository    import UserRepository
from repositories.service_repository import ServiceRepository
from repositories.admin_repository   import AdminRepository

service_bp = Blueprint("service", __name__)


# =============================================================
# SERVICE CONTROLLER
# Responsibilities:
#   - Handle HTTP request/response for service-related routes
#   - Orchestrate Service + Admin creation after email verification
#   - Enforce that only verified web admins can create services
# OOP Principle: Single Responsibility, Dependency Injection
#
# NOTE: Dependencies are instantiated inside each route method
# (lazy initialization) — same pattern as AuthController.
# =============================================================
class ServiceController:

    def _get_deps(self):
        """
        Lazily instantiate dependencies inside the request context.
        Ensures SQLAlchemy has an active app context under Gunicorn.
        """
        return (
            UserRepository(),
            ServiceRepository(),
            AdminRepository(),
        )

    # ----------------------------------------------------------
    # CREATE SERVICE
    # Called from React Step 3 after email verification.
    # Creates the Service row then immediately creates the Admin
    # row linking the user as 'boss' of that service.
    # ----------------------------------------------------------
    def create_service(self):
        user_repo, service_repo, admin_repo = self._get_deps()

        data         = request.get_json()
        email        = data.get("email", "").lower().strip()
        service_name = data.get("service_name", "").strip()

        # --- Validate input ---
        if not email:
            return jsonify({"success": False, "message": "Email is required"}), 400

        if not service_name or len(service_name) < 2:
            return jsonify({
                "success": False,
                "message": "Service name must be at least 2 characters",
            }), 400

        # --- Validate user exists and is a verified admin ---
        user = user_repo.find_by_email(email)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        if not user.is_verified():
            return jsonify({
                "success": False,
                "message": "Email must be verified before creating a service",
            }), 403

        if not user.is_admin():
            return jsonify({
                "success": False,
                "message": "Only admin accounts can create services",
            }), 403

        # --- Guard: prevent duplicate service name for same owner ---
        existing = service_repo.find_by_name_and_owner(service_name, user.id)
        if existing:
            return jsonify({
                "success": False,
                "message": "You already have a service with this name",
            }), 400

        try:
            # 1. Create the Service row
            service = service_repo.create(name=service_name, owner_id=user.id)

            # 2. Flush to get service.id without committing
            service_repo.flush()

            # 3. Create the Admin row — user is 'boss' of this service
            admin_repo.create(
                user_id=user.id,
                service_id=service.id,
                admin_role=AdminRepository.ROLE_BOSS,
            )

            # 4. Single commit for both rows — atomic operation
            service_repo.save()

            return jsonify({
                "success":      True,
                "message":      "Service created successfully",
                "user_id":      str(user.id),
                "username":     user.username,
                "email":        user.email,
                "role":         user.role,
                "admin_role":   AdminRepository.ROLE_BOSS,
                "service_id":   str(service.id),
                "service_name": service.name,
            }), 201

        except Exception as e:
            service_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # GET MY SERVICES
    # Returns all services owned by the authenticated user.
    # (Useful later for a service selector if a boss owns multiple)
    # ----------------------------------------------------------
    def get_my_services(self):
        user_repo, service_repo, _ = self._get_deps()

        email = request.args.get("email", "").lower().strip()
        if not email:
            return jsonify({"success": False, "message": "Email is required"}), 400

        user = user_repo.find_by_email(email)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        services = service_repo.find_by_owner(user.id)
        return jsonify({
            "success":  True,
            "services": [s.to_dict() for s in services],
        }), 200


# =============================================================
# ROUTE REGISTRATION
# =============================================================
_controller = ServiceController()

service_bp.add_url_rule(
    "/services",
    view_func=_controller.create_service,
    methods=["POST"],
)
service_bp.add_url_rule(
    "/services/mine",
    view_func=_controller.get_my_services,
    methods=["GET"],
)