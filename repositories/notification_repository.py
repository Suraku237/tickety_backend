from models import db, Notification
from datetime import datetime, timezone


# =============================================================
# NOTIFICATION REPOSITORY
# Responsibilities:
#   - Create, fetch, mark-read notifications for a service
# OOP Principle: Single Responsibility, Encapsulation
# =============================================================
class NotificationRepository:

    # Notification type constants
    TYPE_QUEUE_CREATED       = 'queue_created'
    TYPE_QUEUE_DELETED       = 'queue_deleted'
    TYPE_QUEUE_EMPTY         = 'queue_empty'
    TYPE_TICKET_ISSUED       = 'ticket_issued'
    TYPE_TICKET_PRINTED      = 'ticket_printed'
    TYPE_TICKET_SERVED       = 'ticket_served'
    TYPE_TICKET_CARRIED_OVER = 'ticket_carried_over'
    TYPE_TEAM_JOINED         = 'team_joined'
    TYPE_MEMBER_REMOVED      = 'member_removed'
    TYPE_INVITE_GENERATED    = 'invite_generated'
    TYPE_CLOSING_WARNING     = 'closing_warning'

    def find_by_service(self, service_id: int, limit: int = 50) -> list[Notification]:
        """Return the most recent notifications for a service."""
        return (Notification.query
                .filter_by(service_id=service_id)
                .order_by(Notification.created_at.desc())
                .limit(limit)
                .all())

    def unread_count(self, service_id: int) -> int:
        """Return count of unread notifications for a service."""
        return Notification.query.filter_by(
            service_id=service_id, read=False
        ).count()

    def create(self, service_id: int, type: str,
               title: str, body: str = None, meta: dict = None) -> Notification:
        """Stage a new notification. Does NOT commit."""
        notif = Notification(
            service_id = service_id,
            type       = type,
            title      = title,
            body       = body,
            meta       = meta or {},
        )
        db.session.add(notif)
        return notif

    def mark_all_read(self, service_id: int):
        """Mark all unread notifications for a service as read."""
        (Notification.query
         .filter_by(service_id=service_id, read=False)
         .update({"read": True}))

    def mark_read(self, notification_id: int):
        """Mark a single notification as read."""
        notif = Notification.query.get(notification_id)
        if notif:
            notif.read = True

    def delete_old(self, service_id: int, keep: int = 100):
        """
        Keep only the most recent `keep` notifications per service.
        Fetches IDs to keep first, then deletes the rest.
        Avoids subquery syntax that breaks on some SQLAlchemy versions.
        """
        # Get the IDs of the notifications we want to KEEP
        rows_to_keep = (Notification.query
                        .filter_by(service_id=service_id)
                        .order_by(Notification.created_at.desc())
                        .limit(keep)
                        .with_entities(Notification.id)
                        .all())

        if not rows_to_keep:
            return

        ids_to_keep = [r.id for r in rows_to_keep]

        # Delete everything else for this service
        (Notification.query
         .filter_by(service_id=service_id)
         .filter(Notification.id.notin_(ids_to_keep))
         .delete(synchronize_session=False))

    def save(self):     db.session.commit()
    def rollback(self): db.session.rollback()