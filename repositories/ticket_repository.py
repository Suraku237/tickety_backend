from models import db, Ticket


# =============================================================
# TICKET REPOSITORY
# Responsibilities:
#   - Abstract all database operations related to Ticket
#   - Mirror the pattern of UserRepository exactly
# OOP Principle: Single Responsibility, Encapsulation
# =============================================================
class TicketRepository:

    # ----------------------------------------------------------
    # READ
    # ----------------------------------------------------------
    def find_by_id(self, ticket_id: int) -> Ticket | None:
        return Ticket.query.get(ticket_id)

    def find_all_by_user(self, user_id: int) -> list[Ticket]:
        return (Ticket.query
                .filter_by(user_id=user_id)
                .order_by(Ticket.created_at.desc())
                .all())

    def find_all(self) -> list[Ticket]:
        """All tickets — admin view."""
        return Ticket.query.order_by(Ticket.created_at.desc()).all()

    def find_by_status(self, status: str) -> list[Ticket]:
        return (Ticket.query
                .filter_by(status=status)
                .order_by(Ticket.created_at.desc())
                .all())

    def find_by_service(self, service_id: int) -> list[Ticket]:
        return (Ticket.query
                .filter_by(service_id=service_id)
                .order_by(Ticket.created_at.desc())
                .all())

    def find_by_user_and_status(self, user_id: int, status: str) -> list[Ticket]:
        return (Ticket.query
                .filter_by(user_id=user_id, status=status)
                .order_by(Ticket.created_at.desc())
                .all())

    def find_by_user_and_priority(self, user_id: int, priority: str) -> list[Ticket]:
        return (Ticket.query
                .filter_by(user_id=user_id, priority=priority)
                .order_by(Ticket.created_at.desc())
                .all())

    # ----------------------------------------------------------
    # CREATE
    # ----------------------------------------------------------
    def create(
        self,
        user_id:      int,
        title:        str,
        description:  str,
        notes:        str,
        priority:     str,
        service:      str,
        service_code: str,
        service_id:   int | None = None,
    ) -> Ticket:
        """Stage a new Ticket. Does NOT commit."""
        ticket = Ticket(
            user_id      = user_id,
            title        = title,
            description  = description,
            notes        = notes,
            priority     = priority,
            service      = service,
            service_code = service_code,
            service_id   = service_id,
            status       = 'open',
        )
        db.session.add(ticket)
        return ticket

    # ----------------------------------------------------------
    # UPDATE
    # ----------------------------------------------------------
    def update_status(self, ticket: Ticket, status: str) -> Ticket:
        ticket.set_status(status)
        return ticket

    def update_priority(self, ticket: Ticket, priority: str) -> Ticket:
        ticket.set_priority(priority)
        return ticket

    def update_fields(
        self,
        ticket:      Ticket,
        title:       str | None = None,
        description: str | None = None,
        notes:       str | None = None,
        priority:    str | None = None,
        status:      str | None = None,
    ) -> Ticket:
        if title       is not None: ticket.title       = title
        if description is not None: ticket.description = description
        if notes       is not None: ticket.notes       = notes
        if priority    is not None: ticket.set_priority(priority)
        if status      is not None: ticket.set_status(status)
        return ticket

    # ----------------------------------------------------------
    # DELETE
    # ----------------------------------------------------------
    def delete(self, ticket: Ticket):
        db.session.delete(ticket)

    # ----------------------------------------------------------
    # TRANSACTION HELPERS
    # ----------------------------------------------------------
    def save(self):       db.session.commit()
    def rollback(self):   db.session.rollback()
    def flush(self):      db.session.flush()
