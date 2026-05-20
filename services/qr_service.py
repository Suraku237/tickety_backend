import qrcode
import qrcode.image.svg
from io import BytesIO
import base64
from flask import current_app


# =============================================================
# QR SERVICE
# Responsibilities:
#   - Build the scannable URL for a service token
#   - Generate a QR code PNG as a base64 data-URI
# OOP Principle: Single Responsibility, Abstraction
#
# The QR code encodes a URL like:
#   https://tickety.app/scan/<service_token>
#
# When the mobile app scans it:
#   1. MobileScanner reads the raw URL string
#   2. App strips the token from the path
#   3. App calls POST /api/services/resolve?token=<token>
#      OR passes the full URL as service_code in the ticket
#
# Dependencies (add to requirements.txt):
#   qrcode[pil]==8.0.0
#   Pillow==11.3.0  (already in requirements.txt)
# =============================================================
class QRService:

    QR_BOX_SIZE  = 10   # pixels per QR module
    QR_BORDER    = 4    # quiet zone in modules
    QR_VERSION   = None # auto-determine
    QR_ERROR     = qrcode.constants.ERROR_CORRECT_M  # ~15% recovery

    def build_url(self, service_token: str) -> str:
        """
        Build the full URL that will be embedded inside the QR code.
        Uses BASE_URL from app config (set in .env as BASE_URL).
        Falls back to localhost for local development.
        """
        base = current_app.config.get('BASE_URL', 'http://localhost:5000')
        return f"{base.rstrip('/')}/scan/{service_token}"

    def generate_png_base64(self, url: str) -> str:
        """
        Generate a QR code for the given URL.
        Returns a base64-encoded PNG as a data-URI string:
          'data:image/png;base64,<data>'
        This can be stored in the database and rendered directly
        in an <img src="..."> tag on the website with no file system.
        """
        qr = qrcode.QRCode(
            version           = self.QR_VERSION,
            error_correction  = self.QR_ERROR,
            box_size          = self.QR_BOX_SIZE,
            border            = self.QR_BORDER,
        )
        qr.add_data(url)
        qr.make(fit=True)

        img = qr.make_image(fill_color='black', back_color='white')

        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)

        b64 = base64.b64encode(buffer.read()).decode('utf-8')
        return f"data:image/png;base64,{b64}"

    def generate_for_service(self, service_token: str) -> tuple[str, str]:
        """
        Convenience method: build the URL and generate the QR image
        in one call. Returns (encoded_url, image_data_uri).

        Usage:
            url, image_uri = QRService().generate_for_service(token)
            qr_repo.create_qr(service_id, url, image_uri)
        """
        url       = self.build_url(service_token)
        image_uri = self.generate_png_base64(url)
        return url, image_uri
