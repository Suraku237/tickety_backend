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
#   - Average wait time per queue
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
        from models import Queue
        queues = Queue.query.filter_by(service_id=sid).all()
        queue_stats = []
        for q in queues:
            q_tickets = [t for t in tickets if t.queue_id == q.id and t.status == 'served']
            if q_tickets:
                # Estimate: average position × assume avg_duration=10 as fallback
                avg_pos = sum(t.position or 0 for t in q_tickets) / len(q_tickets)
                avg_wait = round(avg_pos * 10)
            else:
                avg_wait = 0
            queue_stats.append({
                "queue_id":   str(q.id),
                "queue_name": q.name,
                "avg_wait":   avg_wait,
                "tickets":    len([t for t in tickets if t.queue_id == q.id]),
            })

        # --- Tickets per day of week ---
        day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        day_counts = [0] * 7
        for t in tickets:
            dow = t.issued_at.weekday()
            day_counts[dow] += 1

        daily = [{"day": day_labels[i], "count": day_counts[i]} for i in range(7)]
        peak  = max(daily, key=lambda x: x["count"], default={"day": "—"})

        return jsonify({
            "success":            True,
            "period":             period,
            "total_tickets":      total,
            "avg_per_day":        avg_per_day,
            "peak_day":           peak["day"],
            "priority_breakdown": priority_breakdown,
            "queue_stats":        queue_stats,
            "daily":              daily,
        }), 200


# =============================================================
# ROUTE REGISTRATION
# =============================================================
_controller = AnalyticsController()

analytics_bp.add_url_rule("/analytics", view_func=_controller.get_analytics, methods=["GET"])