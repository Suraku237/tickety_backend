from flask import Blueprint, request, jsonify
from repositories.ticket_repository  import TicketRepository
from repositories.service_repository import ServiceRepository
from models import User

tickets_bp = Blueprint('tickets', __name__)


# =============================================================
# TICKET CONTROLLER
# Responsibilities:
#   - Handle HTTP request/response for all ticket routes
#   - On create: resolve service_id from scanned QR token
#   - Enforce that the requesting user owns the ticket
# OOP Principle: Single Responsibility, Dependency Injection
#
# Routes:
#   POST   /api/tickets              → create ticket
#   GET    /api/tickets?user_id=     → list user tickets
#   GET    /api/tickets/<id>?user_id=→ single ticket
#   PATCH  /api/tickets/<id>         → update (admin: any field)
#   DELETE /api/tickets/<id>         → delete (owner only)
#
#  ADMIN-ONLY (X-App-Source: web):
#   GET    /api/tickets/all          → all tickets
#   PATCH  /api/tickets/<id>         → can set priority + status
# =============================================================
class TicketController:

    def _get_deps(self):
        return TicketRepository(), ServiceRepository()

    def _is_admin(self) -> bool:
        return request.headers.get('X-App-Source', '').lower() == 'web'

    # ----------------------------------------------------------
    # POST /api/tickets
    # Mobile sends: user_id, title, description, notes,
    #               service_code (full QR URL or token)
    #
    # If service_code contains a token path (/scan/<token>),
    # we resolve it to a Service row automatically so the ticket
    # is linked to the correct service_id — no user input needed.
    # ----------------------------------------------------------
    def create(self):
        ticket_repo, svc_repo = self._get_deps()
        data = request.get_json(silent=True) or {}

        user_id      = str(data.get('user_id',      '')).strip()
        title        = str(data.get('title',        '')).strip()
        description  = str(data.get('description',  '')).strip()
        notes        = str(data.get('notes',        '')).strip()
        service_code = str(data.get('service_code', '')).strip()

        # Validate required fields
        if not user_id:
            return jsonify({'success': False,
                            'message': 'user_id is required'}), 400
        if not title:
            return jsonify({'success': False,
                            'message': 'title is required'}), 400
        if not description:
            return jsonify({'success': False,
                            'message': 'description is required'}), 400

        try:
            uid = int(user_id)
        except ValueError:
            return jsonify({'success': False,
                            'message': 'Invalid user_id'}), 400

        # Verify user exists
        user = User.query.get(uid)
        if not user:
            return jsonify({'success': False,
                            'message': 'User not found'}), 404

        # --------------------------------------------------
        # Resolve service from QR token
        # The mobile app sends the full scanned URL as service_code.
        # We extract the token from the last path segment and look
        # up the Service row to get the canonical name + id.
        # --------------------------------------------------
        resolved_service    = None
        resolved_service_id = None
        resolved_name       = str(data.get('service', '')).strip()

        if service_code:
            token = self._extract_token(service_code)
            if token:
                resolved_service = svc_repo.find_by_token(token)
                if resolved_service:
                    resolved_service_id = resolved_service.id
                    resolved_name       = resolved_service.name

        if not resolved_name:
            return jsonify({'success': False,
                            'message': 'Could not resolve service from QR code'}), 400

        try:
            ticket = ticket_repo.create(
                user_id      = uid,
                title        = title,
                description  = description,
                notes        = notes,
                priority     = 'medium',  # admin sets priority after review
                service      = resolved_name,
                service_code = service_code,
                service_id   = resolved_service_id,
            )
            ticket_repo.save()
            return jsonify({
                'success': True,
                'message': 'Ticket created successfully',
                'ticket':  ticket.to_dict(),
            }), 201

        except Exception as e:
            ticket_repo.rollback()
            return jsonify({'success': False, 'message': str(e)}), 500

    def _extract_token(self, service_code: str) -> str | None:
        """
        Extract the service token from a scanned QR URL.
        Handles:
          https://tickety.app/scan/<token>  → <token>
          <token>                           → <token> (raw token)
        """
        try:
            from urllib.parse import urlparse
            parsed = urlparse(service_code)
            parts  = [p for p in parsed.path.split('/') if p]
            # /scan/<token> → last segment
            if 'scan' in parts:
                idx = parts.index('scan')
                if idx + 1 < len(parts):
                    return parts[idx + 1]
            # If it looks like a UUID, treat as raw token
            if len(service_code) == 36 and service_code.count('-') == 4:
                return service_code
        except Exception:
            pass
        return None

    # ----------------------------------------------------------
    # GET /api/tickets?user_id=<id>
    # ----------------------------------------------------------
    def list_tickets(self):
        ticket_repo, _ = self._get_deps()
        user_id  = request.args.get('user_id', '').strip()
        status   = request.args.get('status',  '').strip().lower() or None
        priority = request.args.get('priority','').strip().lower() or None

        if not user_id:
            return jsonify({'success': False,
                            'message': 'user_id is required'}), 400
        try:
            uid = int(user_id)
        except ValueError:
            return jsonify({'success': False,
                            'message': 'Invalid user_id'}), 400

        try:
            if status:
                tickets = ticket_repo.find_by_user_and_status(uid, status)
            elif priority:
                tickets = ticket_repo.find_by_user_and_priority(uid, priority)
            else:
                tickets = ticket_repo.find_all_by_user(uid)

            return jsonify({
                'success': True,
                'tickets': [t.to_dict() for t in tickets],
                'count':   len(tickets),
            }), 200
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500

    # ----------------------------------------------------------
    # GET /api/tickets/all  (admin only)
    # ----------------------------------------------------------
    def list_all(self):
        if not self._is_admin():
            return jsonify({'success': False,
                            'message': 'Admin access required'}), 403
        ticket_repo, _ = self._get_deps()
        try:
            status   = request.args.get('status',  '').strip().lower() or None
            service_id = request.args.get('service_id', '').strip() or None

            if service_id:
                tickets = ticket_repo.find_by_service(int(service_id))
            elif status:
                tickets = ticket_repo.find_by_status(status)
            else:
                tickets = ticket_repo.find_all()

            return jsonify({
                'success': True,
                'tickets': [t.to_dict() for t in tickets],
                'count':   len(tickets),
            }), 200
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500

    # ----------------------------------------------------------
    # GET /api/tickets/<ticket_id>?user_id=<id>
    # ----------------------------------------------------------
    def get_ticket(self, ticket_id: int):
        ticket_repo, _ = self._get_deps()
        user_id = request.args.get('user_id', '').strip()
        ticket  = ticket_repo.find_by_id(ticket_id)

        if not ticket:
            return jsonify({'success': False,
                            'message': 'Ticket not found'}), 404

        # Admin can see any ticket; client only sees their own
        if not self._is_admin() and str(ticket.user_id) != user_id:
            return jsonify({'success': False,
                            'message': 'Access denied'}), 403

        return jsonify({'success': True, 'ticket': ticket.to_dict()}), 200

    # ----------------------------------------------------------
    # PATCH /api/tickets/<ticket_id>
    # Client: can only update title, description, notes
    # Admin:  can also update status and priority
    # ----------------------------------------------------------
    def update_ticket(self, ticket_id: int):
        ticket_repo, _ = self._get_deps()
        data    = request.get_json(silent=True) or {}
        user_id = str(data.get('user_id', '')).strip()
        ticket  = ticket_repo.find_by_id(ticket_id)

        if not ticket:
            return jsonify({'success': False,
                            'message': 'Ticket not found'}), 404

        is_admin = self._is_admin()
        if not is_admin and str(ticket.user_id) != user_id:
            return jsonify({'success': False,
                            'message': 'Access denied'}), 403

        try:
            ticket_repo.update_fields(
                ticket,
                title       = data.get('title'),
                description = data.get('description'),
                notes       = data.get('notes'),
                # Admin-only fields
                priority    = data.get('priority') if is_admin else None,
                status      = data.get('status')   if is_admin else None,
            )
            ticket_repo.save()
            return jsonify({
                'success': True,
                'message': 'Ticket updated',
                'ticket':  ticket.to_dict(),
            }), 200
        except ValueError as e:
            return jsonify({'success': False, 'message': str(e)}), 400
        except Exception as e:
            ticket_repo.rollback()
            return jsonify({'success': False, 'message': str(e)}), 500

    # ----------------------------------------------------------
    # DELETE /api/tickets/<ticket_id>
    # ----------------------------------------------------------
    def delete_ticket(self, ticket_id: int):
        ticket_repo, _ = self._get_deps()
        data    = request.get_json(silent=True) or {}
        user_id = str(data.get('user_id', '')).strip()
        ticket  = ticket_repo.find_by_id(ticket_id)

        if not ticket:
            return jsonify({'success': False,
                            'message': 'Ticket not found'}), 404

        if not self._is_admin() and str(ticket.user_id) != user_id:
            return jsonify({'success': False,
                            'message': 'Access denied'}), 403

        try:
            ticket_repo.delete(ticket)
            ticket_repo.save()
            return jsonify({'success': True,
                            'message': 'Ticket deleted'}), 200
        except Exception as e:
            ticket_repo.rollback()
            return jsonify({'success': False, 'message': str(e)}), 500


# =============================================================
# ROUTE REGISTRATION
# =============================================================
_ctrl = TicketController()

tickets_bp.add_url_rule('/tickets',
    view_func=_ctrl.create,       methods=['POST'])
tickets_bp.add_url_rule('/tickets',
    view_func=_ctrl.list_tickets, methods=['GET'])
tickets_bp.add_url_rule('/tickets/all',
    view_func=_ctrl.list_all,     methods=['GET'])
tickets_bp.add_url_rule('/tickets/<int:ticket_id>',
    view_func=_ctrl.get_ticket,   methods=['GET'])
tickets_bp.add_url_rule('/tickets/<int:ticket_id>',
    view_func=_ctrl.update_ticket,methods=['PATCH'])
tickets_bp.add_url_rule('/tickets/<int:ticket_id>',
    view_func=_ctrl.delete_ticket,methods=['DELETE'])
