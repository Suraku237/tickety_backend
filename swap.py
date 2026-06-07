from flask import Blueprint, request, jsonify
from models import db, Ticket, SwapRequest
from repositories.ticket_repository   import TicketRepository
from repositories.schedule_repository import ScheduleRepository
from services.schedule_service        import ScheduleService
from datetime import datetime, timezone

swap_bp = Blueprint("swap", __name__)

# =============================================================
# SWAP CONTROLLER
# Responsibilities:
#   - Customer requests a swap with any ticket in the same service
#   - Target customer accepts or rejects the pending request
#   - On accept: atomically swap the two ticket positions and
#     recalculate ETA for the whole queue
#   - Only one pending request is allowed per (requester, target) pair
#   - Both tickets must be pending/active and in the same service
# OOP Principle: Single Responsibility, Dependency Injection
# =============================================================
class SwapController:

    def _get_deps(self):
        return (
            TicketRepository(),
            ScheduleRepository(),
            ScheduleService(),
        )

    # ----------------------------------------------------------
    # LIST AVAILABLE TICKETS TO SWAP WITH
    # GET /api/swap/available?requester_ticket_id=<id>
    #
    # Returns all swappable tickets in the same service as the
    # requester's ticket, excluding:
    #   - the requester's own ticket
    #   - already-served or carried-over tickets
    #   - tickets the requester already has a pending request with
    # ----------------------------------------------------------
    def list_available(self):
        ticket_repo, _, _ = self._get_deps()

        requester_ticket_id = request.args.get("requester_ticket_id")
        if not requester_ticket_id:
            return jsonify({"success": False, "message": "requester_ticket_id is required"}), 400

        requester = ticket_repo.find_by_id(int(requester_ticket_id))
        if not requester:
            return jsonify({"success": False, "message": "Ticket not found"}), 404

        # Only pending or active tickets can request swaps
        if requester.status not in {
            ticket_repo.STATUS_PENDING,
            ticket_repo.STATUS_ACTIVE,
        }:
            return jsonify({
                "success": False,
                "message": "Only pending or active tickets can request swaps",
            }), 400

        # Fetch swappable tickets in the SAME QUEUE as the requester.
        # Position is meaningful only within a queue, so swaps must be
        # intra-queue. The currently-served ticket (active, position 0)
        # is excluded — you cannot swap with someone already at the counter.
        service_tickets = (
            Ticket.query
            .filter_by(queue_id=requester.queue_id)
            .filter(Ticket.status.in_([
                ticket_repo.STATUS_PENDING,
                ticket_repo.STATUS_ACTIVE,
            ]))
            .filter(Ticket.id != requester.id)
            .filter(db.or_(Ticket.status != ticket_repo.STATUS_ACTIVE,
                           Ticket.position != 0))
            .order_by(Ticket.position.asc())
            .all()
        )

        # Find existing pending requests from this requester
        existing_pending_target_ids = {
            sr.target_ticket_id
            for sr in SwapRequest.query
            .filter_by(
                requester_ticket_id=requester.id,
                status=SwapRequest.STATUS_PENDING,
            )
            .all()
        }

        result = []
        for t in service_tickets:
            result.append({
                **t.to_dict(),
                "has_pending_request": t.id in existing_pending_target_ids,
            })

        return jsonify({
            "success":           True,
            "requester_ticket":  requester.to_dict(),
            "available_tickets": result,
        }), 200

    # ----------------------------------------------------------
    # REQUEST A SWAP
    # POST /api/swap/request
    # Body: { requester_ticket_id, target_ticket_id }
    #
    # Creates a SwapRequest row with status='pending'.
    # Guards:
    #   - Same service
    #   - Both tickets in a swappable status
    #   - No duplicate pending request for the same pair
    # ----------------------------------------------------------
    def request_swap(self):
        ticket_repo, _, _ = self._get_deps()

        data                 = request.get_json()
        requester_ticket_id  = data.get("requester_ticket_id")
        target_ticket_id     = data.get("target_ticket_id")

        if not requester_ticket_id or not target_ticket_id:
            return jsonify({
                "success": False,
                "message": "requester_ticket_id and target_ticket_id are required",
            }), 400

        if int(requester_ticket_id) == int(target_ticket_id):
            return jsonify({
                "success": False,
                "message": "A ticket cannot swap with itself",
            }), 400

        requester = ticket_repo.find_by_id(int(requester_ticket_id))
        target    = ticket_repo.find_by_id(int(target_ticket_id))

        if not requester:
            return jsonify({"success": False, "message": "Requester ticket not found"}), 404
        if not target:
            return jsonify({"success": False, "message": "Target ticket not found"}), 404

        # Must be in the same QUEUE (position only has meaning within a queue)
        if requester.queue_id != target.queue_id:
            return jsonify({
                "success": False,
                "message": "Both tickets must belong to the same queue",
            }), 400

        # Cannot swap with the ticket currently being served
        if target.status == ticket_repo.STATUS_ACTIVE and target.position == 0:
            return jsonify({
                "success": False,
                "message": "That ticket is currently being served and cannot be swapped",
            }), 400

        # Both must be in a swappable state
        swappable = {ticket_repo.STATUS_PENDING, ticket_repo.STATUS_ACTIVE}
        if requester.status not in swappable:
            return jsonify({
                "success": False,
                "message": "Your ticket is not in a swappable state",
            }), 400
        if target.status not in swappable:
            return jsonify({
                "success": False,
                "message": "The target ticket is not in a swappable state",
            }), 400

        # Check for duplicate pending request
        existing = SwapRequest.query.filter_by(
            requester_ticket_id = requester.id,
            target_ticket_id    = target.id,
            status              = SwapRequest.STATUS_PENDING,
        ).first()
        if existing:
            return jsonify({
                "success": False,
                "message": "You already have a pending swap request with that ticket",
            }), 400

        try:
            swap = SwapRequest(
                service_id          = requester.service_id,
                requester_ticket_id = requester.id,
                target_ticket_id    = target.id,
                status              = SwapRequest.STATUS_PENDING,
            )
            db.session.add(swap)
            db.session.commit()

            return jsonify({
                "success":      True,
                "message":      f"Swap request sent to ticket {target.code}",
                "swap_request": swap.to_dict(),
            }), 201

        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # GET INCOMING SWAP REQUESTS FOR A TICKET
    # GET /api/swap/incoming?target_ticket_id=<id>
    #
    # Used by the mobile app to poll/display pending incoming
    # requests so the target user can accept or reject them.
    # ----------------------------------------------------------
    def get_incoming(self):
        target_ticket_id = request.args.get("target_ticket_id")
        if not target_ticket_id:
            return jsonify({"success": False, "message": "target_ticket_id is required"}), 400

        requests = (
            SwapRequest.query
            .filter_by(
                target_ticket_id = int(target_ticket_id),
                status           = SwapRequest.STATUS_PENDING,
            )
            .order_by(SwapRequest.created_at.desc())
            .all()
        )

        result = []
        for sr in requests:
            req_ticket = sr.requester_ticket
            result.append({
                **sr.to_dict(),
                "requester_code":     req_ticket.code if req_ticket else "",
                "requester_position": req_ticket.position if req_ticket else None,
            })

        return jsonify({
            "success":  True,
            "incoming": result,
        }), 200

    # ----------------------------------------------------------
    # GET OUTGOING SWAP REQUESTS FOR A TICKET
    # GET /api/swap/outgoing?requester_ticket_id=<id>
    #
    # Used by the mobile app so a customer can see the status
    # of their own swap requests (pending / accepted / rejected).
    # ----------------------------------------------------------
    def get_outgoing(self):
        requester_ticket_id = request.args.get("requester_ticket_id")
        if not requester_ticket_id:
            return jsonify({"success": False, "message": "requester_ticket_id is required"}), 400

        requests = (
            SwapRequest.query
            .filter_by(requester_ticket_id=int(requester_ticket_id))
            .order_by(SwapRequest.created_at.desc())
            .all()
        )

        result = []
        for sr in requests:
            tgt_ticket = sr.target_ticket
            result.append({
                **sr.to_dict(),
                "target_code":     tgt_ticket.code if tgt_ticket else "",
                "target_position": tgt_ticket.position if tgt_ticket else None,
            })

        return jsonify({
            "success":  True,
            "outgoing": result,
        }), 200

    # ----------------------------------------------------------
    # RESPOND TO A SWAP REQUEST (accept or reject)
    # POST /api/swap/<swap_id>/respond
    # Body: { action: 'accept' | 'reject' }
    #
    # On accept:
    #   1. Atomically swap positions of the two tickets
    #   2. Recalculate ETAs for the whole queue
    #   3. Cancel all other pending requests between the same pair
    # On reject: simply mark rejected.
    # ----------------------------------------------------------
    def respond(self, swap_id):
        ticket_repo, schedule_repo, schedule_svc = self._get_deps()

        data   = request.get_json()
        action = data.get("action", "").strip().lower()

        if action not in {"accept", "reject"}:
            return jsonify({
                "success": False,
                "message": "action must be 'accept' or 'reject'",
            }), 400

        swap = SwapRequest.query.get(int(swap_id))
        if not swap:
            return jsonify({"success": False, "message": "Swap request not found"}), 404

        if not swap.is_pending():
            return jsonify({
                "success": False,
                "message": f"This swap request is already {swap.status}",
            }), 400

        requester = ticket_repo.find_by_id(swap.requester_ticket_id)
        target    = ticket_repo.find_by_id(swap.target_ticket_id)

        if not requester or not target:
            return jsonify({"success": False, "message": "One or both tickets no longer exist"}), 404

        try:
            now = datetime.now(timezone.utc)

            if action == "reject":
                swap.status       = SwapRequest.STATUS_REJECTED
                swap.responded_at = now
                db.session.commit()
                return jsonify({
                    "success": True,
                    "message": "Swap request rejected",
                    "swap_request": swap.to_dict(),
                }), 200

            # --- ACCEPT ---
            # Guard: both tickets still swappable
            swappable = {
                ticket_repo.STATUS_PENDING,
                ticket_repo.STATUS_ACTIVE,
            }
            if requester.status not in swappable or target.status not in swappable:
                swap.status       = SwapRequest.STATUS_EXPIRED
                swap.responded_at = now
                db.session.commit()
                return jsonify({
                    "success": False,
                    "message": "One or both tickets are no longer in a swappable state",
                }), 400

            # Atomically swap positions
            requester.position, target.position = target.position, requester.position

            # Recalculate ETAs for the service
            service_id = requester.service_id
            schedule   = schedule_repo.resolve_for_today(service_id)

            # Both tickets are in the same queue now; recalc that queue
            # using the rolling-average duration.
            affected_queue_ids = {requester.queue_id, target.queue_id}
            for qid in affected_queue_ids:
                avg_dur       = schedule_svc.effective_avg(ticket_repo, qid, schedule)
                queue_tickets = ticket_repo.find_by_queue(qid)
                schedule_svc.recalculate_queue(queue_tickets, avg_dur)

            # Mark this request accepted
            swap.status       = SwapRequest.STATUS_ACCEPTED
            swap.responded_at = now

            # Cancel any other pending requests between these two tickets
            # in either direction to avoid ghost requests
            SwapRequest.query.filter(
                SwapRequest.status == SwapRequest.STATUS_PENDING,
                db.or_(
                    db.and_(
                        SwapRequest.requester_ticket_id == requester.id,
                        SwapRequest.target_ticket_id    == target.id,
                    ),
                    db.and_(
                        SwapRequest.requester_ticket_id == target.id,
                        SwapRequest.target_ticket_id    == requester.id,
                    ),
                ),
                SwapRequest.id != swap.id,
            ).update(
                {"status": SwapRequest.STATUS_EXPIRED, "responded_at": now},
                synchronize_session=False,
            )

            db.session.commit()

            return jsonify({
                "success":      True,
                "message":      "Swap accepted! Positions have been exchanged.",
                "swap_request": swap.to_dict(),
                "requester":    requester.to_dict(),
                "target":       target.to_dict(),
            }), 200

        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # CANCEL A SWAP REQUEST (by the requester)
    # DELETE /api/swap/<swap_id>
    # ----------------------------------------------------------
    def cancel(self, swap_id):
        swap = SwapRequest.query.get(int(swap_id))
        if not swap:
            return jsonify({"success": False, "message": "Swap request not found"}), 404
        if not swap.is_pending():
            return jsonify({
                "success": False,
                "message": f"Cannot cancel a request that is already {swap.status}",
            }), 400
        try:
            db.session.delete(swap)
            db.session.commit()
            return jsonify({"success": True, "message": "Swap request cancelled"}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500


# =============================================================
# ROUTE REGISTRATION
# =============================================================
_controller = SwapController()

swap_bp.add_url_rule(
    "/swap/available",
    view_func=_controller.list_available,
    methods=["GET"],
)
swap_bp.add_url_rule(
    "/swap/request",
    view_func=_controller.request_swap,
    methods=["POST"],
)
swap_bp.add_url_rule(
    "/swap/incoming",
    view_func=_controller.get_incoming,
    methods=["GET"],
)
swap_bp.add_url_rule(
    "/swap/outgoing",
    view_func=_controller.get_outgoing,
    methods=["GET"],
)
swap_bp.add_url_rule(
    "/swap/<int:swap_id>/respond",
    view_func=_controller.respond,
    methods=["POST"],
)
swap_bp.add_url_rule(
    "/swap/<int:swap_id>",
    view_func=_controller.cancel,
    methods=["DELETE"],
)