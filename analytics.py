from flask import Blueprint, request, jsonify
from models import Ticket, db
from sqlalchemy import func
from datetime import datetime, timezone, timedelta

analytics_bp = Blueprint("analytics", __name__)

# =============================================================
# ANALYTICS CONTROLLER
# Responsibilities:
#   - Average tickets per day
#   - Priority breakdown (counts + percentages)
#   - Average wait time per queue (using actual schedule avg_duration)
#   - Peak day of the week
# OOP Principle: Single Responsibility, Encapsulation
# =============================================================
class AnalyticsController:

    PERIOD_DAYS = {
        "week":       7,
        "last_week":  14,
        "month":      30,
    }

    def _get_date_range(self, period: str):
        now   = datetime.now(timezone.utc)
        days  = self.PERIOD_DAYS.get(period, 7)
        start = now - timedelta(days=days)
        return start, now

    # ----------------------------------------------------------
    # GET ANALYTICS
    # GET /api/analytics?service_id=<id>&period=week|last_week|month
    # ----------------------------------------------------------
    def get_analytics(self):
        from repositories.schedule_repository import ScheduleRepository
        from repositories.admin_repository    import AdminRepository

        service_id = request.args.get("service_id")
        period     = request.args.get("period", "week")

        if not service_id:
            return jsonify({"success": False, "message": "service_id is required"}), 400

        sid        = int(service_id)
        start, end = self._get_date_range(period)

        # --- All tickets in range ---
        tickets = (Ticket.query
                   .filter_by(service_id=sid)
                   .filter(Ticket.issued_at >= start)
                   .filter(Ticket.issued_at <= end)
                   .all())

        total = len(tickets)
        days  = max(self.PERIOD_DAYS.get(period, 7), 1)

        # --- Avg per day ---
        avg_per_day = round(total / days, 1)

        # --- Priority breakdown ---
        priority_counts = {"normal": 0, "high": 0, "urgent": 0}
        for t in tickets:
            if t.priority in priority_counts:
                priority_counts[t.priority] += 1

        priority_breakdown = []
        for p, count in priority_counts.items():
            pct = round((count / total * 100), 1) if total > 0 else 0
            priority_breakdown.append({
                "priority": p,
                "count":    count,
                "pct":      pct,
            })

        # --- Avg wait time per queue ---
        # Uses the actual schedule avg_duration for the service,
        # multiplied by average position of served tickets.
        # Falls back to 10 min if no schedule is configured.
        from models import Queue
        schedule_repo = ScheduleRepository()
        schedule      = schedule_repo.resolve_for_today(sid)
        avg_duration  = schedule.avg_duration if schedule else 10

        queues      = Queue.query.filter_by(service_id=sid).all()
        queue_stats = []
        for q in queues:
            # Count ALL tickets for this queue in range (for the tickets column)
            q_all = [t for t in tickets if t.queue_id == q.id]

            # For avg wait: use served tickets that have an estimated_serve_at
            # and issued_at — compute actual wait as difference
            q_served = [
                t for t in q_all
                if t.status == 'served'
                and t.estimated_serve_at
                and t.issued_at
            ]

            if q_served:
                # Average wait = mean of (estimated_serve_at - issued_at) in minutes
                waits = [
                    (t.estimated_serve_at - t.issued_at.replace(tzinfo=timezone.utc)
                     if t.issued_at.tzinfo is None
                     else t.estimated_serve_at - t.issued_at).total_seconds() / 60
                    for t in q_served
                ]
                avg_wait = round(sum(waits) / len(waits))
            else:
                # Fallback: estimate from pending tickets' positions × avg_duration
                q_pending = [t for t in q_all if t.status in ('pending', 'active') and t.position is not None]
                if q_pending:
                    avg_pos  = sum(t.position for t in q_pending) / len(q_pending)
                    avg_wait = round(avg_pos * avg_duration)
                else:
                    avg_wait = 0

            queue_stats.append({
                "queue_id":   str(q.id),
                "queue_name": q.name,
                "avg_wait":   avg_wait,
                "tickets":    len(q_all),
            })

        # --- Tickets per day of week ---
        day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        day_counts = [0] * 7
        for t in tickets:
            dow = t.issued_at.weekday()
            day_counts[dow] += 1

        daily = [{"day": day_labels[i], "count": day_counts[i]} for i in range(7)]
        peak  = max(daily, key=lambda x: x["count"], default={"day": "—"})

        # --- Team count ---
        admin_repo  = AdminRepository()
        team_count  = len(admin_repo.find_by_service(sid))

        # --- Avg wait across all queues (for KPI card) ---
        all_waits = [q["avg_wait"] for q in queue_stats if q["avg_wait"] > 0]
        global_avg_wait = round(sum(all_waits) / len(all_waits)) if all_waits else "—"

        return jsonify({
            "success":            True,
            "period":             period,
            "total_tickets":      total,
            "avg_per_day":        avg_per_day,
            "avg_wait":           global_avg_wait,
            "peak_day":           peak["day"],
            "team_count":         team_count,
            "priority_breakdown": priority_breakdown,
            "queue_stats":        queue_stats,
            "daily":              daily,
        }), 200


# =============================================================
# ROUTE REGISTRATION
# =============================================================
_controller = AnalyticsController()

analytics_bp.add_url_rule("/analytics", view_func=_controller.get_analytics, methods=["GET"])