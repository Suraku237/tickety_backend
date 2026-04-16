from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone

db = SQLAlchemy()


# =============================================================
# USER MODEL
# Responsibilities:
#   - Store user credentials, profile data and role
#   - Provide instance-level methods for state changes
# OOP Principle: Encapsulation, Single Responsibility
# =============================================================
class User(db.Model):
    __tablename__ = 'users'

    id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username   = db.Column(db.String(50), unique=True, nullable=False)
    email      = db.Column(db.String(120), unique=True, nullable=False)
    password   = db.Column(db.LargeBinary, nullable=False)  # bcrypt bytes
    role       = db.Column(db.String(20), nullable=False, default='client')  # 'client' | 'admin'
    verified   = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def mark_verified(self):
        """Mark this user's email as verified."""
        self.verified = True

    def is_verified(self):
        """Return True if the user has verified their email."""
        return self.verified

    def is_client(self):
        """Return True if this user is a client (mobile app user)."""
        return self.role == 'client'

    def is_admin(self):
        """Return True if this user is an admin (web app user)."""
        return self.role == 'admin'

    def to_dict(self):
        """Serialize user data safe for API responses (no password)."""
        return {
            "user_id":  str(self.id),
            "username": self.username,
            "email":    self.email,
            "role":     self.role,
        }

    def __repr__(self):
        return f"<User id={self.id} username={self.username} role={self.role} verified={self.verified}>"


# =============================================================
# RESET CODE MODEL
# Responsibilities:
#   - Store and validate OTP expiry
#   - Provide expiry check as an instance method
# OOP Principle: Encapsulation, Single Responsibility
# =============================================================
class ResetCode(db.Model):
    __tablename__ = 'resets'

    id        = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email     = db.Column(db.String(120), unique=True, nullable=False)
    code      = db.Column(db.String(6), nullable=False)
    expire_at = db.Column(db.DateTime, nullable=False)

    def is_expired(self):
        """Return True if this OTP code has passed its expiry time."""
        return self.expire_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc)

    def update_code(self, new_code, new_expiry):
        """Replace the existing OTP with a fresh code and expiry."""
        self.code      = new_code
        self.expire_at = new_expiry

    def __repr__(self):
        return f"<ResetCode email={self.email} expires={self.expire_at}>"