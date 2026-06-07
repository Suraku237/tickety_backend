from flask import Blueprint, request, jsonify, current_app
from datetime import datetime, date
import re

from repositories.queue_repository    import QueueRepository
from repositories.ticket_repository   import TicketRepository
from repositories.admin_repository    import AdminRepository
from repositories.user_repository     import UserRepository
from repositories.schedule_repository import ScheduleRepository
from services.schedule_service        import ScheduleService
from services.notification_service    import NotificationService

queue_bp = Blueprint("queue", __name__)


# =============================================================
# QUEUE DEPENDENCIES (named dependency container)
# Replaces the previous positional `_get_deps()` tuple, which was
# fragile and caused a real bug in the mobile backend (a queue
# repository was unpacked into a `user_repo` slot and then used to
# look up users). Accessing dependencies by name removes that whole
# class of error.
# OOP Principle: Encapsulation + Dependency Injection
# =============================================================
class _QueueDeps:
    __slots__ = ("queue_repo", "ticket_repo", "admin_repo",
                 "user_repo", "schedule_repo", "schedule_svc", "notif_svc")

    def __init__(self):
        self.queue_repo    = QueueRepository()
        self.ticket_repo   = TicketRepository()
        self.admin_repo    = AdminRepository()
        self.user_repo     = UserRepository()
        self.schedule_repo = ScheduleRepository()
        self.schedule_svc  = ScheduleService()
        self.notif_svc     = NotificationService()


# =============================================================
# QUEUE CONTROLLER  (merged: web admin + mobile client)
# Responsibilities:
#   - CRUD for queues within a service
#   - CRUD for tickets within a queue
#   - Manual ("printed") ticket issuing for staff           [web]
#   - QR join endpoint - customer scans and gets a ticket   [mobile]
#   - Public queue preview before joining                   [mobile]
#   - User ticket lookup + "called" polling                 [mobile]
#   - Ticket actions: swap, set priority, delete
#   - Fires notifications on mutating actions               [web]
# OOP Principle: Single Responsibility, Dependency Injection
# =============================================================
class QueueController:

    def _deps(self) -> _QueueDeps:
        return _QueueDeps()

    def _get_service_id(self):
        """Extract service_id from request JSON or query string."""
        data = request.get_json(silent=True) or {}
        return data.get("service_id") or request.args.get("service_id")

    def _base_url(self) -> str:
        return current_app.config.get("BASE_URL", "https://tickety.app")

    # Priority ranking used to order waiting lists (urgent first).
    _PRIO_ORDER = {"urgent": 0, "high": 1, "normal": 2}

    def _prio_key(self, t):
        return (self._PRIO_ORDER.get(t.priority, 2),
                t.position if t.position is not None else 9999)

    # ----------------------------------------------------------
    # TICKET CODE from the INITIALS of the queue name + number.
    #   "Bill Payment" -> BP-001 ,  "Reception" -> RE-001
    # ----------------------------------------------------------
    def _ticket_code(self, queue, number: int) -> str:
        words = [w for w in re.split(r"\s+", (queue.name or "").strip()) if w]
        if not words:
            initials = (queue.code or "Q")[:2].upper()
        elif len(words) == 1:
            initials = words[0][:2].upper()
        else:
            initials = "".join(w[0] for w in words).upper()
        return f"{initials}-{str(number).zfill(3)}"

    # ----------------------------------------------------------
    # Shared helper: enrich a ticket dict for mobile consumers.
    # Stored status is the canonical lifecycle value ('pending'
    # while waiting). For the end-user app a waiting ticket reads
    # more naturally as "active", so we translate for DISPLAY only
    # without ever mutating the stored value.
    # ----------------------------------------------------------
    def _enrich_for_user(self, ticket, ticket_repo):
        queue          = ticket.queue
        queue_tickets  = ticket_repo.find_by_queue(queue.id) if queue else []
        total_in_queue = len([t for t in queue_tickets if t.position is not None])
        people_ahead   = len([
            t for t in queue_tickets
            if t.position is not None
            and ticket.position is not None
            and t.position < ticket.position
        ])
        estimated_minutes = 0
        if ticket.estimated_serve_at:
            diff = ticket.estimated_serve_at - datetime.now(ticket.estimated_serve_at.tzinfo)
            estimated_minutes = max(0, int(diff.total_seconds() / 60))

        return {
            **ticket.to_dict(),
            "status":            "active" if ticket.status == "pending" else ticket.status,
            "service_name":      queue.name if queue else "",
            "service_category":  (queue.service.name if queue and queue.service
                                  else queue.code if queue else ""),
            "guichet_number":    int(ticket.counter) if ticket.counter and ticket.counter.isdigit() else 0,
            "currently_serving": ticket.counter or "",
            "estimated_minutes": estimated_minutes,
            "people_ahead":      people_ahead,
            "total_in_queue":    total_in_queue,
        }

    # ----------------------------------------------------------
    # GET ALL QUEUES FOR A SERVICE        [web]
    # GET /api/queues?service_id=<id>
    # ----------------------------------------------------------
    def get_queues(self):
        d = self._deps()
        service_id = request.args.get("service_id")
        if not service_id:
            return jsonify({"success": False, "message": "service_id is required"}), 400
        queues = d.queue_repo.find_by_service(int(service_id))
        return jsonify({
            "success": True,
            "queues":  [q.to_dict(self._base_url()) for q in queues],
        }), 200

    # ----------------------------------------------------------
    # CREATE QUEUE                        [web]
    # POST /api/queues  Body: { service_id, name, code, color }
    # ----------------------------------------------------------
    def create_queue(self):
        d = self._deps()
        data       = request.get_json()
        service_id = data.get("service_id")
        name       = data.get("name", "").strip()
        color      = data.get("color", "#DC0F0F")

        if not service_id or not name:
            return jsonify({"success": False, "message": "service_id and name are required"}), 400

        # Code is no longer entered by the user. We derive a short internal
        # code from the queue name's initials and guarantee it's unique within
        # the service (so two services can never collide, and neither can two
        # queues in the same service). The customer-facing join link is a random
        # UUID generated automatically by the Queue model.
        base = self._queue_initials_for_code(name)
        code = base
        n = 1
        while d.queue_repo.find_by_code_and_service(code, int(service_id)):
            n += 1
            code = f"{base}{n}"

        try:
            queue = d.queue_repo.create(service_id=int(service_id), name=name, code=code, color=color)
            d.queue_repo.flush()
            d.queue_repo.save()
            d.notif_svc.queue_created(int(service_id), name, code)
            return jsonify({"success": True, "queue": queue.to_dict(self._base_url())}), 201
        except Exception as e:
            d.queue_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # Short internal code from a queue name's initials: "Bill Payment" -> "BP".
    def _queue_initials_for_code(self, name: str) -> str:
        words = [w for w in re.split(r"\s+", (name or "").strip()) if w]
        if not words:
            return "Q"
        if len(words) == 1:
            return words[0][:2].upper()
        return "".join(w[0] for w in words).upper()

    # ----------------------------------------------------------
    # DELETE QUEUE                        [web]
    # DELETE /api/queues/<queue_id>
    # ----------------------------------------------------------
    def delete_queue(self, queue_id):
        d = self._deps()
        queue = d.queue_repo.find_by_id(int(queue_id))
        if not queue:
            return jsonify({"success": False, "message": "Queue not found"}), 404

        service_id, name = queue.service_id, queue.name
        try:
            d.queue_repo.delete(queue)
            d.queue_repo.save()
            d.notif_svc.queue_deleted(service_id, name)
            return jsonify({"success": True, "message": "Queue deleted"}), 200
        except Exception as e:
            d.queue_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # GET TICKETS FOR A QUEUE             [web]
    # GET /api/queues/<queue_id>/tickets?status=&priority=
    # ----------------------------------------------------------
    def get_tickets(self, queue_id):
        d = self._deps()
        status_filter   = request.args.get("status",   "all")
        priority_filter = request.args.get("priority", "all")
        tickets = d.ticket_repo.find_by_queue(int(queue_id))
        if status_filter != "all":
            tickets = [t for t in tickets if t.status == status_filter]
        if priority_filter != "all":
            tickets = [t for t in tickets if t.priority == priority_filter]
        # Order so higher priority surfaces first, then arrival order.
        tickets = sorted(tickets, key=self._prio_key)
        return jsonify({"success": True, "tickets": [t.to_dict() for t in tickets]}), 200

    # ----------------------------------------------------------
    # GET TICKETS FOR A USER              [mobile]
    # GET /api/tickets?user_id=<id>&user_email=<email>
    # ----------------------------------------------------------
    def get_tickets_for_user(self):
        d = self._deps()
        user_id    = request.args.get("user_id")
        user_email = request.args.get("user_email")

        if user_id:
            user = d.user_repo.find_by_id(int(user_id))
            if not user:
                return jsonify({"success": False, "message": "User not found"}), 404
            user_email = user.email

        if not user_email:
            return jsonify({"success": False, "message": "user_id or user_email is required"}), 400

        # Normalise so the lookup matches regardless of how the email
        # was stored or sent.
        user_email = user_email.strip().lower()
        tickets    = d.ticket_repo.find_by_customer_identifier(user_email)
        result     = [self._enrich_for_user(t, d.ticket_repo) for t in tickets]
        return jsonify({"success": True, "tickets": result}), 200

    # ----------------------------------------------------------
    # GET SINGLE TICKET                   [mobile]
    # GET /api/tickets/<ticket_id>
    # ----------------------------------------------------------
    def get_ticket(self, ticket_id):
        d = self._deps()
        ticket = d.ticket_repo.find_by_id(int(ticket_id))
        if not ticket:
            return jsonify({"success": False, "message": "Ticket not found"}), 404
        return jsonify({"success": True, "ticket": self._enrich_for_user(ticket, d.ticket_repo)}), 200

    # ----------------------------------------------------------
    # ISSUE TICKET (manual / printed)     [web]
    # POST /api/queues/<queue_id>/issue   Body: { priority }
    # Creates a ticket tagged printed=True and returns its code for
    # the staff member to write on the physical ticket.
    # ----------------------------------------------------------
    def issue_ticket(self, queue_id):
        d = self._deps()
        queue = d.queue_repo.find_by_id(int(queue_id))
        if not queue:
            return jsonify({"success": False, "message": "Queue not found"}), 404

        data     = request.get_json(silent=True) or {}
        priority = data.get("priority", "normal")
        if priority not in d.ticket_repo.VALID_PRIORITIES:
            priority = "normal"

        service_id = queue.service_id
        schedule   = d.schedule_repo.resolve_for_today(service_id)
        avg_dur    = d.schedule_svc.effective_avg(d.ticket_repo, queue.id, schedule)

        try:
            position  = d.ticket_repo.next_position(queue.id)
            code_num  = d.ticket_repo.next_code_number(queue.id)
            code      = self._ticket_code(queue, code_num)
            est_serve = d.schedule_svc.compute_estimated_serve_at(position, avg_dur)

            ticket = d.ticket_repo.create(
                queue_id           = queue.id,
                service_id         = service_id,
                code               = code,
                position           = position,
                estimated_serve_at = est_serve,
            )
            ticket.priority = priority
            ticket.printed  = True
            d.ticket_repo.flush()

            if schedule and d.schedule_svc.exceeds_closing_time(est_serve, schedule):
                ticket.status            = d.ticket_repo.STATUS_CARRIED_OVER
                ticket.carried_over_date = date.today()
                ticket.position          = None

            d.ticket_repo.save()
            d.notif_svc.ticket_issued(service_id, code, queue.name, printed=True)

            return jsonify({
                "success":      True,
                "ticket":       ticket.to_dict(),
                "queue":        queue.to_dict(self._base_url()),
                "carried_over": ticket.status == d.ticket_repo.STATUS_CARRIED_OVER,
            }), 201
        except Exception as e:
            d.ticket_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # DELETE TICKET                       [web + mobile]
    # DELETE /api/tickets/<ticket_id>
    # ----------------------------------------------------------
    def delete_ticket(self, ticket_id):
        d = self._deps()
        ticket = d.ticket_repo.find_by_id(int(ticket_id))
        if not ticket:
            return jsonify({"success": False, "message": "Ticket not found"}), 404

        queue_id   = ticket.queue_id
        service_id = ticket.service_id
        try:
            d.ticket_repo.delete(ticket)
            d.ticket_repo.flush()
            d.ticket_repo.reindex_positions(queue_id)
            schedule  = d.schedule_repo.resolve_for_today(service_id)
            avg_dur   = d.schedule_svc.effective_avg(d.ticket_repo, queue_id, schedule)
            remaining = d.ticket_repo.find_by_queue(queue_id)
            d.schedule_svc.recalculate_queue(remaining, avg_dur)
            d.ticket_repo.save()
            return jsonify({
                "success": True,
                "message": "Ticket deleted",
                "event":   "ticket_left_queue",   # mobile can subscribe to this
            }), 200
        except Exception as e:
            d.ticket_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # TICKET "CALLED" CHECK               [mobile]
    # GET /api/tickets/<ticket_id>/called
    # Mobile polls this to trigger the alarm sound when the
    # ticket reaches the counter (active + position 0).
    # ----------------------------------------------------------
    def check_called(self, ticket_id):
        d = self._deps()
        ticket = d.ticket_repo.find_by_id(int(ticket_id))
        if not ticket:
            return jsonify({
                "success": False,
                "called":  False,
                "deleted": True,
                "message": "Ticket not found",
            }), 200   # 200 so the client can handle gracefully

        is_called = (ticket.status == d.ticket_repo.STATUS_ACTIVE and ticket.position == 0)
        return jsonify({
            "success":  True,
            "called":   is_called,
            "deleted":  False,
            "status":   ticket.status,
            "counter":  ticket.counter or "",
            "position": ticket.position,
        }), 200

    # ----------------------------------------------------------
    # SET TICKET PRIORITY                 [web]
    # PATCH /api/tickets/<ticket_id>/priority   Body: { priority }
    # ----------------------------------------------------------
    def set_priority(self, ticket_id):
        d = self._deps()
        data     = request.get_json()
        priority = data.get("priority", "").strip()
        if priority not in d.ticket_repo.VALID_PRIORITIES:
            return jsonify({"success": False,
                            "message": f"Invalid priority. Must be one of {d.ticket_repo.VALID_PRIORITIES}"}), 400
        ticket = d.ticket_repo.find_by_id(int(ticket_id))
        if not ticket:
            return jsonify({"success": False, "message": "Ticket not found"}), 404
        try:
            ticket.priority = priority
            d.ticket_repo.save()
            return jsonify({"success": True, "ticket": ticket.to_dict()}), 200
        except Exception as e:
            d.ticket_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # SWAP TWO TICKETS                    [web]
    # PATCH /api/tickets/swap   Body: { ticket_id_a, ticket_id_b }
    # ----------------------------------------------------------
    def swap_tickets(self):
        d = self._deps()
        data        = request.get_json()
        ticket_id_a = data.get("ticket_id_a")
        ticket_id_b = data.get("ticket_id_b")
        if not ticket_id_a or not ticket_id_b:
            return jsonify({"success": False, "message": "ticket_id_a and ticket_id_b are required"}), 400

        ticket_a = d.ticket_repo.find_by_id(int(ticket_id_a))
        ticket_b = d.ticket_repo.find_by_id(int(ticket_id_b))
        if not ticket_a or not ticket_b:
            return jsonify({"success": False, "message": "One or both tickets not found"}), 404
        if ticket_a.queue_id != ticket_b.queue_id:
            return jsonify({"success": False, "message": "Tickets must be in the same queue to swap"}), 400

        try:
            ticket_a.position, ticket_b.position = ticket_b.position, ticket_a.position
            service_id  = ticket_a.service_id
            schedule    = d.schedule_repo.resolve_for_today(service_id)
            avg_dur     = d.schedule_svc.effective_avg(d.ticket_repo, ticket_a.queue_id, schedule)
            all_tickets = d.ticket_repo.find_by_queue(ticket_a.queue_id)
            d.schedule_svc.recalculate_queue(all_tickets, avg_dur)
            d.ticket_repo.save()
            return jsonify({
                "success":  True,
                "ticket_a": ticket_a.to_dict(),
                "ticket_b": ticket_b.to_dict(),
            }), 200
        except Exception as e:
            d.ticket_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # PUBLIC: PREVIEW QUEUE VIA JOIN TOKEN (no ticket issued)  [mobile]
    # GET /api/join/<join_token>
    # Shown after a QR scan / link open, before the user confirms.
    # Only tokens that exist in our queues table (UUIDs) are accepted.
    # ----------------------------------------------------------
    def preview_queue(self, join_token):
        d = self._deps()
        queue = d.queue_repo.find_by_token(join_token)
        if not queue:
            return jsonify({
                "success": False,
                "message": "Invalid QR code or link. Only official Tickety QR codes and links are accepted.",
            }), 404
        return jsonify({
            "success": True,
            "queue":   queue.to_dict(self._base_url()),
            "service": queue.service.to_dict() if queue.service else {},
            "active":  queue.active_count(),
            "pending": queue.pending_count(),
        }), 200

    # ----------------------------------------------------------
    # PUBLIC: JOIN QUEUE VIA QR / URL     [mobile + web]
    # POST /api/join/<join_token>   Body: { customer_identifier }
    # The token MUST exist in the Queue table (UUID generated by
    # this backend). Random / external tokens get a 404.
    # New tickets are created PENDING - the shared counter lifecycle
    # promotes them to ACTIVE when an agent calls them. (The mobile
    # app translates pending->"active" for display in _enrich_for_user.)
    # ----------------------------------------------------------
    def join_queue(self, join_token):
        d = self._deps()
        queue = d.queue_repo.find_by_token(join_token)
        if not queue:
            return jsonify({
                "success": False,
                "message": "Invalid QR code or link. Only official Tickety QR codes and links are accepted.",
            }), 404

        data                = request.get_json(silent=True) or {}
        customer_identifier = (data.get("customer_identifier") or "").strip().lower() or None
        schedule            = d.schedule_repo.resolve_for_today(queue.service_id)
        avg_dur             = d.schedule_svc.effective_avg(d.ticket_repo, queue.id, schedule)

        try:
            position  = d.ticket_repo.next_position(queue.id)
            code_num  = d.ticket_repo.next_code_number(queue.id)
            code      = self._ticket_code(queue, code_num)
            est_serve = d.schedule_svc.compute_estimated_serve_at(position, avg_dur)

            ticket = d.ticket_repo.create(
                queue_id            = queue.id,
                service_id          = queue.service_id,
                code                = code,
                position            = position,
                customer_identifier = customer_identifier,
                estimated_serve_at  = est_serve,
            )
            d.ticket_repo.flush()

            # Carry over if the service will have closed by serve time.
            if schedule and d.schedule_svc.exceeds_closing_time(est_serve, schedule):
                ticket.status            = d.ticket_repo.STATUS_CARRIED_OVER
                ticket.carried_over_date = date.today()
                ticket.position          = None

            d.ticket_repo.save()
            d.notif_svc.ticket_issued(queue.service_id, code, queue.name, printed=False)

            return jsonify({
                "success":      True,
                "ticket":       ticket.to_dict(),
                "queue":        queue.to_dict(self._base_url()),
                "service":      queue.service.to_dict() if queue.service else {},
                "carried_over": ticket.status == d.ticket_repo.STATUS_CARRIED_OVER,
            }), 201
        except Exception as e:
            d.ticket_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500


# =============================================================
# ROUTE REGISTRATION  (union of web + mobile endpoints)
# =============================================================
_controller = QueueController()

# Queue management [web]
queue_bp.add_url_rule("/queues",                          view_func=_controller.get_queues,          methods=["GET"])
queue_bp.add_url_rule("/queues",                          view_func=_controller.create_queue,        methods=["POST"])
queue_bp.add_url_rule("/queues/<int:queue_id>",           view_func=_controller.delete_queue,        methods=["DELETE"])
queue_bp.add_url_rule("/queues/<int:queue_id>/tickets",   view_func=_controller.get_tickets,         methods=["GET"])
queue_bp.add_url_rule("/queues/<int:queue_id>/issue",     view_func=_controller.issue_ticket,        methods=["POST"])

# Ticket endpoints consumed by the mobile app
queue_bp.add_url_rule("/tickets",                         view_func=_controller.get_tickets_for_user, methods=["GET"])
queue_bp.add_url_rule("/tickets/<int:ticket_id>",         view_func=_controller.get_ticket,           methods=["GET"])
queue_bp.add_url_rule("/tickets/<int:ticket_id>",         view_func=_controller.delete_ticket,        methods=["DELETE"])
queue_bp.add_url_rule("/tickets/<int:ticket_id>/called",  view_func=_controller.check_called,         methods=["GET"])
queue_bp.add_url_rule("/tickets/<int:ticket_id>/priority",view_func=_controller.set_priority,         methods=["PATCH"])
queue_bp.add_url_rule("/tickets/swap",                    view_func=_controller.swap_tickets,         methods=["PATCH"])

# QR / URL join endpoints - join_token validated against the DB
queue_bp.add_url_rule("/join/<string:join_token>",        view_func=_controller.preview_queue,        methods=["GET"])
queue_bp.add_url_rule("/join/<string:join_token>",        view_func=_controller.join_queue,           methods=["POST"])