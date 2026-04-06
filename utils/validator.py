import re


# =============================================================
# VALIDATOR
# Responsibilities:
#   - Centralize and encapsulate all input validation rules
#   - Return clear error messages for invalid inputs
# OOP Principle: Single Responsibility, Encapsulation
# =============================================================
class Validator:

    MIN_USERNAME_LENGTH = 3
    MIN_PASSWORD_LENGTH = 6

    def validate_username(self, username: str) -> str | None:
        """Return an error message if username is invalid, else None."""
        if not username or len(username) < self.MIN_USERNAME_LENGTH:
            return f"Username must be at least {self.MIN_USERNAME_LENGTH} characters"
        return None

    def validate_email(self, email: str) -> str | None:
        """Return an error message if email format is invalid, else None."""
        pattern = r"[^@]+@[^@]+\.[^@]+"
        if not email or not re.match(pattern, email):
            return "Invalid email format"
        return None

    def validate_password(self, password: str) -> str | None:
        """Return an error message if password does not meet requirements, else None."""
        if not password or len(password) < self.MIN_PASSWORD_LENGTH:
            return f"Password must be at least {self.MIN_PASSWORD_LENGTH} characters"
        if not any(c.isdigit() for c in password):
            return "Password must contain at least one digit"
        return None

    def validate_registration(
        self, username: str, email: str, password: str
    ) -> str | None:
        """
        Run all registration validations in order.
        Returns the first error found, or None if all pass.
        """
        return (
            self.validate_username(username)
            or self.validate_email(email)
            or self.validate_password(password)
        )