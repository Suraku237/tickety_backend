from models import db, Admin


# =============================================================
# ADMIN REPOSITORY
# Responsibilities:
#   - Abstract all database operations related to Admin
#   - Provide create and lookup methods consumed by ServiceController
# OOP Principle: Single Responsibility, Encapsulation
# =============================================================
class AdminRepository:

    # Valid roles as a class-level constant — single source of truth
    ROLE_BOSS    = 'boss'
    ROLE_MANAGER = 'manager'
    ROLE_AGENT   = 'agent'

    VALID_ROLES = {ROLE_BOSS, ROLE_MANAGER, ROLE_AGENT}

    def find_by_user_and_service(self, user_id: int, service_id: int) -> Admin | None:
        """Find an Admin entry for a specific user + service combination."""
        return Admin.query.filter_by(user_id=user_id, service_id=service_id).first()

    def find_by_service(self, service_id: int) -> list[Admin]:
        """Return all admin entries belonging to a service."""
        return Admin.query.filter_by(service_id=service_id).all()

    def find_by_user(self, user_id: int) -> list[Admin]:
        """Return all service roles held by a user."""
        return Admin.query.filter_by(user_id=user_id).all()

    def find_boss(self, service_id: int) -> Admin | None:
        """Find the boss (owner) entry for a given service."""
        return Admin.query.filter_by(
            service_id=service_id, admin_role=self.ROLE_BOSS
        ).first()

    def create(self, user_id: int, service_id: int, admin_role: str) -> Admin:
        """
        Instantiate a new Admin entry and stage it for insertion.
        Validates that the role is one of the allowed values.
        Does NOT commit — caller controls the transaction.
        """
        if admin_role not in self.VALID_ROLES:
            raise ValueError(f"Invalid admin_role '{admin_role}'. Must be one of {self.VALID_ROLES}")

        admin = Admin(user_id=user_id, service_id=service_id, admin_role=admin_role)
        db.session.add(admin)
        return admin

    def save(self):
        """Commit the current session transaction."""
        db.session.commit()

    def rollback(self):
        """Rollback the current session on failure."""
        db.session.rollback()