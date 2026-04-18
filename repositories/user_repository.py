from models import db, User


# =============================================================
# USER REPOSITORY
# Responsibilities:
#   - Abstract all database operations related to User
#   - Provide clean query methods consumed by AuthController
# OOP Principle: Single Responsibility, Encapsulation
#
# NOTE ON create():
#   The signature now accepts hashed_password (bytes) directly
#   instead of a raw password string. The hashing happens in
#   AuthController (via PasswordService) before Phase 1
#   (register), so the same hash can be reused in Phase 2
#   (verify_email) without ever re-hashing or storing the
#   plain password anywhere between the two phases.
# =============================================================
class UserRepository:

    def find_by_email(self, email: str) -> User | None:
        """Find and return a User by email, or None if not found."""
        return User.query.filter_by(email=email).first()

    def find_by_username(self, username: str) -> User | None:
        """Find and return a User by username, or None if not found."""
        return User.query.filter_by(username=username).first()

    def find_by_role(self, role: str) -> list[User]:
        """Return all users matching the given role ('client' or 'admin')."""
        return User.query.filter_by(role=role).all()

    def create(
        self,
        username:        str,
        email:           str,
        hashed_password: bytes,
        role:            str,
    ) -> User:
        """
        Instantiate a new User and stage it for insertion.

        Accepts hashed_password (bytes from bcrypt) directly —
        the caller (AuthController.verify_email) pulls this from
        the PendingRegistration row, which stored it during Phase 1.

        Does NOT commit — caller controls the transaction.
        """
        user = User(
            username = username,
            email    = email,
            password = hashed_password,
            role     = role,
            verified = False,   # caller calls user.mark_verified() after create()
        )
        db.session.add(user)
        return user

    def save(self):
        """Commit the current session transaction."""
        db.session.commit()

    def rollback(self):
        """Rollback the current session on failure."""
        db.session.rollback()

    def flush(self):
        """Flush staged changes without committing."""
        db.session.flush()