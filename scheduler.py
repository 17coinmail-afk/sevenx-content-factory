import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
_publish_callback = None
_auto_post_callback = None


async def _check_scheduled():
    """Every minute: publish posts whose scheduled_at has passed."""
    import database as db
    from datetime import datetime

    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    for post in db.get_scheduled_posts():
        if post.get("scheduled_at") and post["scheduled_at"][:16] <= now:
            if _publish_callback:
                await _publish_callback(post["id"])


def start(publish_callback):
    global _publish_callback
    _publish_callback = publish_callback

    scheduler.add_job(
        _check_scheduled,
        "interval",
        minutes=1,
        id="check_scheduled",
        replace_existing=True,
    )

    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started")


def stop():
    if scheduler.running:
        scheduler.shutdown()


def apply_auto_post(times: list[str], enabled: bool, auto_post_callback):
    for job in scheduler.get_jobs():
        if job.id.startswith("auto_post_"):
            scheduler.remove_job(job.id)

    if not enabled or not auto_post_callback:
        return

    for i, t in enumerate(times):
        try:
            hour, minute = map(int, t.split(":"))
            scheduler.add_job(
                auto_post_callback,
                CronTrigger(hour=hour, minute=minute),
                id=f"auto_post_{i}",
                replace_existing=True,
            )
            logger.info(f"Auto-post job at {t}")
        except Exception as e:
            logger.error(f"Failed to add auto-post job {t}: {e}")
