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

    # Relationship — one user has many tickets
    tickets    = db.relationship('Ticket', backref='owner', lazy=True,
                                 cascade='all, delete-orphan')

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


# =============================================================
# TICKET MODEL
# Responsibilities:
#   - Persist all ticket data submitted from the mobile app
#   - Track lifecycle: status transitions and timestamps
#   - Link to the owning user via foreign key
# OOP Principle: Encapsulation, Single Responsibility
#
# Status values : 'open' | 'pending' | 'closed'
# Priority values: 'low'  | 'medium'  | 'high' | 'urgent'
# =============================================================
class Ticket(db.Model):
    __tablename__ = 'tickets'

    id           = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Core fields supplied by the mobile client
    title        = db.Column(db.String(200), nullable=False)
    description  = db.Column(db.Text, nullable=False)
    notes        = db.Column(db.Text, nullable=True, default='')
    priority     = db.Column(db.String(20), nullable=False, default='medium')
    service      = db.Column(db.String(100), nullable=False)
    service_code = db.Column(db.String(500), nullable=True, default='')  # raw QR/URL value

    # Lifecycle
    status       = db.Column(db.String(20), nullable=False, default='open')
    created_at   = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at   = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                             onupdate=lambda: datetime.now(timezone.utc))

    # ----------------------------------------------------------
    # State transitions
    # ----------------------------------------------------------
    def open(self):
        """Transition ticket back to open."""
        self.status     = 'open'
        self.updated_at = datetime.now(timezone.utc)

    def pend(self):
        """Transition ticket to pending (being processed)."""
        self.status     = 'pending'
        self.updated_at = datetime.now(timezone.utc)

    def close(self):
        """Transition ticket to closed (resolved)."""
        self.status     = 'closed'
        self.updated_at = datetime.now(timezone.utc)

    def set_status(self, status: str):
        """
        Generic status setter — validates allowed values.
        Raises ValueError for unrecognised statuses.
        """
        allowed = {'open', 'pending', 'closed'}
        if status not in allowed:
            raise ValueError(f"Invalid status '{status}'. Allowed: {allowed}")
        self.status     = status
        self.updated_at = datetime.now(timezone.utc)

    def set_priority(self, priority: str):
        """
        Generic priority setter — validates allowed values.
        Raises ValueError for unrecognised priorities.
        """
        allowed = {'low', 'medium', 'high', 'urgent'}
        if priority not in allowed:
            raise ValueError(f"Invalid priority '{priority}'. Allowed: {allowed}")
        self.priority = priority

    # ----------------------------------------------------------
    # Serialisation
    # ----------------------------------------------------------
    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation of this ticket."""
        return {
            "ticket_id":    str(self.id),
            "user_id":      str(self.user_id),
            "title":        self.title,
            "description":  self.description,
            "notes":        self.notes or '',
            "priority":     self.priority,
            "service":      self.service,
            "service_code": self.service_code or '',
            "status":       self.status,
            "created_at":   self.created_at.isoformat() if self.created_at else None,
            "updated_at":   self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return (f"<Ticket id={self.id} title={self.title!r} "
                f"status={self.status} priority={self.priority}>")
