from flask import Blueprint, request, jsonify
from repositories.user_repository    import UserRepository
from repositories.service_repository import ServiceRepository
from repositories.admin_repository   import AdminRepository
from repositories.ticket_repository   import TicketRepository
from repositories.schedule_repository import ScheduleRepository
from services.schedule_service        import ScheduleService
from collections import defaultdict

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

    # ----------------------------------------------------------
    # BROWSE SERVICES  (public — for the mobile "choose a service" page)
    # GET /api/services/browse?q=<search>&user_email=<email>
    #
    # Returns every service (optionally filtered by name search),
    # each annotated with:
    #   - people_waiting     current pending/active tickets
    #   - avg_wait_minutes   estimated current wait if you joined now
    #   - visited            whether this user has a ticket history here
    # Lets a customer compare services by wait time before joining.
    # ----------------------------------------------------------
    def browse_services(self):
        _, service_repo, _ = self._get_deps()
        ticket_repo   = TicketRepository()
        schedule_repo = ScheduleRepository()
        schedule_svc  = ScheduleService()

        q          = (request.args.get("q") or "").strip()
        user_email = (request.args.get("user_email") or "").strip().lower()

        services = service_repo.search_by_name(q) if q else service_repo.find_all()

        result = []
        for svc in services:
            schedule = schedule_repo.resolve_for_today(svc.id)
            tickets  = ticket_repo.find_by_service(svc.id)   # active/pending/suspended
            waiting  = [t for t in tickets
                        if t.status in (ticket_repo.STATUS_PENDING, ticket_repo.STATUS_ACTIVE)]

            per_queue = defaultdict(int)
            for t in waiting:
                per_queue[t.queue_id] += 1

            queue_waits = []
            for qid, count in per_queue.items():
                avg = schedule_svc.effective_avg(ticket_repo, qid, schedule)
                queue_waits.append(count * avg)
            avg_wait_minutes = round(sum(queue_waits) / len(queue_waits)) if queue_waits else 0

            result.append({
                **svc.to_dict(),
                "people_waiting":   len(waiting),
                "avg_wait_minutes": avg_wait_minutes,
                "num_queues":       len(svc.queues),
                "visited":          ticket_repo.has_visited(svc.id, user_email) if user_email else False,
            })

        # Show not-yet-visited services with the shortest waits first;
        # the client can re-sort however it likes.
        result.sort(key=lambda s: (s["visited"], s["avg_wait_minutes"]))

        return jsonify({"success": True, "services": result}), 200


# =============================================================
# ROUTE REGISTRATION
# =============================================================
    # ----------------------------------------------------------
    # DELETE SERVICE  (#6 — boss only)
    # DELETE /api/services/<service_id>   Body/query: { user_id }
    # Deletes the service and everything under it (queues, tickets,
    # team admins, schedules, notifications, swaps) via FK cascade.
    # ----------------------------------------------------------
    def delete_service(self, service_id):
        user_repo, service_repo, admin_repo = self._get_deps()
        data    = request.get_json(silent=True) or {}
        user_id = data.get("user_id") or request.args.get("user_id")

        if not user_id:
            return jsonify({"success": False, "message": "user_id is required"}), 400

        service = service_repo.find_by_id(int(service_id))
        if not service:
            return jsonify({"success": False, "message": "Service not found"}), 404
        if service.owner_id != int(user_id):
            return jsonify({"success": False, "message": "Only the service owner can delete it"}), 403

        try:
            from models import db
            db.session.delete(service)   # cascades to all child rows
            db.session.commit()
            return jsonify({"success": True, "message": "Service deleted"}), 200
        except Exception as e:
            from models import db
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500


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
service_bp.add_url_rule(
    "/services/browse",
    view_func=_controller.browse_services,
    methods=["GET"],
)
service_bp.add_url_rule(
    "/services/<service_id>",
    view_func=_controller.delete_service,
    methods=["DELETE"],
)