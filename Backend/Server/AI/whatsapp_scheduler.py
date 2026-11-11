import logging

from apscheduler.schedulers.background import BackgroundScheduler

from Server.AI.whatsapp_timeout_service import (
    run_whatsapp_timeout_sweep
)


logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(daemon=True)


def start_whatsapp_scheduler(app):
    """
    Start the timeout scheduler.

    Each Gunicorn worker may initialize it, but the MySQL advisory
    lock ensures only one worker performs the timeout sweep at a time.
    """

    if scheduler.running:
        return

    def job():
        with app.app_context():
            run_whatsapp_timeout_sweep()

    scheduler.add_job(
        func=job,
        trigger="interval",
        seconds=30,
        id="diraja_whatsapp_timeout",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    logger.info("Dira WhatsApp timeout scheduler started")