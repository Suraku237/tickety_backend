import logging
import logging.handlers
import os
from datetime import datetime
from flask import request, g

# Create logs directory if it doesn't exist
LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
os.makedirs(LOGS_DIR, exist_ok=True)


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for console output"""

    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
        'RESET': '\033[0m'      # Reset
    }

    def format(self, record):
        log_color = self.COLORS.get(record.levelname, '')
        reset_color = self.COLORS['RESET']

        # Add color to level name
        record.levelname = f"{log_color}{record.levelname}{reset_color}"
        return super().format(record)


def setup_logger(name='tickety', log_level=logging.INFO):
    """
    Configure and return a logger instance with both console and file handlers.

    Args:
        name: Logger name
        log_level: Logging level (default: INFO)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # Prevent duplicate handlers if called multiple times
    if logger.hasHandlers():
        return logger

    # Log format
    log_format = '%(asctime)s | %(name)s | %(levelname)s | %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'

    # Console handler (with colors)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_formatter = ColoredFormatter(log_format, datefmt=date_format)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler - general logs
    log_file = os.path.join(LOGS_DIR, 'app.log')
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=5  # 10MB per file, keep 5 backups
    )
    file_handler.setLevel(log_level)
    file_formatter = logging.Formatter(log_format, datefmt=date_format)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # File handler - error logs only
    error_log_file = os.path.join(LOGS_DIR, 'error.log')
    error_handler = logging.handlers.RotatingFileHandler(
        error_log_file, maxBytes=10*1024*1024, backupCount=5
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_formatter)
    logger.addHandler(error_handler)

    # File handler - operations log
    ops_log_file = os.path.join(LOGS_DIR, 'operations.log')
    ops_handler = logging.handlers.RotatingFileHandler(
        ops_log_file, maxBytes=10*1024*1024, backupCount=5
    )
    ops_handler.setLevel(logging.INFO)
    ops_formatter = logging.Formatter('%(asctime)s | %(message)s', datefmt=date_format)
    ops_handler.setFormatter(ops_formatter)

    # Create operations logger
    ops_logger = logging.getLogger('operations')
    ops_logger.setLevel(logging.INFO)
    if not ops_logger.hasHandlers():
        ops_logger.addHandler(ops_handler)

    return logger


# Initialize main logger
logger = setup_logger('tickety')
ops_logger = logging.getLogger('operations')


def log_request_info():
    """Log incoming request information"""
    source = request.headers.get('X-App-Source', 'unknown').lower()
    user_id = request.args.get('user_id') or request.get_json(silent=True).get('user_id') if request.method != 'GET' else request.args.get('user_id')

    request_info = {
        'method': request.method,
        'endpoint': request.endpoint or 'unknown',
        'path': request.path,
        'source': source,
        'user_id': user_id or 'anonymous',
        'timestamp': datetime.utcnow().isoformat(),
    }

    g.request_start_time = datetime.utcnow()
    g.request_info = request_info

    logger.info(
        f"→ [{source.upper()}] {request.method} {request.path} | User: {user_id or 'anonymous'}"
    )


def log_response_info(response):
    """Log response information"""
    if hasattr(g, 'request_info'):
        duration = (datetime.utcnow() - g.request_start_time).total_seconds() if hasattr(g, 'request_start_time') else 0
        source = g.request_info.get('source', 'unknown').upper()
        status_code = response.status_code

        # Color code status
        if status_code < 400:
            status_emoji = '✓'
        elif status_code < 500:
            status_emoji = '⚠'
        else:
            status_emoji = '✗'

        logger.info(
            f"← [{source}] {g.request_info['method']} {g.request_info['path']} | "
            f"Status: {status_code} {status_emoji} | Duration: {duration:.2f}s"
        )

    return response


def log_operation(operation_type, platform, details, user_id=None, success=True):
    """
    Log a specific operation.

    Args:
        operation_type: Type of operation (CREATE, READ, UPDATE, DELETE, LOGIN, etc.)
        platform: Platform being used (auth, tickets, services)
        details: Dictionary with operation details
        user_id: User ID performing the operation
        success: Whether the operation succeeded
    """
    status = '✓' if success else '✗'
    user_info = f"user={user_id}" if user_id else "anonymous"
    details_str = ' | '.join(f"{k}={v}" for k, v in details.items() if v is not None)

    message = f"[{operation_type}] {platform.upper()} {status} | {user_info} | {details_str}"

    if success:
        ops_logger.info(message)
        logger.info(f"✓ {message}")
    else:
        ops_logger.error(message)
        logger.error(f"✗ {message}")


def log_error(error_type, platform, message, user_id=None, exception=None):
    """
    Log an error.

    Args:
        error_type: Type of error (VALIDATION, DATABASE, AUTH, etc.)
        platform: Platform where error occurred
        message: Error message
        user_id: User ID if available
        exception: The exception object if available
    """
    user_info = f"user={user_id}" if user_id else "anonymous"
    error_msg = f"[ERROR] {error_type} | {platform.upper()} | {user_info} | {message}"

    logger.error(error_msg, exc_info=exception)
    ops_logger.error(error_msg)
