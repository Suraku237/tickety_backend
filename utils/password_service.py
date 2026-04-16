import bcrypt


# =============================================================
# PASSWORD SERVICE
# Responsibilities:
#   - Hash plain-text passwords securely using bcrypt
#   - Verify a plain-text password against a stored hash
# OOP Principle: Single Responsibility, Encapsulation
# =============================================================
class PasswordService:

    def hash(self, plain_password: str) -> bytes:
        """Hash a plain-text password and return the bcrypt bytes."""
        return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt())

    def verify(self, plain_password: str, hashed_password: bytes) -> bool:
        """Return True if the plain password matches the stored hash."""
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password)