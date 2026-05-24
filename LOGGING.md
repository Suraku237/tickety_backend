# Tickety Backend Logging System

## Overview
Your backend now has comprehensive logging enabled for all operations across all platforms (Auth, Tickets, and Services). Logs are recorded to files and console with color-coded output for easy monitoring.

## Log Locations
All logs are stored in the `logs/` directory:

```
logs/
├── app.log              # General application logs (all events)
├── error.log            # Error events only
└── operations.log       # Business operations audit trail
```

## Log Files

### `app.log` (General Application Log)
Contains all events including:
- Request/response information
- Operation logs (CREATE, READ, UPDATE, DELETE)
- Error logs
- Exceptions

**Format:** `timestamp | logger_name | level | message`

**Example:**
```
2025-05-24 14:23:45 | tickety | INFO | → [MOBILE] POST /api/tickets | User: 5
2025-05-24 14:23:46 | tickety | INFO | ✓ [CREATE] TICKETS ✓ | user=5 | ticket_id=42 | title=Payment Issue | service=BillingService | priority=medium
2025-05-24 14:23:46 | tickety | INFO | ← [MOBILE] POST /api/tickets | Status: 201 ✓ | Duration: 0.45s
```

### `error.log` (Error Events Only)
Contains only ERROR and CRITICAL level messages for quick error tracking.

**Format:** `timestamp | logger_name | level | message`

**Example:**
```
2025-05-24 14:25:12 | tickety | ERROR | [ERROR] VALIDATION | TICKETS | user=10 | Ticket not found: 999
2025-05-24 14:26:33 | tickety | ERROR | [ERROR] AUTH | SERVICES | anonymous | Admin access required
```

### `operations.log` (Audit Trail)
Structured business operation logs for auditing purposes. Perfect for:
- Tracking who did what
- Monitoring data modifications
- Compliance auditing

**Format:** `timestamp | [OPERATION_TYPE] PLATFORM ✓/✗ | user_id | details`

**Examples:**
```
2025-05-24 14:23:46 | [CREATE] TICKETS ✓ | user=5 | ticket_id=42 | title=Payment Issue | service=BillingService
2025-05-24 14:24:12 | [UPDATE] TICKETS ✓ | user=5 | ticket_id=42 | changes=2 | status=in-progress | priority=high
2025-05-24 14:25:00 | [LOGIN] AUTH ✓ | user=1 | email=admin@tickety.app | role=admin
2025-05-24 14:26:15 | [REGISTER] AUTH ✓ | email=newuser@example.com | username=newuser | role=client
2025-05-24 14:27:30 | [CREATE] SERVICES ✓ | user=1 | service_id=5 | name=PaymentGateway | category=Finance
```

## Console Output

The console displays color-coded logs for easy visual parsing:

```
✓ Request/Response logs: GREEN
✗ Error logs: RED
⚠ Auth errors: YELLOW
Information: CYAN
```

### Console Log Format
```
Request:  → [SOURCE] METHOD /path | User: user_id
Response: ← [SOURCE] METHOD /path | Status: code emoji | Duration: time
```

## What Gets Logged

### Authentication Platform
- **REGISTER**: New user registrations
- **VERIFY_EMAIL**: Email verification events
- **LOGIN**: User login attempts (success/failure)
- **RESEND_OTP**: OTP resend requests

### Tickets Platform
- **CREATE**: New ticket creation
- **READ**: Ticket retrieval/filtering
- **UPDATE**: Ticket modifications
- **DELETE**: Ticket deletion

### Services Platform
- **CREATE**: New service setup
- **READ**: Service retrieval/listing
- **UPDATE**: Service modifications
- **DELETE**: Service removal
- **REGENERATE_QR**: QR code regeneration
- **DOWNLOAD_QR**: QR code downloads
- **RESOLVE_QR**: QR token resolution (mobile scanning)

## Error Categories

Errors are classified into types for better tracking:

- **VALIDATION**: Input validation failures
- **AUTH**: Authorization/authentication errors
- **DATABASE**: Database operation failures
- **EXCEPTION**: Unhandled exceptions

## Log Rotation

Logs are automatically rotated to prevent unlimited growth:
- **Max file size**: 10MB per log file
- **Backup count**: 5 previous files kept
- **File naming**: `app.log`, `app.log.1`, `app.log.2`, etc.

## Viewing Logs

### Real-time monitoring (development)
```bash
# Watch app.log in real-time
tail -f logs/app.log

# Watch operations audit trail
tail -f logs/operations.log

# Watch errors only
tail -f logs/error.log
```

### Searching logs
```bash
# Find all user login attempts
grep "LOGIN" logs/operations.log

# Find all errors for a specific user
grep "user=5" logs/error.log

# Find all DELETE operations
grep "\[DELETE\]" logs/operations.log

# Find failures
grep "✗" logs/operations.log
```

### Using grep with timestamps
```bash
# Logs from the last hour
grep "14:2[0-9]" logs/app.log

# Find slow operations (>1s)
grep "Duration: [1-9]\." logs/app.log
```

## Integration Points

The logger is imported and used in:
- **app.py**: Request/response hooks
- **auth.py**: Authentication operations
- **tickets.py**: Ticket CRUD operations
- **services_bp.py**: Service CRUD operations

## API Response Times

The response logs include operation duration:
```
Duration: 0.45s  ← time to process request
```

This helps identify slow operations for optimization.

## User Identification

Logs capture user_id or email when available:
- Authenticated requests: `user_id`
- Registration/login: `email`
- Anonymous/failed auth: `anonymous`

This enables tracking user activity across the system.

## Example Log Workflow

**Mobile user creates a ticket:**
```
14:23:45 | → [MOBILE] POST /api/tickets | User: 5
14:23:46 | ✓ [CREATE] TICKETS ✓ | user=5 | ticket_id=42 | title=Payment Issue
14:23:46 | ← [MOBILE] POST /api/tickets | Status: 201 ✓ | Duration: 0.45s
```

**Admin updates service:**
```
14:24:10 | → [WEB] PATCH /api/services/3 | User: 1
14:24:11 | ✓ [UPDATE] SERVICES ✓ | user=1 | service_id=3 | changes=2 | is_active=false | category=Maintenance
14:24:11 | ← [WEB] PATCH /api/services/3 | Status: 200 ✓ | Duration: 0.12s
```

## Best Practices

1. **Monitor errors regularly** - Check error.log for issues
2. **Audit operations** - Use operations.log for compliance
3. **Track user activity** - Use user_id in search queries
4. **Performance tracking** - Look for Duration > 1s
5. **Security monitoring** - Look for AUTH errors and failed logins

## Troubleshooting

If logs aren't appearing:
1. Check that the `logs/` directory exists and is writable
2. Verify logger imports in the endpoint file
3. Check console for any logger initialization errors
4. Ensure the Flask app is running with the updated code
