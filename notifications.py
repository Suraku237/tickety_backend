from flask import Blueprint, request, jsonify
from repositories.notification_repository import NotificationRepository

notifications_bp = Blueprint("notifications", __name__)

# =============================================================
# NOTIFICATIONS CONTROLLER
# GET    /api/notifications?service_id=<id>&limit=50
# PATCH  /api/notifications/<id>/read
# PATCH  /api/notifications/read-all?service_id=<id>
# GET    /api/notifications/unread-count?service_id=<id>
# =============================================================
class NotificationsController:

    def _repo(self):
        return NotificationRepository()

    def get_notifications(self):
        service_id = request.args.get("service_id")
        limit      = int(request.args.get("limit", 50))
        if not service_id:
            return jsonify({"success": False, "message": "service_id is required"}), 400

        repo  = self._repo()
        notifs = repo.find_by_service(int(service_id), limit=limit)
        unread = repo.unread_count(int(service_id))

        return jsonify({
            "success":       True,
            "notifications": [n.to_dict() for n in notifs],
            "unread_count":  unread,
        }), 200

    def mark_read(self, notification_id):
        repo = self._repo()
        repo.mark_read(int(notification_id))
        repo.save()
        return jsonify({"success": True}), 200

    def mark_all_read(self):
        service_id = request.args.get("service_id")
        if not service_id:
            return jsonify({"success": False, "message": "service_id is required"}), 400
        repo = self._repo()
        repo.mark_all_read(int(service_id))
        repo.save()
        return jsonify({"success": True}), 200

    def unread_count(self):
        service_id = request.args.get("service_id")
        if not service_id:
            return jsonify({"success": False, "message": "service_id is required"}), 400
        count = self._repo().unread_count(int(service_id))
        return jsonify({"success": True, "unread_count": count}), 200


_controller = NotificationsController()

notifications_bp.add_url_rule("/notifications",                        view_func=_controller.get_notifications, methods=["GET"])
notifications_bp.add_url_rule("/notifications/<int:notification_id>/read", view_func=_controller.mark_read,    methods=["PATCH"])
notifications_bp.add_url_rule("/notifications/read-all",               view_func=_controller.mark_all_read,    methods=["PATCH"])
notifications_bp.add_url_rule("/notifications/unread-count",           view_func=_controller.unread_count,     methods=["GET"])