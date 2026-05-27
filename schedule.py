from flask import Blueprint, request, jsonify
from repositories.schedule_repository import ScheduleRepository
from repositories.ticket_repository   import TicketRepository
from services.schedule_service        import ScheduleService
from datetime import datetime, timezone, time as time_type

schedule_bp = Blueprint("schedule", __name__)

# =============================================================
# SCHEDULE CONTROLLER
# Responsibilities:
#   - Get full schedule for a service
#   - Set general schedule (applied to all days)
#   - Override a specific day
#   - Delete a day override (revert to general)
#   - Get current open/closed status + closing time warning
# OOP Principle: Single Responsibility, Dependency Injection
# =============================================================
class ScheduleController:

    DAY_NAMES = {
        0: "Monday", 1: "Tuesday", 2: "Wednesday",
        3: "Thursday", 4: "Friday", 5: "Saturday", 6: "Sunday",
    }

    def _get_deps(self):
        return (
            ScheduleRepository(),
            TicketRepository(),
            ScheduleService(),
        )

    def _parse_time(self, time_str: str) -> time_type | None:
        """Parse 'HH:MM' or 'HH:MM:SS' into a time object."""
        if not time_str:
            return None
        try:
            parts = time_str.strip().split(":")
            return time_type(int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            return None

    # ----------------------------------------------------------
    # GET SCHEDULE
    # GET /api/schedule?service_id=<id>
    # Returns general row + all day overrides
    # ----------------------------------------------------------
    def get_schedule(self):
        schedule_repo, _, _ = self._get_deps()

        service_id = request.args.get("service_id")
        if not service_id:
            return jsonify({"success": False, "message": "service_id is required"}), 400

        rows    = schedule_repo.find_all(int(service_id))
        general = next((r for r in rows if r.day_of_week is None), None)
        overrides = [r for r in rows if r.day_of_week is not None]

        return jsonify({
            "success":   True,
            "general":   general.to_dict() if general else None,
            "overrides": [r.to_dict() for r in overrides],
        }), 200

    # ----------------------------------------------------------
    # SET GENERAL SCHEDULE
    # POST /api/schedule/general
    # Body: { service_id, is_open, opening_time, closing_time, avg_duration }
    # ----------------------------------------------------------
    def set_general(self):
        schedule_repo, _, _ = self._get_deps()

        data         = request.get_json()
        service_id   = data.get("service_id")
        is_open      = data.get("is_open", True)
        opening_str  = data.get("opening_time", "")
        closing_str  = data.get("closing_time", "")
        avg_duration = int(data.get("avg_duration", 10))

        if not service_id:
            return jsonify({"success": False, "message": "service_id is required"}), 400

        opening = self._parse_time(opening_str)
        closing = self._parse_time(closing_str)

        if not opening or not closing:
            return jsonify({"success": False, "message": "opening_time and closing_time are required (HH:MM)"}), 400

        if closing <= opening:
            return jsonify({"success": False, "message": "closing_time must be after opening_time"}), 400

        if avg_duration < 1:
            return jsonify({"success": False, "message": "avg_duration must be at least 1 minute"}), 400

        try:
            row = schedule_repo.upsert_general(
                service_id   = int(service_id),
                is_open      = bool(is_open),
                opening_time = opening,
                closing_time = closing,
                avg_duration = avg_duration,
            )
            schedule_repo.save()
            return jsonify({"success": True, "schedule": row.to_dict()}), 200
        except Exception as e:
            schedule_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # SET DAY OVERRIDE
    # POST /api/schedule/day
    # Body: { service_id, day_of_week (0-6), is_open,
    #         opening_time, closing_time, avg_duration }
    # ----------------------------------------------------------
    def set_day(self):
        schedule_repo, _, _ = self._get_deps()

        data         = request.get_json()
        service_id   = data.get("service_id")
        day_of_week  = data.get("day_of_week")
        is_open      = data.get("is_open", True)
        opening_str  = data.get("opening_time", "")
        closing_str  = data.get("closing_time", "")
        avg_duration = int(data.get("avg_duration", 10))

        if not service_id:
            return jsonify({"success": False, "message": "service_id is required"}), 400

        if day_of_week is None or int(day_of_week) not in range(7):
            return jsonify({"success": False, "message": "day_of_week must be 0 (Mon) to 6 (Sun)"}), 400

        # If marking as closed, times are optional
        if bool(is_open):
            opening = self._parse_time(opening_str)
            closing = self._parse_time(closing_str)
            if not opening or not closing:
                return jsonify({"success": False, "message": "opening_time and closing_time are required when is_open=true"}), 400
            if closing <= opening:
                return jsonify({"success": False, "message": "closing_time must be after opening_time"}), 400
        else:
            # Closed day — use placeholder times
            opening = time_type(0, 0)
            closing = time_type(0, 0)

        try:
            row = schedule_repo.upsert_day(
                service_id   = int(service_id),
                day_of_week  = int(day_of_week),
                is_open      = bool(is_open),
                opening_time = opening,
                closing_time = closing,
                avg_duration = avg_duration,
            )
            schedule_repo.save()
            return jsonify({
                "success":  True,
                "schedule": row.to_dict(),
                "day_name": self.DAY_NAMES.get(int(day_of_week), ""),
            }), 200
        except Exception as e:
            schedule_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # DELETE DAY OVERRIDE
    # DELETE /api/schedule/day/<day_of_week>?service_id=<id>
    # Reverts that day back to the general schedule
    # ----------------------------------------------------------
    def delete_day(self, day_of_week):
        schedule_repo, _, _ = self._get_deps()

        service_id = request.args.get("service_id")
        if not service_id:
            return jsonify({"success": False, "message": "service_id is required"}), 400

        if int(day_of_week) not in range(7):
            return jsonify({"success": False, "message": "day_of_week must be 0–6"}), 400

        try:
            schedule_repo.delete_day(int(service_id), int(day_of_week))
            schedule_repo.save()
            return jsonify({
                "success": True,
                "message": f"{self.DAY_NAMES.get(int(day_of_week), 'Day')} override removed — general schedule now applies",
            }), 200
        except Exception as e:
            schedule_repo.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # ----------------------------------------------------------
    # GET CURRENT STATUS
    # GET /api/schedule/status?service_id=<id>
    # Returns: is_open, closing_time, minutes_until_close,
    #          closing_warning (for frontend popup trigger)
    # ----------------------------------------------------------
    def get_status(self):
        schedule_repo, ticket_repo, schedule_svc = self._get_deps()

        service_id = request.args.get("service_id")
        if not service_id:
            return jsonify({"success": False, "message": "service_id is required"}), 400

        sid      = int(service_id)
        schedule = schedule_repo.resolve_for_today(sid)

        if not schedule:
            return jsonify({
                "success":    True,
                "is_open":    False,
                "message":    "No schedule configured for this service",
            }), 200

        is_open = schedule_svc.is_open_now(schedule)

        # Minutes until closing
        now_time  = datetime.now(timezone.utc).time()
        today     = datetime.now(timezone.utc).date()
        closing_dt = datetime.combine(today, schedule.closing_time).replace(tzinfo=timezone.utc)
        now_dt     = datetime.now(timezone.utc)
        mins_until_close = max(0, int((closing_dt - now_dt).total_seconds() / 60))

        # Tickets exceeding closing time
        tickets   = ticket_repo.find_by_service(sid)
        exceeding = [
            t for t in tickets
            if t.estimated_serve_at
            and schedule_svc.exceeds_closing_time(t.estimated_serve_at, schedule)
        ]

        warning = schedule_svc.closing_warning_payload(schedule, exceeding)

        return jsonify({
            "success":           True,
            "is_open":           is_open,
            "opening_time":      str(schedule.opening_time),
            "closing_time":      str(schedule.closing_time),
            "avg_duration":      schedule.avg_duration,
            "mins_until_close":  mins_until_close,
            "day_name":          self.DAY_NAMES.get(datetime.now(timezone.utc).weekday(), ""),
            "closing_warning":   warning,
        }), 200


# =============================================================
# ROUTE REGISTRATION
# =============================================================
_controller = ScheduleController()

schedule_bp.add_url_rule("/schedule",               view_func=_controller.get_schedule, methods=["GET"])
schedule_bp.add_url_rule("/schedule/general",       view_func=_controller.set_general,  methods=["POST"])
schedule_bp.add_url_rule("/schedule/day",           view_func=_controller.set_day,      methods=["POST"])
schedule_bp.add_url_rule("/schedule/day/<int:day_of_week>", view_func=_controller.delete_day, methods=["DELETE"])
schedule_bp.add_url_rule("/schedule/status",        view_func=_controller.get_status,   methods=["GET"])