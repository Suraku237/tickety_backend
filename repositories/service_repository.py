from models import db, Service


# =============================================================
# SERVICE REPOSITORY
# Responsibilities:
#   - Abstract all database operations related to Service
#   - Provide create and lookup methods consumed by ServiceController
# OOP Principle: Single Responsibility, Encapsulation
# =============================================================
class ServiceRepository:

    def find_by_id(self, service_id: int) -> Service | None:
        """Find a Service by its primary key."""
        return Service.query.get(service_id)

    def find_by_owner(self, owner_id: int) -> list[Service]:
        """Return all services owned by a given user."""
        return Service.query.filter_by(owner_id=owner_id).all()

    def find_by_name_and_owner(self, name: str, owner_id: int) -> Service | None:
        """Check if a user already registered a service with this exact name."""
        return Service.query.filter_by(name=name, owner_id=owner_id).first()

    def create(self, name: str, owner_id: int) -> Service:
        """
        Instantiate a new Service and stage it for insertion.
        Does NOT commit — caller controls the transaction.
        """
        service = Service(name=name, owner_id=owner_id)
        db.session.add(service)
        return service

    def save(self):
        """Commit the current session transaction."""
        db.session.commit()

    def rollback(self):
        """Rollback the current session on failure."""
        db.session.rollback()

    def flush(self):
        """Flush staged changes without committing (needed to get service.id before commit)."""
        db.session.flush()