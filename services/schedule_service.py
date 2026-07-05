from datetime import datetime, timezone, timedelta
from models import Ticket, ServiceSchedule, ApiTimestamp
from services.local_clock import LocalClock


# =============================================================
# SCHEDULE SERVICE
# Responsibilities:
#   - Compute estimated serve time for a ticket
#   - Determine if the service is currently open
#   - Check if a ticket's estimated time exceeds closing time
#   - Provide closing time warning data for the frontend popup
# OOP Principle: Single Responsibility, Abstraction — timezone
#   questions are delegated to the LocalClock collaborator.
#
# NOTE ON DATETIME CONVENTION:
#   All datetimes are STORED as naive UTC (MySQL strips tzinfo).
#   Schedule opening/closing times are ENTERED by the boss in the
#   business's LOCAL timezone. The LocalClock converts between the
#   two frames so that a closing time of 10:00 actually closes the
#   service at 10:00 local — not one hour later.
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

    def __init__(self, clock: LocalClock | None = None):
        # Dependency injection with a sensible default — tests can pass
        # a LocalClock(offset_minutes=...) to pin the timezone.
        self._clock = clock or LocalClock()

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
    # EFFECTIVE AVERAGE DURATION  (auto, with manual fallback)
    # Uses the rolling average of recent real wait times for the
    # queue when enough served tickets exist; otherwise falls back
    # to the boss-configured avg_duration (or 10 if unset).
    # This is what makes the boss's manual value a *fallback* rather
    # than the source of truth.
    # ----------------------------------------------------------
    def effective_avg(self, ticket_repo, queue_id: int, schedule) -> int:
        fallback = schedule.avg_duration if schedule else 10
        try:
            return ticket_repo.compute_rolling_avg_duration(queue_id, fallback=fallback)
        except Exception:
            return fallback

    # ----------------------------------------------------------
    # IS SERVICE OPEN NOW
    # Opening/closing are LOCAL wall-clock times, so the comparison
    # uses the LOCAL current time (this is the 1-hour-late fix).
    # ----------------------------------------------------------
    def is_open_now(self, schedule: ServiceSchedule | None) -> bool:
        """
        Return True if the service is currently open based on
        the effective schedule for today.
        Returns False if no schedule is configured.
        """
        if not schedule or not schedule.is_open:
            return False

        now_local = self._clock.local_time()
        return schedule.opening_time <= now_local <= schedule.closing_time

    # ----------------------------------------------------------
    # EXCEEDS CLOSING TIME
    # estimated_serve_at is stored in UTC; closing_time is local.
    # Convert today's local closing moment to UTC, then compare
    # in a single (UTC) frame.
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
        """
        if not schedule or not schedule.is_open:
            return False

        if estimated_serve_at is None:
            return False

        closing_local = datetime.combine(self._clock.local_today(), schedule.closing_time)
        closing_utc   = self._clock.local_to_utc(closing_local)
        est           = _strip_tz(estimated_serve_at)   # stored naive UTC

        return est >= closing_utc

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

        closing_local = datetime.combine(self._clock.local_today(), schedule.closing_time)
        closing_utc   = self._clock.local_to_utc(closing_local)

        return {
            "warning":          len(tickets_exceeding) > 0,
            "closing_time":     str(schedule.closing_time),
            "closing_dt":       ApiTimestamp.to_iso(closing_utc),
            "affected_count":   len(tickets_exceeding),
            "affected_tickets": [
                {
                    "ticket_id":           str(t.id),
                    "code":                t.code,
                    "estimated_serve_at":  ApiTimestamp.to_iso(_strip_tz(t.estimated_serve_at)),
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