from repositories.notification_repository import NotificationRepository


# =============================================================
# NOTIFICATION SERVICE
# Responsibilities:
#   - Provide typed factory methods so controllers never
#     construct notification dicts manually
#   - Keep title/body wording consistent across the app
# OOP Principle: Single Responsibility, Encapsulation, DRY
# =============================================================
class NotificationService:

    def __init__(self):
        self._repo = NotificationRepository()

    def _push(self, service_id, type, title, body=None, meta=None):
        """Create + commit a single notification."""
        self._repo.create(service_id, type, title, body, meta)
        # Trim to last 100 before committing to avoid unbounded growth
        self._repo.delete_old(service_id, keep=100)
        self._repo.save()

    # ----------------------------------------------------------
    # QUEUE EVENTS
    # ----------------------------------------------------------
    def queue_created(self, service_id: int, queue_name: str, queue_code: str):
        self._push(
            service_id,
            NotificationRepository.TYPE_QUEUE_CREATED,
            title = f"Queue created: {queue_name}",
            body  = f"Code: {queue_code}. Agents can now select this queue.",
            meta  = {"queue_name": queue_name, "queue_code": queue_code},
        )

    def queue_deleted(self, service_id: int, queue_name: str):
        self._push(
            service_id,
            NotificationRepository.TYPE_QUEUE_DELETED,
            title = f"Queue deleted: {queue_name}",
            body  = "All tickets in this queue have been removed.",
            meta  = {"queue_name": queue_name},
        )

    def queue_empty(self, service_id: int, queue_name: str):
        self._push(
            service_id,
            NotificationRepository.TYPE_QUEUE_EMPTY,
            title = f"Queue empty: {queue_name}",
            body  = "All tickets in this queue have been served.",
            meta  = {"queue_name": queue_name},
        )

    # ----------------------------------------------------------
    # TICKET EVENTS
    # ----------------------------------------------------------
    def ticket_issued(self, service_id: int, code: str, queue_name: str, printed: bool = False):
        if printed:
            self._push(
                service_id,
                NotificationRepository.TYPE_TICKET_PRINTED,
                title = f"Printed ticket issued: {code}",
                body  = f"A physical ticket ({code}) was manually issued for {queue_name}.",
                meta  = {"code": code, "queue_name": queue_name, "printed": True},
            )
        else:
            self._push(
                service_id,
                NotificationRepository.TYPE_TICKET_ISSUED,
                title = f"New ticket: {code}",
                body  = f"A new ticket was issued for {queue_name}.",
                meta  = {"code": code, "queue_name": queue_name, "printed": False},
            )

    def ticket_served(self, service_id: int, code: str, counter: str = None):
        body = f"Ticket {code} was served."
        if counter:
            body += f" (Counter: {counter})"
        self._push(
            service_id,
            NotificationRepository.TYPE_TICKET_SERVED,
            title = f"Ticket served: {code}",
            body  = body,
            meta  = {"code": code, "counter": counter},
        )

    def ticket_carried_over(self, service_id: int, count: int, closing_time: str):
        self._push(
            service_id,
            NotificationRepository.TYPE_TICKET_CARRIED_OVER,
            title = f"{count} ticket{'s' if count != 1 else ''} carried over",
            body  = f"Service closed at {closing_time}. {count} ticket{'s' if count != 1 else ''} will be served first tomorrow.",
            meta  = {"count": count, "closing_time": closing_time},
        )

    # ----------------------------------------------------------
    # TEAM EVENTS
    # ----------------------------------------------------------
    def team_joined(self, service_id: int, username: str, role: str):
        role_label = {'manager': 'Ticket Manager', 'agent': 'Counter Agent'}.get(role, role)
        self._push(
            service_id,
            NotificationRepository.TYPE_TEAM_JOINED,
            title = f"New team member: {username}",
            body  = f"{username} joined as {role_label}.",
            meta  = {"username": username, "role": role},
        )

    def member_removed(self, service_id: int, username: str):
        self._push(
            service_id,
            NotificationRepository.TYPE_MEMBER_REMOVED,
            title = f"Team member removed: {username}",
            body  = f"{username} was removed from the service.",
            meta  = {"username": username},
        )

    def invite_generated(self, service_id: int, role: str, expires_at: str):
        role_label = {'manager': 'Ticket Manager', 'agent': 'Counter Agent'}.get(role, role)
        self._push(
            service_id,
            NotificationRepository.TYPE_INVITE_GENERATED,
            title = f"Invite link generated for {role_label}",
            body  = f"Link expires at {expires_at}.",
            meta  = {"role": role, "expires_at": expires_at},
        )

    # ----------------------------------------------------------
    # SCHEDULE EVENTS
    # ----------------------------------------------------------
    def closing_warning(self, service_id: int, count: int, closing_time: str):
        self._push(
            service_id,
            NotificationRepository.TYPE_CLOSING_WARNING,
            title = f"Closing time approaching: {closing_time}",
            body  = f"{count} ticket{'s' if count != 1 else ''} may not be served today.",
            meta  = {"count": count, "closing_time": closing_time},
        )