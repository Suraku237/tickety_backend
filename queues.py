from flask import Blueprint, request, jsonify, current_app
from repositories.queue_repository    import QueueRepository
from repositories.ticket_repository   import TicketRepository
from repositories.admin_repository    import AdminRepository
from repositories.schedule_repository import ScheduleRepository
from services.schedule_service        import ScheduleService

queue_bp = Blueprint("queue", __name__)

# =============================================================
# QUEUE CONTROLLER
# Responsibilities:
#   - CRUD for queues within a service
#   - CRUD for tickets within a queue
#   - QR join endpoint (public — customer scans and gets ticket)
#   - Ticket actions: swap, set priority, delete
# OOP Principle: Single Responsibility, Dependency Injection
# =============================================================
class QueueController:

    def _get_deps(self):
        return (
            QueueRepository(),
            TicketRepository(),
            AdminRepository(),
            ScheduleRepository(),
            ScheduleService(),
        )

    def _get_service_id(self) -> int | None:
        """Extract service_id from request JSON or query string."""
        data = request.get_json(silent=True) or {}
        return (
            data.get("service_id")
            or request.args.get("service_id")
        )

    def _base_url(self) -> str:
        return current_app.config.get("BASE_URL", "https://tickety.app")

    # ----------------------------------------------------------
    # GET ALL QUEUES FOR A SERVICE
    # GET /api/queues?service_id=<id>
    # ----------------------------------------------------------
    def get_queues(self):
        queue_repo, _, _, _, _ = self._get_deps()

        service_id = request.args.get("service_id")
        if not service_id:
            return jsonify({"success": False, "message": "service_id is required"}), 400

        queues = queue_repo.find_by_service(int(service_id))
        return jsonify({
            "success": True,
            "queues":  [q.to_dict(self._base_url()) for q in queues],
        }), 200

    # ----------------------------------------------------------
    # CREATE QUEUE
    # POST /api/queues
    # Body: { service_id, name, code, color }
    # ----------------------------------------------------------
    def create_queue(self):
        queue_repo, _, _, _, _ = self._get_deps()

        data       = request.get_json()
        service_id = data.get("service_id")
        name       = data.get("name", "").strip()
        code       = data.get("code", "").strip().upper()
        color      = data.get("color", "#DC0F0F")

        if not service_id or not name or not code:
            return jsonify({"success": False, "message": "service_id, name and code are required"}), 400

        if queue_repo.find_by_code_and_service(code, int(service_id)):
            return jsonify({"success": False, "message": "A queue with this code already exists"}), 400

        try:
            queue = queue_repo.create(
                service_id = int(service_id),
                name       = name,
                code       = code,
                color      = color,
            )
            queue_repo.flush()
            queue_repo.save()
            return jsonify({
                "success": True,
                "queue":   queue.to_dict(self._base_url()),
            }), 201
        except Exception as e:
            queue_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # DELETE QUEUE
    # DELETE /api/queues/<queue_id>
    # ----------------------------------------------------------
    def delete_queue(self, queue_id):
        queue_repo, _, _, _, _ = self._get_deps()

        queue = queue_repo.find_by_id(int(queue_id))
        if not queue:
            return jsonify({"success": False, "message": "Queue not found"}), 404

        try:
            queue_repo.delete(queue)
            queue_repo.save()
            return jsonify({"success": True, "message": "Queue deleted"}), 200
        except Exception as e:
            queue_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # GET TICKETS FOR A QUEUE
    # GET /api/queues/<queue_id>/tickets
    # Query: ?status=all|pending|active|suspended|carried_over
    #        &priority=all|normal|high|urgent
    # ----------------------------------------------------------
    def get_tickets(self, queue_id):
        _, ticket_repo, _, _, _ = self._get_deps()

        status_filter   = request.args.get("status",   "all")
        priority_filter = request.args.get("priority", "all")

        tickets = ticket_repo.find_by_queue(int(queue_id))

        if status_filter != "all":
            tickets = [t for t in tickets if t.status == status_filter]
        if priority_filter != "all":
            tickets = [t for t in tickets if t.priority == priority_filter]

        return jsonify({
            "success": True,
            "tickets": [t.to_dict() for t in tickets],
        }), 200

    # ----------------------------------------------------------
    # DELETE TICKET
    # DELETE /api/tickets/<ticket_id>
    # ----------------------------------------------------------
    def delete_ticket(self, ticket_id):
        queue_repo, ticket_repo, _, schedule_repo, schedule_svc = self._get_deps()

        ticket = ticket_repo.find_by_id(int(ticket_id))
        if not ticket:
            return jsonify({"success": False, "message": "Ticket not found"}), 404

        queue_id   = ticket.queue_id
        service_id = ticket.service_id

        try:
            ticket_repo.delete(ticket)
            ticket_repo.flush()
            ticket_repo.reindex_positions(queue_id)

            # Recalculate estimates after deletion
            schedule  = schedule_repo.resolve_for_today(service_id)
            avg_dur   = schedule.avg_duration if schedule else 10
            remaining = ticket_repo.find_by_queue(queue_id)
            schedule_svc.recalculate_queue(remaining, avg_dur)

            ticket_repo.save()
            return jsonify({"success": True, "message": "Ticket deleted"}), 200
        except Exception as e:
            ticket_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # SET TICKET PRIORITY
    # PATCH /api/tickets/<ticket_id>/priority
    # Body: { priority: 'normal' | 'high' | 'urgent' }
    # ----------------------------------------------------------
    def set_priority(self, ticket_id):
        _, ticket_repo, _, _, _ = self._get_deps()

        data     = request.get_json()
        priority = data.get("priority", "").strip()

        if priority not in ticket_repo.VALID_PRIORITIES:
            return jsonify({"success": False, "message": f"Invalid priority. Must be one of {ticket_repo.VALID_PRIORITIES}"}), 400

        ticket = ticket_repo.find_by_id(int(ticket_id))
        if not ticket:
            return jsonify({"success": False, "message": "Ticket not found"}), 404

        try:
            ticket.priority = priority
            ticket_repo.save()
            return jsonify({"success": True, "ticket": ticket.to_dict()}), 200
        except Exception as e:
            ticket_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # SWAP TWO TICKETS
    # PATCH /api/tickets/swap
    # Body: { ticket_id_a: int, ticket_id_b: int }
    # ----------------------------------------------------------
    def swap_tickets(self):
        _, ticket_repo, _, schedule_repo, schedule_svc = self._get_deps()

        data        = request.get_json()
        ticket_id_a = data.get("ticket_id_a")
        ticket_id_b = data.get("ticket_id_b")

        if not ticket_id_a or not ticket_id_b:
            return jsonify({"success": False, "message": "ticket_id_a and ticket_id_b are required"}), 400

        ticket_a = ticket_repo.find_by_id(int(ticket_id_a))
        ticket_b = ticket_repo.find_by_id(int(ticket_id_b))

        if not ticket_a or not ticket_b:
            return jsonify({"success": False, "message": "One or both tickets not found"}), 404

        if ticket_a.queue_id != ticket_b.queue_id:
            return jsonify({"success": False, "message": "Tickets must be in the same queue to swap"}), 400

        try:
            # Swap positions
            ticket_a.position, ticket_b.position = ticket_b.position, ticket_a.position

            # Recalculate estimates after swap
            service_id = ticket_a.service_id
            schedule   = schedule_repo.resolve_for_today(service_id)
            avg_dur    = schedule.avg_duration if schedule else 10
            all_tickets = ticket_repo.find_by_queue(ticket_a.queue_id)
            schedule_svc.recalculate_queue(all_tickets, avg_dur)

            ticket_repo.save()
            return jsonify({
                "success":  True,
                "ticket_a": ticket_a.to_dict(),
                "ticket_b": ticket_b.to_dict(),
            }), 200
        except Exception as e:
            ticket_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # PUBLIC: JOIN QUEUE VIA QR LINK
    # POST /api/join/<join_token>
    # Body (optional): { customer_identifier: "phone or email" }
    # Called by the mobile app when a customer scans the QR code.
    # Issues a new ticket and returns it.
    # ----------------------------------------------------------
    def join_queue(self, join_token):
        queue_repo, ticket_repo, _, schedule_repo, schedule_svc = self._get_deps()

        queue = queue_repo.find_by_token(join_token)
        if not queue:
            return jsonify({"success": False, "message": "Invalid or expired QR code"}), 404

        data                = request.get_json(silent=True) or {}
        customer_identifier = data.get("customer_identifier", "").strip() or None

        # Resolve schedule for estimated time
        schedule = schedule_repo.resolve_for_today(queue.service_id)
        avg_dur  = schedule.avg_duration if schedule else 10

        try:
            position   = ticket_repo.next_position(queue.id)
            code_num   = ticket_repo.next_code_number(queue.id)
            code       = f"{queue.code}-{str(code_num).zfill(3)}"
            est_serve  = schedule_svc.compute_estimated_serve_at(position, avg_dur)

            ticket = ticket_repo.create(
                queue_id            = queue.id,
                service_id          = queue.service_id,
                code                = code,
                position            = position,
                customer_identifier = customer_identifier,
                estimated_serve_at  = est_serve,
            )
            ticket_repo.flush()

            # Check if this ticket exceeds closing time → carry over
            if schedule and schedule_svc.exceeds_closing_time(est_serve, schedule):
                from datetime import date
                ticket.status           = ticket_repo.STATUS_CARRIED_OVER
                ticket.carried_over_date = date.today()
                ticket.position         = None

            ticket_repo.save()
            return jsonify({
                "success": True,
                "ticket":  ticket.to_dict(),
                "queue":   queue.to_dict(current_app.config.get("BASE_URL", "")),
                "carried_over": ticket.status == ticket_repo.STATUS_CARRIED_OVER,
            }), 201

        except Exception as e:
            ticket_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500


# =============================================================
# ROUTE REGISTRATION
# =============================================================
_controller = QueueController()

queue_bp.add_url_rule("/queues",                    view_func=_controller.get_queues,     methods=["GET"])
queue_bp.add_url_rule("/queues",                    view_func=_controller.create_queue,   methods=["POST"])
queue_bp.add_url_rule("/queues/<int:queue_id>",     view_func=_controller.delete_queue,   methods=["DELETE"])
queue_bp.add_url_rule("/queues/<int:queue_id>/tickets", view_func=_controller.get_tickets, methods=["GET"])
queue_bp.add_url_rule("/tickets/<int:ticket_id>",   view_func=_controller.delete_ticket,  methods=["DELETE"])
queue_bp.add_url_rule("/tickets/<int:ticket_id>/priority", view_func=_controller.set_priority, methods=["PATCH"])
queue_bp.add_url_rule("/tickets/swap",              view_func=_controller.swap_tickets,   methods=["PATCH"])
queue_bp.add_url_rule("/join/<string:join_token>",  view_func=_controller.join_queue,     methods=["POST"])