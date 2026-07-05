from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone
import uuid

db = SQLAlchemy()


# =============================================================
# API TIMESTAMP  (timezone fix)
# Responsibilities:
#   - Encapsulate the API datetime wire convention in ONE place
#   - Storage convention : naive UTC in MySQL DATETIME columns
#   - Wire convention    : ISO-8601 with an explicit UTC marker "Z"
#
# WHY THIS EXISTS:
#   A naive isoformat() like "2026-06-20T09:01:35" carries no
#   timezone, so browsers (new Date) and Dart (DateTime.parse)
#   interpret it as LOCAL time. Result: every displayed time was
#   1 hour behind in Cameroon (UTC+1). Emitting "...Z" tells every
#   client the value is UTC, and each client then renders it in
#   the user's own local timezone automatically.
#
# OOP Principle: Single Responsibility, Encapsulation — models
#   never format datetimes themselves; they delegate here.
# =============================================================
class ApiTimestamp:

    @staticmethod
    def to_iso(dt: datetime | None) -> str | None:
        """Serialize a stored (naive-UTC) datetime as ISO-8601 UTC ("Z")."""
        if dt is None:
            return None
        if dt.tzinfo is None:                      # DB gives us naive UTC
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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

    admin_entries  = db.relationship('Admin',            backref='service',  lazy=True, cascade='all, delete-orphan')
    queues         = db.relationship('Queue',            backref='service',  lazy=True, cascade='all, delete-orphan')
    schedules      = db.relationship('ServiceSchedule',  backref='service',  lazy=True, cascade='all, delete-orphan')
    invite_tokens  = db.relationship('InviteToken',      backref='service',  lazy=True, cascade='all, delete-orphan')
    notifications  = db.relationship('Notification',     backref='service',  lazy=True, cascade='all, delete-orphan')

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
# =============================================================
class Queue(db.Model):
    __tablename__ = 'queues'

    id         = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id', ondelete='CASCADE'), nullable=False)
    name       = db.Column(db.String(120), nullable=False)
    code       = db.Column(db.String(20),  nullable=False)
    color      = db.Column(db.String(10),  nullable=False, default='#DC0F0F')
    join_token = db.Column(db.String(36),  unique=True, nullable=False,
                           default=lambda: str(uuid.uuid4()))
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
# Added: printed (bool) — marks manually issued printed tickets
# Added: called_at — stamped when the agent calls the ticket;
#        drives the rolling real-wait average.
# =============================================================
class Ticket(db.Model):
    __tablename__ = 'tickets'

    id                  = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    queue_id            = db.Column(db.Integer, db.ForeignKey('queues.id',    ondelete='CASCADE'), nullable=False)
    service_id          = db.Column(db.Integer, db.ForeignKey('services.id',  ondelete='CASCADE'), nullable=False)
    code                = db.Column(db.String(20),  nullable=False)
    status              = db.Column(db.String(20),  nullable=False, default='pending')
    priority            = db.Column(db.String(20),  nullable=False, default='normal')
    position            = db.Column(db.Integer,     nullable=True)
    counter             = db.Column(db.String(20),  nullable=True)
    customer_identifier = db.Column(db.String(120), nullable=True)
    printed             = db.Column(db.Boolean,     nullable=False, default=False)  # manually issued printed ticket
    issued_at           = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    called_at           = db.Column(db.DateTime, nullable=True)   # stamped when agent calls the ticket (status -> active)
    estimated_serve_at  = db.Column(db.DateTime, nullable=True)
    carried_over_date   = db.Column(db.Date,     nullable=True)

    def actual_wait_minutes(self):
        """Real wait (minutes) between issue and being called, or None."""
        if self.issued_at and self.called_at:
            return max(0, int((self.called_at - self.issued_at).total_seconds() / 60))
        return None

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
            "printed":             self.printed,
            "issued_at":           ApiTimestamp.to_iso(self.issued_at),
            "called_at":           ApiTimestamp.to_iso(self.called_at),
            "estimated_serve_at":  ApiTimestamp.to_iso(self.estimated_serve_at),
            "carried_over_date":   str(self.carried_over_date) if self.carried_over_date else None,
        }

    def __repr__(self):
        return f"<Ticket id={self.id} code={self.code} status={self.status} pos={self.position}>"


# =============================================================
# INVITE TOKEN MODEL
# =============================================================
class InviteToken(db.Model):
    __tablename__ = 'invite_tokens'

    id         = db.Column(db.Integer,    primary_key=True, autoincrement=True)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id', ondelete='CASCADE'), nullable=False)
    token      = db.Column(db.String(36), unique=True, nullable=False,
                           default=lambda: str(uuid.uuid4()))
    admin_role = db.Column(db.String(20), nullable=False, default='agent')
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
            "expires_at": ApiTimestamp.to_iso(self.expires_at),
        }

    def __repr__(self):
        return f"<InviteToken service_id={self.service_id} role={self.admin_role} used={self.used}>"


# =============================================================
# SERVICE SCHEDULE MODEL
# =============================================================
class ServiceSchedule(db.Model):
    __tablename__ = 'service_schedules'

    id           = db.Column(db.Integer, primary_key=True, autoincrement=True)
    service_id   = db.Column(db.Integer, db.ForeignKey('services.id', ondelete='CASCADE'), nullable=False)
    day_of_week  = db.Column(db.Integer, nullable=True)
    is_open      = db.Column(db.Boolean, nullable=False, default=True)
    opening_time = db.Column(db.Time,    nullable=False)
    closing_time = db.Column(db.Time,    nullable=False)
    avg_duration = db.Column(db.Integer, nullable=False, default=10)
    created_at   = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at   = db.Column(db.DateTime,
                             default=lambda: datetime.now(timezone.utc),
                             onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint('service_id', 'day_of_week', name='uq_service_schedule_day'),
    )

    def to_dict(self):
        return {
            "schedule_id":  str(self.id),
            "service_id":   str(self.service_id),
            "day_of_week":  self.day_of_week,
            "is_open":      self.is_open,
            "opening_time": str(self.opening_time),
            "closing_time": str(self.closing_time),
            "avg_duration": self.avg_duration,
        }

    def __repr__(self):
        day = self.day_of_week if self.day_of_week is not None else 'general'
        return f"<ServiceSchedule service_id={self.service_id} day={day} open={self.is_open}>"


# =============================================================
# NOTIFICATION MODEL
# Responsibilities:
#   - Persist service-level notifications across sessions
#   - type: queue_created | ticket_issued | ticket_printed |
#           team_joined | closing_warning | queue_empty |
#           ticket_served | ticket_carried_over | queue_deleted |
#           member_removed | invite_generated
# =============================================================
class Notification(db.Model):
    __tablename__ = 'notifications'

    id         = db.Column(db.Integer,    primary_key=True, autoincrement=True)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id', ondelete='CASCADE'), nullable=False)
    type       = db.Column(db.String(40), nullable=False)
    title      = db.Column(db.String(120), nullable=False)
    body       = db.Column(db.String(255), nullable=True)
    meta       = db.Column(db.JSON,        nullable=True)   # extra data (ticket code, queue name…)
    read       = db.Column(db.Boolean,     nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "notification_id": str(self.id),
            "service_id":      str(self.service_id),
            "type":            self.type,
            "title":           self.title,
            "body":            self.body,
            "meta":            self.meta,
            "read":            self.read,
            "created_at":      ApiTimestamp.to_iso(self.created_at),
        }

    def __repr__(self):
        return f"<Notification service_id={self.service_id} type={self.type} read={self.read}>"


# =============================================================
# DEVICE TOKEN MODEL  (#8 — push notifications)
# Stores a user's FCM device tokens so the backend can push
# system notifications (ticket called, swap request) even when
# the app is closed.
# =============================================================
class DeviceToken(db.Model):
    __tablename__ = 'device_tokens'

    id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    token      = db.Column(db.String(255), unique=True, nullable=False)   # FCM registration token
    platform   = db.Column(db.String(20),  nullable=True)                 # android | ios | web
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id":       str(self.id),
            "user_id":  str(self.user_id),
            "platform": self.platform,
        }

    def __repr__(self):
        return f"<DeviceToken user_id={self.user_id} platform={self.platform}>"


# =============================================================
# SWAP REQUEST MODEL  (merged from mobile backend)
# Responsibilities:
#   - Represent a request by one ticket holder to swap queue
#     position with another ticket holder
#   - status: pending | accepted | rejected | expired
# OOP Principle: Encapsulation — status transitions guarded by
#                helper predicates and class-level constants
# =============================================================
class SwapRequest(db.Model):
    __tablename__ = 'swap_requests'

    id                  = db.Column(db.Integer, primary_key=True, autoincrement=True)
    service_id          = db.Column(db.Integer, db.ForeignKey('services.id', ondelete='CASCADE'), nullable=False)
    requester_ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id',  ondelete='CASCADE'), nullable=False)
    target_ticket_id    = db.Column(db.Integer, db.ForeignKey('tickets.id',  ondelete='CASCADE'), nullable=False)
    status              = db.Column(db.String(20), nullable=False, default='pending')
    created_at          = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    responded_at        = db.Column(db.DateTime, nullable=True)

    requester_ticket = db.relationship('Ticket', foreign_keys=[requester_ticket_id])
    target_ticket    = db.relationship('Ticket', foreign_keys=[target_ticket_id])

    STATUS_PENDING  = 'pending'
    STATUS_ACCEPTED = 'accepted'
    STATUS_REJECTED = 'rejected'
    STATUS_EXPIRED  = 'expired'

    def is_pending(self):  return self.status == self.STATUS_PENDING
    def is_accepted(self): return self.status == self.STATUS_ACCEPTED
    def is_rejected(self): return self.status == self.STATUS_REJECTED

    def to_dict(self):
        return {
            "swap_id":              str(self.id),
            "service_id":           str(self.service_id),
            "requester_ticket_id":  str(self.requester_ticket_id),
            "target_ticket_id":     str(self.target_ticket_id),
            "status":               self.status,
            "created_at":           ApiTimestamp.to_iso(self.created_at),
            "responded_at":         ApiTimestamp.to_iso(self.responded_at),
        }

    def __repr__(self):
        return (f"<SwapRequest id={self.id} "
                f"req={self.requester_ticket_id} "
                f"tgt={self.target_ticket_id} "
                f"status={self.status}>")