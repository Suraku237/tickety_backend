from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone

db = SQLAlchemy()


# =============================================================
# USER MODEL
# Responsibilities:
#   - Store verified user credentials, profile data and role
#   - ONLY created AFTER email verification succeeds
# OOP Principle: Encapsulation, Single Responsibility
# =============================================================
class User(db.Model):
    __tablename__ = 'users'

    id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username   = db.Column(db.String(50),    unique=True, nullable=False)
    email      = db.Column(db.String(120),   unique=True, nullable=False)
    password   = db.Column(db.LargeBinary,   nullable=False)   # bcrypt bytes
    role       = db.Column(db.String(20),    nullable=False, default='client')
    verified   = db.Column(db.Boolean,       default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    owned_services = db.relationship('Service', backref='owner', lazy=True)
    admin_entries  = db.relationship('Admin',   backref='user',  lazy=True)

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
        return f"<User id={self.id} username={self.username} role={self.role}>"


# =============================================================
# PENDING REGISTRATION MODEL
# Responsibilities:
#   - Temporarily hold registration data BEFORE email is verified
#   - Stores hashed password so it is never transmitted twice
#   - Deleted immediately after successful verification
#   - Expired rows can be cleaned up by a scheduled job later
#
# OOP Principle: Encapsulation, Single Responsibility
#
# WHY THIS EXISTS:
#   Without this model, a connection error after User creation but
#   before OTP delivery leaves an unverified ghost User in the DB.
#   The user cannot re-register (email already taken) and never
#   received the code — they are permanently locked out.
#
#   With this model:
#     - register()      → creates PendingRegistration + sends OTP
#     - verify_email()  → on success, creates real User + deletes pending row
#     - resend_otp()    → updates the pending row's code + resends
#   A failed or interrupted registration leaves only a pending row,
#   which expires naturally. The user can restart the flow freely.
# =============================================================
class PendingRegistration(db.Model):
    __tablename__ = 'pending_registrations'

    id              = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    username        = db.Column(db.String(50),  nullable=False)
    email           = db.Column(db.String(120), unique=True, nullable=False)
    hashed_password = db.Column(db.LargeBinary, nullable=False)
    role            = db.Column(db.String(20),  nullable=False, default='client')
    code            = db.Column(db.String(6),   nullable=False)
    expire_at       = db.Column(db.DateTime,    nullable=False)
    created_at      = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )

    def is_expired(self) -> bool:
        """Return True if this OTP code has passed its expiry time."""
        return self.expire_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc)

    def update_code(self, new_code: str, new_expiry: datetime):
        """Replace the OTP with a fresh code and expiry (used by resend)."""
        self.code      = new_code
        self.expire_at = new_expiry

    def to_user_payload(self) -> dict:
        """
        Return the fields needed to create a real User row.
        Called by AuthController.verify_email() after code is confirmed.
        """
        return {
            "username":        self.username,
            "email":           self.email,
            "hashed_password": self.hashed_password,
            "role":            self.role,
        }

    def __repr__(self):
        return (
            f"<PendingRegistration email={self.email} "
            f"role={self.role} expires={self.expire_at}>"
        )


# =============================================================
# RESET CODE MODEL
# Responsibilities:
#   - Store OTP for password reset flows (existing / future feature)
#   - Intentionally kept separate from PendingRegistration:
#       ResetCode   → applies to EXISTING verified users
#       PendingRegistration → applies to UNVERIFIED newcomers
# OOP Principle: Encapsulation, Single Responsibility
# =============================================================
class ResetCode(db.Model):
    __tablename__ = 'resets'

    id        = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    email     = db.Column(db.String(120), unique=True, nullable=False)
    code      = db.Column(db.String(6),   nullable=False)
    expire_at = db.Column(db.DateTime,    nullable=False)

    def is_expired(self) -> bool:
        """Return True if this OTP code has passed its expiry time."""
        return self.expire_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc)

    def update_code(self, new_code: str, new_expiry: datetime):
        """Replace the existing OTP with a fresh code and expiry."""
        self.code      = new_code
        self.expire_at = new_expiry

    def __repr__(self):
        return f"<ResetCode email={self.email} expires={self.expire_at}>"


# =============================================================
# SERVICE MODEL
# Responsibilities:
#   - Store the enterprise / business created by a boss admin
# OOP Principle: Encapsulation, Single Responsibility
# =============================================================
class Service(db.Model):
    __tablename__ = 'services'

    id         = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    name       = db.Column(db.String(120), nullable=False)
    owner_id   = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    admin_entries = db.relationship(
        'Admin', backref='service', lazy=True, cascade='all, delete-orphan'
    )

    def to_dict(self):
        return {
            "service_id":   str(self.id),
            "service_name": self.name,
            "owner_id":     str(self.owner_id),
        }

    def __repr__(self):
        return f"<Service id={self.id} name={self.name} owner_id={self.owner_id}>"


# =============================================================
# ADMIN MODEL
# Responsibilities:
#   - Link a User to a Service with a specific admin role
#   - admin_role: 'boss' | 'manager' | 'agent'
# OOP Principle: Encapsulation, Single Responsibility
# =============================================================
class Admin(db.Model):
    __tablename__ = 'admins'

    id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id    = db.Column(
        db.Integer,
        db.ForeignKey('users.id',    ondelete='CASCADE'),
        nullable=False,
    )
    service_id = db.Column(
        db.Integer,
        db.ForeignKey('services.id', ondelete='CASCADE'),
        nullable=False,
    )
    admin_role = db.Column(db.String(20), nullable=False, default='agent')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'service_id', name='uq_user_service'),
    )

    def is_boss(self):    return self.admin_role == 'boss'
    def is_manager(self): return self.admin_role == 'manager'
    def is_agent(self):   return self.admin_role == 'agent'

    def to_dict(self):
        return {
            "admin_id":   str(self.id),
            "user_id":    str(self.user_id),
            "service_id": str(self.service_id),
            "admin_role": self.admin_role,
        }

    def __repr__(self):
        return (
            f"<Admin user_id={self.user_id} "
            f"service_id={self.service_id} role={self.admin_role}>"
        )