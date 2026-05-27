from models import db, Ticket
from datetime import date


# =============================================================
# TICKET REPOSITORY
# Responsibilities:
#   - Abstract all DB operations for Ticket
# OOP Principle: Single Responsibility, Encapsulation
#
# NOTE ON ORDERING:
#   MySQL does not support NULLS FIRST / NULLS LAST syntax.
#   Wherever we need NULLs last (position ordering), we use
#   a CASE expression:
#     CASE WHEN position IS NULL THEN 9999 ELSE position END ASC
#   This pushes NULL positions (served/suspended/carried_over
#   tickets) to the end of the result set.
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

    # ----------------------------------------------------------
    # SHARED: MySQL-safe position ordering expression
    # Puts NULL positions at the end (9999), then sorts by issued_at
    # ----------------------------------------------------------
    @staticmethod
    def _position_order():
        """
        Returns a SQLAlchemy order expression that sorts tickets
        by position ascending with NULLs last — MySQL compatible.
        """
        return db.case(
            (Ticket.position == None, 9999),
            else_=Ticket.position
        ).asc()

    def find_by_id(self, ticket_id: int) -> Ticket | None:
        return Ticket.query.get(ticket_id)

    def find_by_queue(self, queue_id: int) -> list[Ticket]:
        """
        All non-served tickets in a queue, ordered by position
        (NULLs last) then issued_at.
        """
        return (Ticket.query
                .filter_by(queue_id=queue_id)
                .filter(Ticket.status != self.STATUS_SERVED)
                .order_by(
                    self._position_order(),
                    Ticket.issued_at.asc()
                )
                .all())

    def find_by_service(self, service_id: int) -> list[Ticket]:
        """
        All active/pending/suspended tickets for a service
        (counter view), ordered by position then issued_at.
        """
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

    def find_carried_over(self, service_id: int) -> list[Ticket]:
        """
        All carried-over tickets for a service, ordered by
        original carried_over_date then issued_at.
        """
        return (Ticket.query
                .filter_by(service_id=service_id, status=self.STATUS_CARRIED_OVER)
                .order_by(
                    Ticket.carried_over_date.asc(),
                    Ticket.issued_at.asc()
                )
                .all())

    def find_serving(self, service_id: int) -> Ticket | None:
        """The ticket currently being served at this service."""
        return Ticket.query.filter_by(
            service_id=service_id,
            status=self.STATUS_ACTIVE,
            position=0,
        ).first()

    def next_position(self, queue_id: int) -> int:
        """Return the next available position in a queue."""
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
        """Return the next sequential code number for a queue."""
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
        Re-assign sequential positions (0, 1, 2…) to all
        pending/active tickets in a queue after a swap or delete.
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

    def delete(self, ticket: Ticket):
        db.session.delete(ticket)

    def save(self):     db.session.commit()
    def rollback(self): db.session.rollback()
    def flush(self):    db.session.flush()