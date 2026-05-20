from flask import Blueprint, request, jsonify, send_file
from io import BytesIO
import base64

from repositories.service_repository import ServiceRepository
from repositories.user_repository    import UserRepository
from services.qr_service             import QRService

services_bp = Blueprint('services', __name__)


# =============================================================
# SERVICES CONTROLLER
# Responsibilities:
#   - Provide CRUD routes for Service management (website)
#   - Generate and regenerate QR codes for each service
#   - Expose a public /scan/<token> resolver used by the mobile app
# OOP Principle: Single Responsibility, Dependency Injection
#
# Route overview:
#
#  WEBSITE (admin only — must send X-App-Source: web)
#   POST   /api/services              → create service + generate QR
#   GET    /api/services              → list all services
#   GET    /api/services/<id>         → get one service + its QR
#   PATCH  /api/services/<id>         → update service details
#   DELETE /api/services/<id>         → delete service
#   POST   /api/services/<id>/regenerate-qr → regenerate QR image
#   GET    /api/services/<id>/qr.png  → download QR as PNG file
#
#  MOBILE + WEBSITE (public)
#   GET    /api/services/resolve?token=<token> → resolve token to service
#
# Auth strategy: same X-App-Source header as auth.py
# =============================================================
class ServicesController:

    def _get_deps(self):
        return ServiceRepository(), UserRepository(), QRService()

    def _require_admin(self) -> bool:
        """Return True if request comes from the web dashboard."""
        return request.headers.get('X-App-Source', '').lower() == 'web'

    # ----------------------------------------------------------
    # POST /api/services
    # Create a service and immediately generate its QR code.
    # ----------------------------------------------------------
    def create(self):
        if not self._require_admin():
            return jsonify({'success': False,
                            'message': 'Admin access required'}), 403

        svc_repo, _, qr_svc = self._get_deps()
        data = request.get_json(silent=True) or {}

        name        = str(data.get('name',        '')).strip()
        description = str(data.get('description', '')).strip()
        category    = str(data.get('category',    'General')).strip()
        admin_id    = data.get('admin_id')

        if not name:
            return jsonify({'success': False,
                            'message': 'Service name is required'}), 400
        if not admin_id:
            return jsonify({'success': False,
                            'message': 'admin_id is required'}), 400

        try:
            # 1. Create the service row — flushes to get the ID
            service = svc_repo.create(
                name        = name,
                admin_id    = int(admin_id),
                description = description,
                category    = category,
            )
            svc_repo.flush()  # now service.id and service.service_token exist

            # 2. Generate QR code from the service_token
            encoded_url, image_uri = qr_svc.generate_for_service(
                service.service_token)

            # 3. Persist the QR record
            svc_repo.create_qr(
                service_id  = service.id,
                encoded_url = encoded_url,
                image_url   = image_uri,
            )
            svc_repo.save()

            return jsonify({
                'success': True,
                'message': 'Service created with QR code',
                'service': service.to_dict(),
            }), 201

        except Exception as e:
            svc_repo.rollback()
            return jsonify({'success': False, 'message': str(e)}), 500

    # ----------------------------------------------------------
    # GET /api/services
    # List all services (admin) or only active ones (mobile).
    # ----------------------------------------------------------
    def list_services(self):
        svc_repo, _, _ = self._get_deps()
        is_admin = self._require_admin()

        try:
            services = svc_repo.find_all() if is_admin \
                else svc_repo.find_active()
            return jsonify({
                'success':  True,
                'services': [s.to_dict() for s in services],
                'count':    len(services),
            }), 200
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500

    # ----------------------------------------------------------
    # GET /api/services/<service_id>
    # ----------------------------------------------------------
    def get_service(self, service_id: int):
        svc_repo, _, _ = self._get_deps()
        service = svc_repo.find_by_id(service_id)
        if not service:
            return jsonify({'success': False,
                            'message': 'Service not found'}), 404
        return jsonify({'success': True, 'service': service.to_dict()}), 200

    # ----------------------------------------------------------
    # PATCH /api/services/<service_id>
    # Update name, description, category, or is_active.
    # ----------------------------------------------------------
    def update_service(self, service_id: int):
        if not self._require_admin():
            return jsonify({'success': False,
                            'message': 'Admin access required'}), 403

        svc_repo, _, _ = self._get_deps()
        service = svc_repo.find_by_id(service_id)
        if not service:
            return jsonify({'success': False,
                            'message': 'Service not found'}), 404

        data = request.get_json(silent=True) or {}
        try:
            svc_repo.update(
                service,
                name        = data.get('name'),
                description = data.get('description'),
                category    = data.get('category'),
                is_active   = data.get('is_active'),
            )
            svc_repo.save()
            return jsonify({
                'success': True,
                'message': 'Service updated',
                'service': service.to_dict(),
            }), 200
        except Exception as e:
            svc_repo.rollback()
            return jsonify({'success': False, 'message': str(e)}), 500

    # ----------------------------------------------------------
    # DELETE /api/services/<service_id>
    # ----------------------------------------------------------
    def delete_service(self, service_id: int):
        if not self._require_admin():
            return jsonify({'success': False,
                            'message': 'Admin access required'}), 403

        svc_repo, _, _ = self._get_deps()
        service = svc_repo.find_by_id(service_id)
        if not service:
            return jsonify({'success': False,
                            'message': 'Service not found'}), 404

        try:
            svc_repo.delete(service)
            svc_repo.save()
            return jsonify({'success': True,
                            'message': 'Service deleted'}), 200
        except Exception as e:
            svc_repo.rollback()
            return jsonify({'success': False, 'message': str(e)}), 500

    # ----------------------------------------------------------
    # POST /api/services/<service_id>/regenerate-qr
    # Regenerate the QR code (e.g. if the service_token is compromised).
    # NOTE: regenerating creates a NEW token, which invalidates
    # all printed QR codes — use with caution.
    # ----------------------------------------------------------
    def regenerate_qr(self, service_id: int):
        if not self._require_admin():
            return jsonify({'success': False,
                            'message': 'Admin access required'}), 403

        svc_repo, _, qr_svc = self._get_deps()
        service = svc_repo.find_by_id(service_id)
        if not service:
            return jsonify({'success': False,
                            'message': 'Service not found'}), 404

        try:
            import uuid
            # Issue a new token so old physical QR codes stop working
            service.service_token = str(uuid.uuid4())

            encoded_url, image_uri = qr_svc.generate_for_service(
                service.service_token)

            qr = svc_repo.get_qr(service_id)
            if qr:
                svc_repo.update_qr(qr, encoded_url, image_uri)
            else:
                svc_repo.create_qr(service_id, encoded_url, image_uri)

            svc_repo.save()
            return jsonify({
                'success': True,
                'message': 'QR code regenerated',
                'service': service.to_dict(),
            }), 200
        except Exception as e:
            svc_repo.rollback()
            return jsonify({'success': False, 'message': str(e)}), 500

    # ----------------------------------------------------------
    # GET /api/services/<service_id>/qr.png
    # Download the QR code as a raw PNG file (for printing).
    # ----------------------------------------------------------
    def download_qr(self, service_id: int):
        svc_repo, _, _ = self._get_deps()
        qr = svc_repo.get_qr(service_id)
        if not qr or not qr.image_url:
            return jsonify({'success': False,
                            'message': 'QR code not found'}), 404

        try:
            # image_url is stored as "data:image/png;base64,<data>"
            header, b64_data = qr.image_url.split(',', 1)
            png_bytes        = base64.b64decode(b64_data)
            buffer           = BytesIO(png_bytes)
            buffer.seek(0)
            return send_file(
                buffer,
                mimetype     = 'image/png',
                as_attachment = True,
                download_name = f'service_{service_id}_qr.png',
            )
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500

    # ----------------------------------------------------------
    # GET /api/services/resolve?token=<token>
    # Resolve a scanned QR token → return service details.
    # Called by the mobile app right after scanning a QR.
    # Public endpoint — no admin check.
    # ----------------------------------------------------------
    def resolve_token(self):
        svc_repo, _, _ = self._get_deps()
        token = request.args.get('token', '').strip()

        if not token:
            return jsonify({'success': False,
                            'message': 'token is required'}), 400

        service = svc_repo.find_by_token(token)
        if not service:
            return jsonify({'success': False,
                            'message': 'Invalid or expired QR code'}), 404

        if not service.is_active:
            return jsonify({'success': False,
                            'message': 'This service is currently inactive'}), 403

        return jsonify({
            'success': True,
            'service': service.to_dict(),
        }), 200


# =============================================================
# ROUTE REGISTRATION
# =============================================================
_ctrl = ServicesController()

services_bp.add_url_rule(
    '/services',
    view_func = _ctrl.create,
    methods   = ['POST'],
)
services_bp.add_url_rule(
    '/services',
    view_func = _ctrl.list_services,
    methods   = ['GET'],
)
services_bp.add_url_rule(
    '/services/resolve',
    view_func = _ctrl.resolve_token,
    methods   = ['GET'],
)
services_bp.add_url_rule(
    '/services/<int:service_id>',
    view_func = _ctrl.get_service,
    methods   = ['GET'],
)
services_bp.add_url_rule(
    '/services/<int:service_id>',
    view_func = _ctrl.update_service,
    methods   = ['PATCH'],
)
services_bp.add_url_rule(
    '/services/<int:service_id>',
    view_func = _ctrl.delete_service,
    methods   = ['DELETE'],
)
services_bp.add_url_rule(
    '/services/<int:service_id>/regenerate-qr',
    view_func = _ctrl.regenerate_qr,
    methods   = ['POST'],
)
services_bp.add_url_rule(
    '/services/<int:service_id>/qr.png',
    view_func = _ctrl.download_qr,
    methods   = ['GET'],
)
