from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron         import CronTrigger
from datetime import datetime, timezone, date
import logging

logger = logging.getLogger(__name__)

# =============================================================
# SCHEDULER
# Responsibilities:
#   - Run the carry-over requeue job every minute
#   - For each service whose schedule opens at the current minute,
#     promote all carried_over tickets back to pending status
#     and assign them positions ahead of today's new tickets.
#
# Why every minute?
#   Different services can have different opening times, so we
#   check every minute and only act when now == opening_time.
#
# OOP Principle: Single Responsibility
# =============================================================

def requeue_carried_over():
    """
    Runs every minute.
    For each service that opens right now (within this minute),
    find all carried_over tickets and put them back as pending
    at the front of their queues (position 0, 1, 2…).
    New tickets issued today will be positioned after them.
    """
    from models import db, ServiceSchedule, Ticket, Service
    from repositories.schedule_repository import ScheduleRepository
    from repositories.ticket_repository   import TicketRepository
    from services.schedule_service        import ScheduleService

    # We need the Flask app context — imported lazily to avoid circular imports
    from app import create_app
    app = create_app()

    with app.app_context():
        try:
            now      = datetime.now(timezone.utc)
            now_time = now.time().replace(second=0, microsecond=0)
            today    = date.today()
            dow      = now.weekday()   # 0=Mon … 6=Sun

            schedule_repo = ScheduleRepository()
            ticket_repo   = TicketRepository()
            schedule_svc  = ScheduleService()

            # Find all services with a schedule that opens right now
            # Check specific day override first, then general
            from sqlalchemy import or_
            schedules = (ServiceSchedule.query
                         .filter(ServiceSchedule.is_open == True)
                         .filter(
                             # opening_time matches current minute (ignore seconds)
                             db.func.time_format(ServiceSchedule.opening_time, '%H:%i') ==
                             now.strftime('%H:%M')
                         )
                         .filter(
                             or_(
                                 ServiceSchedule.day_of_week == None,
                                 ServiceSchedule.day_of_week == dow,
                             )
                         )
                         .all())

            # Deduplicate: per service, prefer specific day override over general
            service_schedule_map = {}
            for s in schedules:
                sid = s.service_id
                if sid not in service_schedule_map:
                    service_schedule_map[sid] = s
                elif s.day_of_week is not None:
                    # Specific day overrides general
                    service_schedule_map[sid] = s

            for service_id, schedule in service_schedule_map.items():
                _requeue_for_service(
                    service_id, schedule, ticket_repo,
                    schedule_svc, today, db
                )

        except Exception as e:
            logger.error(f"[Scheduler] requeue_carried_over error: {e}")


def _requeue_for_service(service_id, schedule, ticket_repo, schedule_svc, today, db):
    """
    Promote all carried_over tickets for a service back to pending,
    placing them at the front of their respective queues.
    """
    carried = ticket_repo.find_carried_over(service_id)
    if not carried:
        return

    # Group by queue
    from collections import defaultdict
    by_queue = defaultdict(list)
    for t in carried:
        by_queue[t.queue_id].append(t)

    avg_dur = schedule.avg_duration

    for queue_id, tickets in by_queue.items():
        # Current max position in this queue (active/pending tickets)
        current_queue = ticket_repo.find_by_queue(queue_id)
        active_pending = [
            t for t in current_queue
            if t.status in (ticket_repo.STATUS_PENDING, ticket_repo.STATUS_ACTIVE)
            and t.position is not None
        ]

        # Shift existing tickets to make room for carried-over ones
        offset = len(tickets)
        for t in active_pending:
            t.position = (t.position or 0) + offset

        # Place carried-over tickets at front
        for i, t in enumerate(sorted(tickets, key=lambda x: x.carried_over_date or today)):
            t.status            = ticket_repo.STATUS_PENDING
            t.position          = i
            t.carried_over_date = None   # clear the carry-over marker

        # Recalculate estimates for entire queue
        all_queue_tickets = ticket_repo.find_by_queue(queue_id)
        schedule_svc.recalculate_queue(all_queue_tickets, avg_dur)

    try:
        db.session.commit()
        logger.info(f"[Scheduler] Requeued {len(carried)} carried-over ticket(s) for service {service_id}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"[Scheduler] Failed to requeue for service {service_id}: {e}")


# =============================================================
# SCHEDULER FACTORY
# Call init_scheduler(app) from create_app()
# =============================================================
_scheduler = None

def init_scheduler(app):
    """Initialize and start the APScheduler background scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone="UTC")

    # Run every minute to catch any service opening time
    _scheduler.add_job(
        func     = requeue_carried_over,
        trigger  = CronTrigger(minute="*"),
        id       = "requeue_carried_over",
        name     = "Requeue carried-over tickets at opening time",
        replace_existing = True,
        misfire_grace_time = 30,
    )

    _scheduler.start()
    logger.info("[Scheduler] Background scheduler started.")

    import atexit
    atexit.register(lambda: _scheduler.shutdown(wait=False))