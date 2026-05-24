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
    username   = db.Column(db.String(50), unique=True, nullable=False)
    email      = db.Column(db.String(120), unique=True, nullable=False)
    password   = db.Column(db.LargeBinary, nullable=False)
    role       = db.Column(db.String(20), nullable=False, default='client')
    verified   = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    tickets    = db.relationship('Ticket', backref='owner', lazy=True,
                                 cascade='all, delete-orphan')

    def mark_verified(self):   self.verified = True
    def is_verified(self):     return self.verified
    def is_client(self):       return self.role == 'client'
    def is_admin(self):        return self.role == 'admin'

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
# RESET CODE MODEL
# =============================================================
class ResetCode(db.Model):
    __tablename__ = 'resets'

    id        = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email     = db.Column(db.String(120), unique=True, nullable=False)
    code      = db.Column(db.String(6), nullable=False)
    expire_at = db.Column(db.DateTime, nullable=False)

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

    id            = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name          = db.Column(db.String(100), nullable=False)
    description   = db.Column(db.Text, nullable=True, default='')
    category      = db.Column(db.String(50), nullable=False, default='General')
    is_active     = db.Column(db.Boolean, default=True)

    service_token = db.Column(
        db.String(36), unique=True, nullable=False,
        default=lambda: str(uuid.uuid4())
    )

    created_by    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at    = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    # Fixed: removed onupdate lambda (unreliable on SQLite); updated_at is
    # stamped explicitly in ServiceRepository.update() instead.
    updated_at    = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    tickets       = db.relationship('Ticket', backref='service_ref', lazy=True)
    qr_code       = db.relationship('QRCode', backref='service',
                                    uselist=False, cascade='all, delete-orphan')

    def activate(self):   self.is_active = True
    def deactivate(self): self.is_active = False

    def to_dict(self) -> dict:
        return {
            "service_id":    str(self.id),
            "name":          self.name,
            "description":   self.description or '',
            "category":      self.category,
            "is_active":     self.is_active,
            "service_token": self.service_token,
            "created_by":    str(self.created_by),
            "created_at":    self.created_at.isoformat() if self.created_at else None,
            "qr_url":        self.qr_code.image_url if self.qr_code else None,
        }

    def __repr__(self):
        return f"<Service id={self.id} name={self.name!r} active={self.is_active}>"


# =============================================================
# QR CODE MODEL
# =============================================================
class QRCode(db.Model):
    __tablename__ = 'qr_codes'

    id           = db.Column(db.Integer, primary_key=True, autoincrement=True)
    service_id   = db.Column(db.Integer, db.ForeignKey('services.id'),
                             nullable=False, unique=True)
    encoded_url  = db.Column(db.String(500), nullable=False)
    image_url    = db.Column(db.Text, nullable=True)
    generated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def regenerate(self, new_url: str, new_image_url: str):
        self.encoded_url  = new_url
        self.image_url    = new_image_url
        self.generated_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "qr_id":        str(self.id),
            "service_id":   str(self.service_id),
            "encoded_url":  self.encoded_url,
            "image_url":    self.image_url,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
        }

    def __repr__(self):
        return f"<QRCode service_id={self.service_id}>"


# =============================================================
# TICKET MODEL
# =============================================================
class Ticket(db.Model):
    __tablename__ = 'tickets'

    id           = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    service_id   = db.Column(db.Integer, db.ForeignKey('services.id'), nullable=True)

    title        = db.Column(db.String(200), nullable=False)
    description  = db.Column(db.Text, nullable=False)
    notes        = db.Column(db.Text, nullable=True, default='')
    priority     = db.Column(db.String(20), nullable=False, default='medium')
    service      = db.Column(db.String(100), nullable=False)
    service_code = db.Column(db.String(500), nullable=True, default='')

    status       = db.Column(db.String(20), nullable=False, default='open')
    created_at   = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    # Fixed: removed onupdate lambda; updated_at is stamped explicitly
    # in set_status() and set_priority() below.
    updated_at   = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def set_status(self, status: str):
        allowed = {'open', 'pending', 'closed'}
        if status not in allowed:
            raise ValueError(f"Invalid status '{status}'. Allowed: {allowed}")
        self.status     = status
        self.updated_at = datetime.now(timezone.utc)  # explicit for SQLite compat

    def set_priority(self, priority: str):
        allowed = {'low', 'medium', 'high', 'urgent'}
        if priority not in allowed:
            raise ValueError(f"Invalid priority '{priority}'. Allowed: {allowed}")
        self.priority   = priority
        self.updated_at = datetime.now(timezone.utc)  # Fixed: was missing updated_at stamp

    def open(self):
        self.status     = 'open'
        self.updated_at = datetime.now(timezone.utc)

    def pend(self):
        self.status     = 'pending'
        self.updated_at = datetime.now(timezone.utc)

    def close(self):
        self.status     = 'closed'
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "ticket_id":    str(self.id),
            "user_id":      str(self.user_id),
            "service_id":   str(self.service_id) if self.service_id else None,
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
