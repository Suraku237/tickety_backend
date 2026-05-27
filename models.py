from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone
import uuid

db = SQLAlchemy()


# =============================================================
# USER MODEL
# =============================================================
class User(db.Model):
    __tablename__ = 'users'

    id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username   = db.Column(db.String(50),  unique=True, nullable=False)
    email      = db.Column(db.String(120), unique=True, nullable=False)
    password   = db.Column(db.LargeBinary, nullable=False)
    role       = db.Column(db.String(20),  nullable=False, default='client')
    verified   = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    owned_services = db.relationship('Service', backref='owner', lazy=True)
    admin_entries  = db.relationship('Admin',   backref='user',  lazy=True)

    def mark_verified(self): self.verified = True
    def is_verified(self):   return self.verified
    def is_client(self):     return self.role == 'client'
    def is_admin(self):      return self.role == 'admin'

    def to_dict(self):
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
    created_at      = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def is_expired(self):
        return self.expire_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc)

    def update_code(self, new_code, new_expiry):
        self.code      = new_code
        self.expire_at = new_expiry

    def to_user_payload(self):
        return {
            "username":        self.username,
            "email":           self.email,
            "hashed_password": self.hashed_password,
            "role":            self.role,
        }

    def __repr__(self):
        return f"<PendingRegistration email={self.email} role={self.role}>"


# =============================================================
# RESET CODE MODEL
# =============================================================
class ResetCode(db.Model):
    __tablename__ = 'resets'

    id        = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    email     = db.Column(db.String(120), unique=True, nullable=False)
    code      = db.Column(db.String(6),   nullable=False)
    expire_at = db.Column(db.DateTime,    nullable=False)

    def is_expired(self):
        return self.expire_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc)

    def update_code(self, new_code, new_expiry):
        self.code      = new_code
        self.expire_at = new_expiry

    def __repr__(self):
        return f"<ResetCode email={self.email} expires={self.expire_at}>"


# =============================================================
# SERVICE MODEL
# =============================================================
class Service(db.Model):
    __tablename__ = 'services'

    id         = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    name       = db.Column(db.String(120), nullable=False)
    owner_id   = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    admin_entries = db.relationship('Admin',           backref='service',  lazy=True, cascade='all, delete-orphan')
    queues        = db.relationship('Queue',           backref='service',  lazy=True, cascade='all, delete-orphan')
    schedules     = db.relationship('ServiceSchedule', backref='service',  lazy=True, cascade='all, delete-orphan')
    invite_tokens = db.relationship('InviteToken',     backref='service',  lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            "service_id":   str(self.id),
            "service_name": self.name,
            "owner_id":     str(self.owner_id),
        }

    def __repr__(self):
        return f"<Service id={self.id} name={self.name}>"


# =============================================================
# ADMIN MODEL
# =============================================================
class Admin(db.Model):
    __tablename__ = 'admins'

    id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id',    ondelete='CASCADE'), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id', ondelete='CASCADE'), nullable=False)
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
        return f"<Admin user_id={self.user_id} service_id={self.service_id} role={self.admin_role}>"


# =============================================================
# QUEUE MODEL
# Responsibilities:
#   - Represent a named queue within a service
#   - Hold a unique join_token that forms the QR link
#     customers scan to join: /join/<join_token>
# OOP Principle: Encapsulation, Single Responsibility
# =============================================================
class Queue(db.Model):
    __tablename__ = 'queues'

    id         = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id', ondelete='CASCADE'), nullable=False)
    name       = db.Column(db.String(120), nullable=False)
    code       = db.Column(db.String(20),  nullable=False)      # short human code e.g. GEN-01
    color      = db.Column(db.String(10),  nullable=False, default='#DC0F0F')
    join_token = db.Column(db.String(36),  unique=True, nullable=False,
                           default=lambda: str(uuid.uuid4()))   # UUID for the QR URL
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    tickets = db.relationship('Ticket', backref='queue', lazy=True, cascade='all, delete-orphan')

    def active_count(self):
        return sum(1 for t in self.tickets if t.status == 'active')

    def pending_count(self):
        return sum(1 for t in self.tickets if t.status == 'pending')

    def to_dict(self, base_url=''):
        return {
            "queue_id":   str(self.id),
            "service_id": str(self.service_id),
            "name":       self.name,
            "code":       self.code,
            "color":      self.color,
            "join_token": self.join_token,
            "join_url":   f"{base_url}/join/{self.join_token}",
            "active":     self.active_count(),
            "pending":    self.pending_count(),
        }

    def __repr__(self):
        return f"<Queue id={self.id} name={self.name} code={self.code}>"


# =============================================================
# TICKET MODEL
# Responsibilities:
#   - Represent a single customer ticket in a queue
#   - Track position, status, priority and timing
#   - status: 'pending' | 'active' | 'suspended' |
#             'served' | 'carried_over'
#   - priority: 'normal' | 'high' | 'urgent'
# OOP Principle: Encapsulation, Single Responsibility
# =============================================================
class Ticket(db.Model):
    __tablename__ = 'tickets'

    id                  = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    queue_id            = db.Column(db.Integer, db.ForeignKey('queues.id',    ondelete='CASCADE'), nullable=False)
    service_id          = db.Column(db.Integer, db.ForeignKey('services.id',  ondelete='CASCADE'), nullable=False)
    code                = db.Column(db.String(20),  nullable=False)       # e.g. GEN-047
    status              = db.Column(db.String(20),  nullable=False, default='pending')
    priority            = db.Column(db.String(20),  nullable=False, default='normal')
    position            = db.Column(db.Integer,     nullable=True)        # NULL for served/carried_over
    counter             = db.Column(db.String(20),  nullable=True)        # which counter is serving
    customer_identifier = db.Column(db.String(120), nullable=True)        # phone/email from mobile join
    issued_at           = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    estimated_serve_at  = db.Column(db.DateTime, nullable=True)           # computed on issue + on queue move
    carried_over_date   = db.Column(db.Date,     nullable=True)           # original date if carried over

    def is_carried_over(self): return self.status == 'carried_over'
    def is_pending(self):      return self.status == 'pending'
    def is_active(self):       return self.status == 'active'
    def is_suspended(self):    return self.status == 'suspended'
    def is_served(self):       return self.status == 'served'

    def to_dict(self):
        return {
            "ticket_id":           str(self.id),
            "queue_id":            str(self.queue_id),
            "service_id":          str(self.service_id),
            "code":                self.code,
            "status":              self.status,
            "priority":            self.priority,
            "position":            self.position,
            "counter":             self.counter,
            "customer_identifier": self.customer_identifier,
            "issued_at":           self.issued_at.isoformat() if self.issued_at else None,
            "estimated_serve_at":  self.estimated_serve_at.isoformat() if self.estimated_serve_at else None,
            "carried_over_date":   str(self.carried_over_date) if self.carried_over_date else None,
        }

    def __repr__(self):
        return f"<Ticket id={self.id} code={self.code} status={self.status} pos={self.position}>"


# =============================================================
# INVITE TOKEN MODEL
# Responsibilities:
#   - Store a one-time invite link generated by a boss/manager
#   - The token encodes the target admin_role
#   - Consumed (marked used) when someone registers via the link
# OOP Principle: Encapsulation, Single Responsibility
# =============================================================
class InviteToken(db.Model):
    __tablename__ = 'invite_tokens'

    id         = db.Column(db.Integer,    primary_key=True, autoincrement=True)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id', ondelete='CASCADE'), nullable=False)
    token      = db.Column(db.String(36), unique=True, nullable=False,
                           default=lambda: str(uuid.uuid4()))
    admin_role = db.Column(db.String(20), nullable=False, default='agent')  # 'manager' | 'agent'
    used       = db.Column(db.Boolean,    nullable=False, default=False)
    expires_at = db.Column(db.DateTime,   nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def is_expired(self):
        return self.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc)

    def is_valid(self):
        return not self.used and not self.is_expired()

    def consume(self):
        self.used = True

    def to_dict(self, base_url=''):
        return {
            "invite_id":  str(self.id),
            "service_id": str(self.service_id),
            "token":      self.token,
            "invite_url": f"{base_url}/invite/{self.token}",
            "admin_role": self.admin_role,
            "used":       self.used,
            "expires_at": self.expires_at.isoformat(),
        }

    def __repr__(self):
        return f"<InviteToken service_id={self.service_id} role={self.admin_role} used={self.used}>"


# =============================================================
# SERVICE SCHEDULE MODEL
# Responsibilities:
#   - Store opening/closing times and working days for a service
#   - day_of_week = NULL  → general default applied to all days
#   - day_of_week = 0–6   → per-day override (0=Mon … 6=Sun)
#   - Boss sets a general schedule first; can override any day
# OOP Principle: Encapsulation, Single Responsibility
# =============================================================
class ServiceSchedule(db.Model):
    __tablename__ = 'service_schedules'

    id              = db.Column(db.Integer, primary_key=True, autoincrement=True)
    service_id      = db.Column(db.Integer, db.ForeignKey('services.id', ondelete='CASCADE'), nullable=False)
    day_of_week     = db.Column(db.Integer, nullable=True)      # NULL = general; 0=Mon … 6=Sun
    is_open         = db.Column(db.Boolean, nullable=False, default=True)
    opening_time    = db.Column(db.Time,    nullable=False)
    closing_time    = db.Column(db.Time,    nullable=False)
    avg_duration    = db.Column(db.Integer, nullable=False, default=10)  # minutes per ticket
    created_at      = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at      = db.Column(db.DateTime,
                                default=lambda: datetime.now(timezone.utc),
                                onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        # Only one general row (NULL) or one row per specific day per service
        db.UniqueConstraint('service_id', 'day_of_week', name='uq_service_schedule_day'),
    )

    def to_dict(self):
        return {
            "schedule_id":   str(self.id),
            "service_id":    str(self.service_id),
            "day_of_week":   self.day_of_week,   # None = general
            "is_open":       self.is_open,
            "opening_time":  str(self.opening_time),
            "closing_time":  str(self.closing_time),
            "avg_duration":  self.avg_duration,
        }

    def __repr__(self):
        day = self.day_of_week if self.day_of_week is not None else 'general'
        return f"<ServiceSchedule service_id={self.service_id} day={day} open={self.is_open}>"