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
# =============================================================
class ScheduleService:

    # ----------------------------------------------------------
    # COMPUTE ESTIMATED SERVE TIME
    # Formula:
    #   estimated_serve_at = now + (position × avg_duration_minutes)
    # Called when a ticket is issued and when the queue moves.
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
        base_time defaults to now (UTC).
        """
        base = base_time or datetime.now(timezone.utc)
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

        now_time = datetime.now(timezone.utc).time()
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
        """
        if not schedule or not schedule.is_open:
            return False

        today = datetime.now(timezone.utc).date()
        closing_dt = datetime.combine(
            today,
            schedule.closing_time,
        ).replace(tzinfo=timezone.utc)

        return estimated_serve_at >= closing_dt

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

        today = datetime.now(timezone.utc).date()
        closing_dt = datetime.combine(
            today, schedule.closing_time
        ).replace(tzinfo=timezone.utc)

        return {
            "warning":       len(tickets_exceeding) > 0,
            "closing_time":  str(schedule.closing_time),
            "closing_dt":    closing_dt.isoformat(),
            "affected_count": len(tickets_exceeding),
            "affected_tickets": [
                {
                    "ticket_id":          str(t.id),
                    "code":               t.code,
                    "estimated_serve_at": t.estimated_serve_at.isoformat()
                    if t.estimated_serve_at else None,
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
        Returns tickets whose estimate now exceeds closing time.
        """
        base = base_time or datetime.now(timezone.utc)
        for ticket in tickets:
            if ticket.position is not None:
                ticket.estimated_serve_at = self.compute_estimated_serve_at(
                    ticket.position, avg_duration, base
                )
        return tickets