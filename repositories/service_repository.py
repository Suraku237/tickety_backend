from models import db, Service, QRCode


# =============================================================
# SERVICE REPOSITORY
# Responsibilities:
#   - Abstract all database operations for Service and QRCode
#   - Mirror the pattern of UserRepository exactly
# OOP Principle: Single Responsibility, Encapsulation
# =============================================================
class ServiceRepository:

    # ----------------------------------------------------------
    # SERVICE — READ
    # ----------------------------------------------------------
    def find_by_id(self, service_id: int) -> Service | None:
        return Service.query.get(service_id)

    def find_by_token(self, token: str) -> Service | None:
        """Resolve a scanned QR token back to its Service row."""
        return Service.query.filter_by(service_token=token).first()

    def find_all(self) -> list[Service]:
        """All services — used by admin dashboard."""
        return Service.query.order_by(Service.created_at.desc()).all()

    def find_active(self) -> list[Service]:
        """Only active services — used by mobile service picker."""
        return (Service.query
                .filter_by(is_active=True)
                .order_by(Service.name)
                .all())

    def find_by_admin(self, admin_id: int) -> list[Service]:
        """Services created by a specific admin."""
        return (Service.query
                .filter_by(created_by=admin_id)
                .order_by(Service.created_at.desc())
                .all())

    def find_by_category(self, category: str) -> list[Service]:
        return (Service.query
                .filter_by(category=category, is_active=True)
                .order_by(Service.name)
                .all())

    # ----------------------------------------------------------
    # SERVICE — CREATE / UPDATE / DELETE
    # ----------------------------------------------------------
    def create(
        self,
        name:       str,
        admin_id:   int,
        description: str = '',
        category:   str = 'General',
    ) -> Service:
        """
        Create a new Service. service_token is auto-generated
        by the model default (uuid4). Does NOT commit.
        """
        service = Service(
            name        = name,
            description = description,
            category    = category,
            is_active   = True,
            created_by  = admin_id,
        )
        db.session.add(service)
        return service

    def update(
        self,
        service:     Service,
        name:        str | None = None,
        description: str | None = None,
        category:    str | None = None,
        is_active:   bool | None = None,
    ) -> Service:
        """Partial update — only overwrites fields that are not None."""
        from datetime import datetime, timezone
        if name        is not None: service.name        = name
        if description is not None: service.description = description
        if category    is not None: service.category    = category
        if is_active   is not None: service.is_active   = is_active
        # Fixed: stamp updated_at explicitly (onupdate lambda removed from model)
        service.updated_at = datetime.now(timezone.utc)
        return service

    def delete(self, service: Service):
        """Hard delete. Cascades to QRCode and de-links Tickets."""
        db.session.delete(service)

    # ----------------------------------------------------------
    # QR CODE — READ / CREATE / UPDATE
    # ----------------------------------------------------------
    def get_qr(self, service_id: int) -> QRCode | None:
        return QRCode.query.filter_by(service_id=service_id).first()

    def create_qr(
        self,
        service_id:  int,
        encoded_url: str,
        image_url:   str,
    ) -> QRCode:
        """
        Create a QRCode record for the service.
        Does NOT commit — caller controls the transaction.
        """
        qr = QRCode(
            service_id  = service_id,
            encoded_url = encoded_url,
            image_url   = image_url,
        )
        db.session.add(qr)
        return qr

    def update_qr(
        self,
        qr:          QRCode,
        encoded_url: str,
        image_url:   str,
    ) -> QRCode:
        """Regenerate an existing QR code record. Does NOT commit."""
        qr.regenerate(encoded_url, image_url)
        return qr

    # ----------------------------------------------------------
    # TRANSACTION HELPERS  (mirrors UserRepository)
    # ----------------------------------------------------------
    def save(self):
        db.session.commit()

    def rollback(self):
        db.session.rollback()

    def flush(self):
        """Flush to get the new service.id before committing."""
        db.session.flush()
