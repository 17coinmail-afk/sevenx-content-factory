import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

MOSCOW_TZ = ZoneInfo("Asia/Irkutsk")

scheduler = AsyncIOScheduler()
_publish_callback = None
_auto_post_callback = None


async def _keep_alive():
    url = os.getenv("RENDER_EXTERNAL_URL", "")
    if not url:
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            await client.get(f"{url}/health")
        logger.debug("Keep-alive ping sent")
    except Exception:
        pass


async def _refresh_currency():
    """Every 5 minutes: refresh CBR exchange rates into cache."""
    from currency_service import refresh_rates
    await refresh_rates()


async def check_scheduled():
    """Publish all scheduled posts whose scheduled_at has passed. Called every minute and on each /health ping."""
    import database as db

    now = datetime.now(MOSCOW_TZ).replace(tzinfo=None)
    for post in db.get_scheduled_posts():
        sa = post.get("scheduled_at")
        if not sa:
            continue
        try:
            due = datetime.fromisoformat(sa)
        except ValueError:
            due = datetime.strptime(sa[:16], "%Y-%m-%dT%H:%M")
        if due <= now and _publish_callback:
            try:
                await _publish_callback(post["id"])
            except Exception as e:
                logger.error(f"Scheduler failed to publish post {post['id']}: {e}")


def start(publish_callback):
    global _publish_callback
    _publish_callback = publish_callback

    scheduler.add_job(
        check_scheduled,
        "interval",
        minutes=1,
        id="check_scheduled",
        replace_existing=True,
        next_run_time=datetime.now(MOSCOW_TZ),
        misfire_grace_time=3600,  # catch up within 1 hour after sleep/restart
    )
    scheduler.add_job(
        _refresh_currency,
        "interval",
        minutes=5,
        id="refresh_currency",
        replace_existing=True,
        next_run_time=datetime.now(MOSCOW_TZ),
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _keep_alive,
        "interval",
        minutes=5,  # reduced from 10 to keep Render awake longer
        id="keep_alive",
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
                CronTrigger(hour=hour, minute=minute, timezone=MOSCOW_TZ),
                id=f"auto_post_{i}",
                replace_existing=True,
                misfire_grace_time=3600,
            )
            logger.info(f"Auto-post job at {t}")
        except Exception as e:
            logger.error(f"Failed to add auto-post job {t}: {e}")
