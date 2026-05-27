from flask import Blueprint, request, jsonify
from repositories.ticket_repository   import TicketRepository
from repositories.queue_repository    import QueueRepository
from repositories.schedule_repository import ScheduleRepository
from services.schedule_service        import ScheduleService
from datetime import date

counter_bp = Blueprint("counter", __name__)

# =============================================================
# COUNTER CONTROLLER
# Responsibilities:
#   - Get tickets filtered by the queues an agent is serving
#   - Terminate, suspend, reactivate tickets
#   - Call next ticket — stamps counter_name on the ticket
#   - Return closing time warning in every response
#
# AGENT FLOW:
#   1. Agent opens Counter page
#   2. Agent selects which queue(s) they are serving + their
#      counter name/number (e.g. "Counter A", "Guichet 3")
#   3. All endpoints filter by those queue_ids
#   4. When a ticket is called, counter_name is stamped on it
#
# OOP Principle: Single Responsibility, Dependency Injection
# =============================================================
class CounterController:

    def _get_deps(self):
        return (
            TicketRepository(),
            QueueRepository(),
            ScheduleRepository(),
            ScheduleService(),
        )

    def _parse_queue_ids(self, raw) -> list[int]:
        """
        Parse queue_ids from either a comma-separated query string
        or a JSON list in the request body.
        Returns an empty list if not provided (means: all queues).
        """
        if not raw:
            return []
        if isinstance(raw, list):
            return [int(x) for x in raw if str(x).isdigit()]
        # comma-separated string from query param
        return [int(x.strip()) for x in str(raw).split(',') if x.strip().isdigit()]

    def _closing_warning(self, ticket_repo, schedule_repo, schedule_svc, service_id):
        schedule  = schedule_repo.resolve_for_today(service_id)
        if not schedule:
            return {"warning": False}
        tickets   = ticket_repo.find_by_service(service_id)
        exceeding = [
            t for t in tickets
            if t.estimated_serve_at
            and schedule_svc.exceeds_closing_time(t.estimated_serve_at, schedule)
        ]
        return schedule_svc.closing_warning_payload(schedule, exceeding)

    # ----------------------------------------------------------
    # GET COUNTER TICKETS
    # GET /api/counter/tickets?service_id=<id>&queue_ids=1,2,3&counter_name=A
    #
    # queue_ids (optional, comma-separated) — if omitted, returns
    #   all tickets for the service (manager/boss overview)
    # counter_name (optional) — used for display only in response
    # ----------------------------------------------------------
    def get_tickets(self):
        ticket_repo, queue_repo, schedule_repo, schedule_svc = self._get_deps()

        service_id   = request.args.get("service_id")
        queue_ids_raw= request.args.get("queue_ids", "")
        counter_name = request.args.get("counter_name", "")

        if not service_id:
            return jsonify({"success": False, "message": "service_id is required"}), 400

        sid       = int(service_id)
        queue_ids = self._parse_queue_ids(queue_ids_raw)

        # Fetch all active/pending/suspended tickets for the service
        all_tickets = ticket_repo.find_by_service(sid)

        # Filter by selected queues if specified
        if queue_ids:
            all_tickets = [t for t in all_tickets if t.queue_id in queue_ids]

        # Enrich tickets with queue name for display
        queue_cache = {}
        for t in all_tickets:
            if t.queue_id not in queue_cache:
                q = queue_repo.find_by_id(t.queue_id)
                queue_cache[t.queue_id] = q.name if q else '—'

        def enrich(t):
            d = t.to_dict()
            d['queue_name'] = queue_cache.get(t.queue_id, '—')
            return d

        serving   = next(
            (t for t in all_tickets
             if t.status == ticket_repo.STATUS_ACTIVE and t.position == 0),
            None
        )
        waiting   = sorted(
            [t for t in all_tickets if t.status == ticket_repo.STATUS_PENDING],
            key=lambda x: x.position if x.position is not None else 9999
        )
        suspended = [t for t in all_tickets if t.status == ticket_repo.STATUS_SUSPENDED]

        warning = self._closing_warning(ticket_repo, schedule_repo, schedule_svc, sid)

        return jsonify({
            "success":         True,
            "counter_name":    counter_name,
            "serving":         enrich(serving)    if serving   else None,
            "waiting":         [enrich(t) for t in waiting],
            "suspended":       [enrich(t) for t in suspended],
            "closing_warning": warning,
        }), 200

    # ----------------------------------------------------------
    # TERMINATE TICKET
    # PATCH /api/counter/tickets/<ticket_id>/terminate
    # Body: { counter_name (optional) }
    # Auto-promotes next pending ticket in the SAME queue.
    # ----------------------------------------------------------
    def terminate(self, ticket_id):
        ticket_repo, queue_repo, schedule_repo, schedule_svc = self._get_deps()

        ticket = ticket_repo.find_by_id(int(ticket_id))
        if not ticket:
            return jsonify({"success": False, "message": "Ticket not found"}), 404

        data         = request.get_json(silent=True) or {}
        counter_name = data.get("counter_name", ticket.counter or "")
        service_id   = ticket.service_id
        queue_id     = ticket.queue_id

        try:
            ticket.status   = ticket_repo.STATUS_SERVED
            ticket.position = None
            ticket_repo.flush()

            ticket_repo.reindex_positions(queue_id)

            # Promote next pending ticket in the same queue
            remaining = ticket_repo.find_by_queue(queue_id)
            next_up   = next(
                (t for t in remaining if t.status == ticket_repo.STATUS_PENDING),
                None
            )
            if next_up:
                next_up.status   = ticket_repo.STATUS_ACTIVE
                next_up.position = 0
                next_up.counter  = counter_name  # stamp counter on the promoted ticket

            # Recalculate estimates
            schedule = schedule_repo.resolve_for_today(service_id)
            avg_dur  = schedule.avg_duration if schedule else 10
            schedule_svc.recalculate_queue(remaining, avg_dur)

            ticket_repo.save()

            warning = self._closing_warning(ticket_repo, schedule_repo, schedule_svc, service_id)
            return jsonify({
                "success":         True,
                "message":         "Ticket terminated",
                "next_ticket":     next_up.to_dict() if next_up else None,
                "closing_warning": warning,
            }), 200

        except Exception as e:
            ticket_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # SUSPEND TICKET
    # PATCH /api/counter/tickets/<ticket_id>/suspend
    # ----------------------------------------------------------
    def suspend(self, ticket_id):
        ticket_repo, queue_repo, schedule_repo, schedule_svc = self._get_deps()

        ticket = ticket_repo.find_by_id(int(ticket_id))
        if not ticket:
            return jsonify({"success": False, "message": "Ticket not found"}), 404

        service_id = ticket.service_id
        queue_id   = ticket.queue_id

        try:
            ticket.status   = ticket_repo.STATUS_SUSPENDED
            ticket.position = None
            ticket_repo.flush()

            ticket_repo.reindex_positions(queue_id)
            schedule  = schedule_repo.resolve_for_today(service_id)
            avg_dur   = schedule.avg_duration if schedule else 10
            remaining = ticket_repo.find_by_queue(queue_id)
            schedule_svc.recalculate_queue(remaining, avg_dur)

            ticket_repo.save()
            warning = self._closing_warning(ticket_repo, schedule_repo, schedule_svc, service_id)
            return jsonify({
                "success":         True,
                "message":         "Ticket suspended",
                "closing_warning": warning,
            }), 200

        except Exception as e:
            ticket_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # REACTIVATE TICKET
    # PATCH /api/counter/tickets/<ticket_id>/reactivate
    # ----------------------------------------------------------
    def reactivate(self, ticket_id):
        ticket_repo, queue_repo, schedule_repo, schedule_svc = self._get_deps()

        ticket = ticket_repo.find_by_id(int(ticket_id))
        if not ticket:
            return jsonify({"success": False, "message": "Ticket not found"}), 404

        if ticket.status != ticket_repo.STATUS_SUSPENDED:
            return jsonify({"success": False,
                            "message": "Only suspended tickets can be reactivated"}), 400

        service_id = ticket.service_id
        queue_id   = ticket.queue_id

        try:
            next_pos        = ticket_repo.next_position(queue_id)
            ticket.status   = ticket_repo.STATUS_PENDING
            ticket.position = next_pos
            ticket_repo.flush()

            schedule  = schedule_repo.resolve_for_today(service_id)
            avg_dur   = schedule.avg_duration if schedule else 10
            remaining = ticket_repo.find_by_queue(queue_id)
            schedule_svc.recalculate_queue(remaining, avg_dur)

            # Carry over if now exceeds closing time
            if schedule and ticket.estimated_serve_at:
                if schedule_svc.exceeds_closing_time(ticket.estimated_serve_at, schedule):
                    ticket.status            = ticket_repo.STATUS_CARRIED_OVER
                    ticket.position          = None
                    ticket.carried_over_date = date.today()

            ticket_repo.save()
            warning = self._closing_warning(ticket_repo, schedule_repo, schedule_svc, service_id)
            return jsonify({
                "success":         True,
                "ticket":          ticket.to_dict(),
                "carried_over":    ticket.status == ticket_repo.STATUS_CARRIED_OVER,
                "closing_warning": warning,
            }), 200

        except Exception as e:
            ticket_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # CALL NEXT
    # PATCH /api/counter/call-next
    # Body: { service_id, queue_ids (list), counter_name }
    #
    # Promotes the next PENDING ticket from one of the selected
    # queues. Counter name is stamped on the ticket.
    # Priority order: urgent first, then high, then normal,
    # then by position within the selected queues.
    # ----------------------------------------------------------
    def call_next(self):
        ticket_repo, queue_repo, schedule_repo, schedule_svc = self._get_deps()

        data         = request.get_json(silent=True) or {}
        service_id   = data.get("service_id") or request.args.get("service_id")
        queue_ids    = self._parse_queue_ids(data.get("queue_ids", []))
        counter_name = data.get("counter_name", "").strip()

        if not service_id:
            return jsonify({"success": False, "message": "service_id is required"}), 400

        sid     = int(service_id)
        tickets = ticket_repo.find_by_service(sid)

        # Filter by selected queues
        if queue_ids:
            tickets = [t for t in tickets if t.queue_id in queue_ids]

        # Priority ordering: urgent > high > normal, then by position
        PRIO_ORDER = {'urgent': 0, 'high': 1, 'normal': 2}
        pending = sorted(
            [t for t in tickets if t.status == ticket_repo.STATUS_PENDING],
            key=lambda t: (
                PRIO_ORDER.get(t.priority, 2),
                t.position if t.position is not None else 9999
            )
        )

        if not pending:
            return jsonify({"success": False, "message": "No pending tickets in the selected queues"}), 404

        next_ticket = pending[0]

        try:
            next_ticket.status   = ticket_repo.STATUS_ACTIVE
            next_ticket.position = 0
            next_ticket.counter  = counter_name  # stamp counter name on ticket

            # Reindex the queue this ticket came from
            ticket_repo.reindex_positions(next_ticket.queue_id)

            schedule  = schedule_repo.resolve_for_today(sid)
            avg_dur   = schedule.avg_duration if schedule else 10
            remaining = ticket_repo.find_by_service(sid)
            schedule_svc.recalculate_queue(remaining, avg_dur)

            ticket_repo.save()
            warning = self._closing_warning(ticket_repo, schedule_repo, schedule_svc, sid)

            # Enrich with queue name
            q = queue_repo.find_by_id(next_ticket.queue_id)
            ticket_dict = next_ticket.to_dict()
            ticket_dict['queue_name'] = q.name if q else '—'

            return jsonify({
                "success":         True,
                "ticket":          ticket_dict,
                "closing_warning": warning,
            }), 200

        except Exception as e:
            ticket_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # GET CARRIED OVER TICKETS
    # GET /api/counter/carried-over?service_id=<id>
    # ----------------------------------------------------------
    def get_carried_over(self):
        ticket_repo, _, _, _ = self._get_deps()

        service_id = request.args.get("service_id")
        if not service_id:
            return jsonify({"success": False, "message": "service_id is required"}), 400

        tickets = ticket_repo.find_carried_over(int(service_id))
        return jsonify({
            "success": True,
            "tickets": [t.to_dict() for t in tickets],
            "count":   len(tickets),
        }), 200


# =============================================================
# ROUTE REGISTRATION
# =============================================================
_controller = CounterController()

counter_bp.add_url_rule("/counter/tickets",                           view_func=_controller.get_tickets,     methods=["GET"])
counter_bp.add_url_rule("/counter/tickets/<int:ticket_id>/terminate", view_func=_controller.terminate,       methods=["PATCH"])
counter_bp.add_url_rule("/counter/tickets/<int:ticket_id>/suspend",   view_func=_controller.suspend,         methods=["PATCH"])
counter_bp.add_url_rule("/counter/tickets/<int:ticket_id>/reactivate",view_func=_controller.reactivate,      methods=["PATCH"])
counter_bp.add_url_rule("/counter/call-next",                         view_func=_controller.call_next,       methods=["PATCH"])
counter_bp.add_url_rule("/counter/carried-over",                      view_func=_controller.get_carried_over,methods=["GET"])