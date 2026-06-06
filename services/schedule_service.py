from datetime import datetime, timezone, timedelta
from models import Ticket, ServiceSchedule


# =============================================================
# SCHEDULE SERVICE
# Responsibilities:
#   - Compute estimated serve time for a ticket
#   - Determine if the service is currently open
#   - Check if a ticket's estimated time exceeds closing time
#   - Provide closing time warning data for the frontend popup
# OOP Principle: Single Responsibility, Abstraction
#
# NOTE ON DATETIME CONVENTION:
#   All datetimes are stored and compared as naive UTC.
#   MySQL/SQLite strip timezone info on DATETIME columns, so
#   estimated_serve_at always comes back from the DB as naive.
#   To avoid offset-naive vs offset-aware TypeError, this service
#   never attaches tzinfo to datetimes used in comparisons or
#   stored on model fields. datetime.utcnow() is used instead of
#   datetime.now(timezone.utc) everywhere for consistency.
# =============================================================

def _utcnow() -> datetime:
    """Return the current UTC time as a naive datetime (no tzinfo)."""
    return datetime.utcnow()


def _strip_tz(dt: datetime | None) -> datetime | None:
    """Strip tzinfo from a datetime if present, leaving value unchanged."""
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


class ScheduleService:

    # ----------------------------------------------------------
    # COMPUTE ESTIMATED SERVE TIME
    # Formula:
    #   estimated_serve_at = now + (position × avg_duration_minutes)
    # Called when a ticket is issued and when the queue moves.
    # Returns a naive UTC datetime safe for DB storage.
    # ----------------------------------------------------------
    def compute_estimated_serve_at(
        self,
        position: int,
        avg_duration: int,
        base_time: datetime = None,
    ) -> datetime:
        """
        Return the estimated datetime at which a ticket at
        the given position will be served.
        base_time defaults to now (naive UTC).
        Always returns a naive datetime.
        """
        base = _strip_tz(base_time) if base_time else _utcnow()
        return base + timedelta(minutes=position * avg_duration)

    # ----------------------------------------------------------
    # IS SERVICE OPEN NOW
    # ----------------------------------------------------------
    def is_open_now(self, schedule: ServiceSchedule | None) -> bool:
        """
        Return True if the service is currently open based on
        the effective schedule for today.
        Returns False if no schedule is configured.
        """
        if not schedule or not schedule.is_open:
            return False

        now_time = _utcnow().time()
        return schedule.opening_time <= now_time <= schedule.closing_time

    # ----------------------------------------------------------
    # EXCEEDS CLOSING TIME
    # ----------------------------------------------------------
    def exceeds_closing_time(
        self,
        estimated_serve_at: datetime,
        schedule: ServiceSchedule | None,
    ) -> bool:
        """
        Return True if the estimated serve time is at or after
        today's closing time — meaning the ticket should be
        carried over to the next working day.
        Both datetimes are compared as naive UTC.
        """
        if not schedule or not schedule.is_open:
            return False

        if estimated_serve_at is None:
            return False

        today      = _utcnow().date()
        closing_dt = datetime.combine(today, schedule.closing_time)  # naive
        est        = _strip_tz(estimated_serve_at)

        return est >= closing_dt

    # ----------------------------------------------------------
    # CLOSING TIME WARNING PAYLOAD
    # Sent to the frontend to trigger the popup indicator
    # and to the mobile app to trigger a push notification.
    # ----------------------------------------------------------
    def closing_warning_payload(
        self,
        schedule: ServiceSchedule | None,
        tickets_exceeding: list,
    ) -> dict:
        """
        Build the payload the frontend and mobile app consume
        to display closing time warnings.

        tickets_exceeding: list of Ticket objects whose
        estimated_serve_at >= closing_time.
        """
        if not schedule:
            return {"warning": False}

        today      = _utcnow().date()
        closing_dt = datetime.combine(today, schedule.closing_time)  # naive

        return {
            "warning":          len(tickets_exceeding) > 0,
            "closing_time":     str(schedule.closing_time),
            "closing_dt":       closing_dt.isoformat(),
            "affected_count":   len(tickets_exceeding),
            "affected_tickets": [
                {
                    "ticket_id":           str(t.id),
                    "code":                t.code,
                    "estimated_serve_at":  (
                        _strip_tz(t.estimated_serve_at).isoformat()
                        if t.estimated_serve_at else None
                    ),
                    "customer_identifier": t.customer_identifier,
                }
                for t in tickets_exceeding
            ],
        }

    # ----------------------------------------------------------
    # RECALCULATE QUEUE ESTIMATES
    # Called after every queue movement (serve, suspend, delete,
    # swap) to keep estimated_serve_at accurate for all tickets.
    # ----------------------------------------------------------
    def recalculate_queue(
        self,
        tickets: list,
        avg_duration: int,
        base_time: datetime = None,
    ) -> list:
        """
        Recompute estimated_serve_at for each ticket in the list
        (already sorted by position ascending).
        Mutates the ticket objects in place — caller must commit.
        Returns the mutated ticket list.
        base_time defaults to now (naive UTC).
        """
        base = _strip_tz(base_time) if base_time else _utcnow()
        for ticket in tickets:
            if ticket.position is not None:
                ticket.estimated_serve_at = self.compute_estimated_serve_at(
                    ticket.position, avg_duration, base
                )
        return tickets