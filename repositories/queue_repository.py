from models import db, Queue


# =============================================================
# QUEUE REPOSITORY
# Responsibilities:
#   - Abstract all DB operations for Queue
# OOP Principle: Single Responsibility, Encapsulation
# =============================================================
class QueueRepository:

    def find_by_id(self, queue_id: int) -> Queue | None:
        return Queue.query.get(queue_id)

    def find_by_service(self, service_id: int) -> list[Queue]:
        return Queue.query.filter_by(service_id=service_id).order_by(Queue.created_at).all()

    def find_by_token(self, token: str) -> Queue | None:
        """Find a queue by its QR join token."""
        return Queue.query.filter_by(join_token=token).first()

    def find_by_code_and_service(self, code: str, service_id: int) -> Queue | None:
        return Queue.query.filter_by(code=code, service_id=service_id).first()

    def create(self, service_id: int, name: str, code: str, color: str) -> Queue:
        """Stage a new Queue. Does NOT commit."""
        queue = Queue(service_id=service_id, name=name, code=code, color=color)
        db.session.add(queue)
        return queue

    def delete(self, queue: Queue):
        """Stage queue deletion. Does NOT commit."""
        db.session.delete(queue)

    def save(self):    db.session.commit()
    def rollback(self): db.session.rollback()
    def flush(self):   db.session.flush()