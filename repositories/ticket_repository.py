from models import db, Ticket
from datetime import date


# =============================================================
# TICKET REPOSITORY
# Responsibilities:
#   - Abstract all DB operations for Ticket
# OOP Principle: Single Responsibility, Encapsulation
# =============================================================
class TicketRepository:

    # Status constants
    STATUS_PENDING      = 'pending'
    STATUS_ACTIVE       = 'active'
    STATUS_SUSPENDED    = 'suspended'
    STATUS_SERVED       = 'served'
    STATUS_CARRIED_OVER = 'carried_over'

    # Priority constants
    PRIORITY_NORMAL = 'normal'
    PRIORITY_HIGH   = 'high'
    PRIORITY_URGENT = 'urgent'

    VALID_STATUSES   = {STATUS_PENDING, STATUS_ACTIVE, STATUS_SUSPENDED, STATUS_SERVED, STATUS_CARRIED_OVER}
    VALID_PRIORITIES = {PRIORITY_NORMAL, PRIORITY_HIGH, PRIORITY_URGENT}

    # Minimum number of real served tickets required before we
    # trust the rolling average over the manually configured value.
    ROLLING_AVG_MIN_SAMPLES = 5

    # How many recent served tickets to include in the rolling average.
    # Keeps the estimate responsive to recent pace changes rather than
    # being dragged down by very old data.
    ROLLING_AVG_WINDOW = 20

    # ----------------------------------------------------------
    # SHARED: MySQL-safe position ordering expression
    # ----------------------------------------------------------
    @staticmethod
    def _position_order():
        return db.case(
            (Ticket.position == None, 9999),
            else_=Ticket.position
        ).asc()

    def find_by_id(self, ticket_id: int) -> Ticket | None:
        return Ticket.query.get(ticket_id)

    def find_by_queue(self, queue_id: int) -> list[Ticket]:
        return (Ticket.query
                .filter_by(queue_id=queue_id)
                .filter(Ticket.status != self.STATUS_SERVED)
                .order_by(
                    self._position_order(),
                    Ticket.issued_at.asc()
                )
                .all())

    def find_by_service(self, service_id: int) -> list[Ticket]:
        return (Ticket.query
                .filter_by(service_id=service_id)
                .filter(Ticket.status.in_([
                    self.STATUS_ACTIVE,
                    self.STATUS_PENDING,
                    self.STATUS_SUSPENDED,
                ]))
                .order_by(
                    self._position_order(),
                    Ticket.issued_at.asc()
                )
                .all())

    def find_by_customer_identifier(self, customer_identifier: str) -> list[Ticket]:
        """
        Find all in-queue (non-served) tickets for a customer identifier.
        Case-insensitive so email capitalisation differences still match.
        Consumed by the mobile app's "my tickets" view.
        """
        return (Ticket.query
                .filter(
                    db.func.lower(Ticket.customer_identifier) ==
                    customer_identifier.strip().lower()
                )
                .filter(Ticket.status != self.STATUS_SERVED)
                .order_by(
                    self._position_order(),
                    Ticket.issued_at.asc()
                )
                .all())

    def has_visited(self, service_id: int, identifier: str) -> bool:
        """
        True if this customer identifier has ever taken a ticket at the
        service (any status, including served). Powers the mobile browse
        page's visited/not-visited distinction.
        """
        if not identifier:
            return False
        return (Ticket.query
                .filter(db.func.lower(Ticket.customer_identifier) == identifier.strip().lower())
                .filter(Ticket.service_id == service_id)
                .first()) is not None

    def find_carried_over(self, service_id: int) -> list[Ticket]:
        return (Ticket.query
                .filter_by(service_id=service_id, status=self.STATUS_CARRIED_OVER)
                .order_by(
                    Ticket.carried_over_date.asc(),
                    Ticket.issued_at.asc()
                )
                .all())

    def find_serving(self, service_id: int) -> Ticket | None:
        return Ticket.query.filter_by(
            service_id=service_id,
            status=self.STATUS_ACTIVE,
            position=0,
        ).first()

    def next_position(self, queue_id: int) -> int:
        last = (Ticket.query
                .filter_by(queue_id=queue_id)
                .filter(Ticket.status.in_([
                    self.STATUS_PENDING,
                    self.STATUS_ACTIVE,
                ]))
                .filter(Ticket.position != None)
                .order_by(Ticket.position.desc())
                .first())
        return (last.position + 1) if last else 0

    def next_code_number(self, queue_id: int) -> int:
        count = Ticket.query.filter_by(queue_id=queue_id).count()
        return count + 1

    def create(self, queue_id: int, service_id: int, code: str,
               position: int, customer_identifier: str = None,
               estimated_serve_at=None) -> Ticket:
        """Stage a new Ticket. Does NOT commit."""
        ticket = Ticket(
            queue_id            = queue_id,
            service_id          = service_id,
            code                = code,
            position            = position,
            customer_identifier = customer_identifier,
            estimated_serve_at  = estimated_serve_at,
        )
        db.session.add(ticket)
        return ticket

    def reindex_positions(self, queue_id: int):
        """
        Re-assign sequential positions to all pending/active tickets.
        Does NOT commit.
        """
        tickets = (Ticket.query
                   .filter_by(queue_id=queue_id)
                   .filter(Ticket.status.in_([
                       self.STATUS_PENDING,
                       self.STATUS_ACTIVE,
                   ]))
                   .filter(Ticket.position != None)
                   .order_by(
                       self._position_order(),
                       Ticket.issued_at.asc()
                   )
                   .all())
        for i, t in enumerate(tickets):
            t.position = i

    # ----------------------------------------------------------
    # ROLLING AVERAGE DURATION
    # ----------------------------------------------------------
    def compute_rolling_avg_duration(
        self,
        queue_id: int,
        fallback: int = 10,
    ) -> int:
        """
        Compute the average real wait time (in minutes) from the
        most recent ROLLING_AVG_WINDOW served tickets in this queue
        that have both issued_at and called_at stamped.

        called_at is set the moment the agent calls the ticket
        (status → active), so:
            real_wait = called_at − issued_at

        Falls back to `fallback` (the manually configured
        avg_duration) when fewer than ROLLING_AVG_MIN_SAMPLES
        real samples exist — so cold-start behaviour is unchanged.

        Returns an integer number of minutes (minimum 1).
        """
        recent_served = (
            Ticket.query
            .filter_by(queue_id=queue_id, status=self.STATUS_SERVED)
            .filter(Ticket.called_at  != None)
            .filter(Ticket.issued_at  != None)
            .order_by(Ticket.called_at.desc())
            .limit(self.ROLLING_AVG_WINDOW)
            .all()
        )

        # Not enough data yet — use the manual fallback
        if len(recent_served) < self.ROLLING_AVG_MIN_SAMPLES:
            return fallback

        waits = [
            t.actual_wait_minutes()
            for t in recent_served
            if t.actual_wait_minutes() is not None
        ]

        if not waits:
            return fallback

        avg = sum(waits) / len(waits)
        return max(1, round(avg))   # never go below 1 minute

    def delete(self, ticket: Ticket):
        db.session.delete(ticket)

    def save(self):     db.session.commit()
    def rollback(self): db.session.rollback()
    def flush(self):    db.session.flush()  # ✅