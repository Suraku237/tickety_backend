from flask import Blueprint, request, jsonify
from models import db, Ticket, Service
from datetime import datetime, timezone
from sqlalchemy import func

analytics_bp = Blueprint('analytics', __name__)


# =============================================================
# ANALYTICS CONTROLLER
#
# Routes (all admin-only: X-App-Source: web OR mobile with user_id):
#   GET /api/analytics/wait-times          → per-queue wait times
#   GET /api/analytics/summary             → global stats
#
# Waiting time logic:
#   • For CLOSED tickets: updated_at - created_at (real resolution time)
#   • For OPEN/PENDING tickets: now() - created_at (time already waited)
#
# Per-queue (service): average, min, max wait time + ticket counts
# =============================================================

class AnalyticsController:

    def _is_admin(self) -> bool:
        return request.headers.get('X-App-Source', '').lower() == 'web'

    # ----------------------------------------------------------
    # GET /api/analytics/wait-times
    # Optional query params:
    #   ?service_id=<id>   → filter to one service
    #   ?user_id=<id>      → mobile user: only their own tickets
    # ----------------------------------------------------------
    def wait_times(self):
        service_id_param = request.args.get('service_id', '').strip() or None
        user_id_param    = request.args.get('user_id',    '').strip() or None

        try:
            # Base query: join tickets with services
            query = (
                db.session.query(
                    Ticket.service_id,
                    Ticket.service,
                    Ticket.status,
                    Ticket.priority,
                    Ticket.created_at,
                    Ticket.updated_at,
                )
                .filter(Ticket.service_id.isnot(None))
            )

            # Apply filters
            if service_id_param:
                query = query.filter(Ticket.service_id == int(service_id_param))
            if user_id_param and not self._is_admin():
                query = query.filter(Ticket.user_id == int(user_id_param))

            tickets = query.all()

            # Group by service_id
            service_map: dict[int, dict] = {}
            now = datetime.now(timezone.utc)

            for row in tickets:
                sid   = row.service_id
                sname = row.service or f'Service {sid}'

                if sid not in service_map:
                    service_map[sid] = {
                        'service_id':   sid,
                        'service_name': sname,
                        'wait_minutes': [],
                        'total':        0,
                        'open':         0,
                        'pending':      0,
                        'closed':       0,
                        'by_priority':  {'urgent': 0, 'high': 0, 'medium': 0, 'low': 0},
                    }

                entry = service_map[sid]
                entry['total'] += 1

                # Count by status
                status = row.status or 'open'
                if status in entry:
                    entry[status] += 1

                # Count by priority
                prio = row.priority or 'medium'
                if prio in entry['by_priority']:
                    entry['by_priority'][prio] += 1

                # Calculate wait time in minutes
                created = row.created_at
                if created is None:
                    continue

                # Ensure timezone-aware
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)

                if status == 'closed' and row.updated_at:
                    resolved = row.updated_at
                    if resolved.tzinfo is None:
                        resolved = resolved.replace(tzinfo=timezone.utc)
                    delta = resolved - created
                else:
                    delta = now - created

                wait_min = max(0, delta.total_seconds() / 60)
                entry['wait_minutes'].append(wait_min)

            # Build response per service
            results = []
            for sid, data in service_map.items():
                waits = data['wait_minutes']
                avg_w = round(sum(waits) / len(waits), 1) if waits else 0
                min_w = round(min(waits), 1) if waits else 0
                max_w = round(max(waits), 1) if waits else 0

                # Estimate queue position for open tickets
                # (number of open tickets ahead + 1, based on age)
                queue_depth = data['open'] + data['pending']

                results.append({
                    'service_id':         sid,
                    'service_name':       data['service_name'],
                    'total_tickets':      data['total'],
                    'open_tickets':       data['open'],
                    'pending_tickets':    data['pending'],
                    'closed_tickets':     data['closed'],
                    'queue_depth':        queue_depth,
                    'avg_wait_minutes':   avg_w,
                    'min_wait_minutes':   min_w,
                    'max_wait_minutes':   max_w,
                    'avg_wait_display':   _fmt_duration(avg_w),
                    'min_wait_display':   _fmt_duration(min_w),
                    'max_wait_display':   _fmt_duration(max_w),
                    'by_priority':        data['by_priority'],
                    # Congestion level: green/yellow/red
                    'congestion':         _congestion(queue_depth, avg_w),
                })

            # Sort by avg wait descending (busiest first)
            results.sort(key=lambda x: x['avg_wait_minutes'], reverse=True)

            return jsonify({
                'success':   True,
                'analytics': results,
                'count':     len(results),
            }), 200

        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500

    # ----------------------------------------------------------
    # GET /api/analytics/summary
    # Global aggregate across all services
    # ----------------------------------------------------------
    def summary(self):
        user_id_param = request.args.get('user_id', '').strip() or None
        try:
            query = db.session.query(Ticket)
            if user_id_param and not self._is_admin():
                query = query.filter(Ticket.user_id == int(user_id_param))

            tickets = query.all()
            now = datetime.now(timezone.utc)

            total    = len(tickets)
            open_c   = sum(1 for t in tickets if t.status == 'open')
            pending  = sum(1 for t in tickets if t.status == 'pending')
            closed   = sum(1 for t in tickets if t.status == 'closed')

            all_waits = []
            for t in tickets:
                created = t.created_at
                if not created:
                    continue
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if t.status == 'closed' and t.updated_at:
                    resolved = t.updated_at
                    if resolved.tzinfo is None:
                        resolved = resolved.replace(tzinfo=timezone.utc)
                    delta = resolved - created
                else:
                    delta = now - created
                all_waits.append(max(0, delta.total_seconds() / 60))

            avg_wait = round(sum(all_waits) / len(all_waits), 1) if all_waits else 0

            # Busiest service (most open tickets)
            svc_counts: dict[str, int] = {}
            for t in tickets:
                if t.service and t.status in ('open', 'pending'):
                    svc_counts[t.service] = svc_counts.get(t.service, 0) + 1
            busiest = max(svc_counts, key=svc_counts.get) if svc_counts else None

            return jsonify({
                'success':              True,
                'total_tickets':        total,
                'open_tickets':         open_c,
                'pending_tickets':      pending,
                'closed_tickets':       closed,
                'avg_wait_minutes':     avg_wait,
                'avg_wait_display':     _fmt_duration(avg_wait),
                'busiest_service':      busiest,
                'busiest_queue_depth':  svc_counts.get(busiest, 0) if busiest else 0,
            }), 200

        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500


# ----------------------------------------------------------
# Helpers
# ----------------------------------------------------------
def _fmt_duration(minutes: float) -> str:
    """Format minutes into human-readable string."""
    if minutes < 1:
        return '< 1 min'
    if minutes < 60:
        return f'{int(minutes)} min'
    hours = int(minutes // 60)
    mins  = int(minutes % 60)
    return f'{hours}h {mins}m' if mins else f'{hours}h'


def _congestion(queue_depth: int, avg_wait: float) -> str:
    """Return a traffic-light congestion label."""
    if queue_depth <= 2 and avg_wait < 30:
        return 'low'
    if queue_depth <= 6 or avg_wait < 90:
        return 'medium'
    return 'high'


# ----------------------------------------------------------
# Route registration
# ----------------------------------------------------------
_ctrl = AnalyticsController()

analytics_bp.add_url_rule(
    '/analytics/wait-times',
    view_func=_ctrl.wait_times,
    methods=['GET'],
)
analytics_bp.add_url_rule(
    '/analytics/summary',
    view_func=_ctrl.summary,
    methods=['GET'],
)