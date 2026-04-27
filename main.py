import os
import json
import logging
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

import database as db
import scheduler as sched
from currency_service import get_cbr_rates, format_rates_for_post
from telegram_service import send_post, test_connection

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

IMAGES_DIR = Path(os.getenv("IMAGES_DIR", "images"))
IMAGES_DIR.mkdir(exist_ok=True, parents=True)
Path("static").mkdir(exist_ok=True)


# ── Core publish logic ────────────────────────────────────────────────────────

async def publish_post(post_id: int):
    post = db.get_post(post_id)
    if not post or post["status"] == "published":
        return

    settings = db.get_settings()
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or settings.get("telegram_bot_token", "")
    ch1 = os.getenv("CHANNEL_1_ID") or settings.get("channel_1_id", "")
    ch2 = os.getenv("CHANNEL_2_ID") or settings.get("channel_2_id", "")
    channels = [c for c in [ch1, ch2] if c]

    if not bot_token or not channels:
        logger.error("Telegram not configured")
        db.update_post(post_id, status="failed")
        return

    image_path = post.get("image_path", "")
    if image_path and image_path.startswith("/"):
        image_path = image_path[1:]

    results = await send_post(
        bot_token=bot_token,
        channel_ids=channels,
        text=post["text"],
        image_path=image_path,
        hashtags=post.get("hashtags", ""),
    )

    success = all(r.get("success") for r in results.values())
    updates = {
        "status": "published" if success else "failed",
        "published_at": datetime.now().isoformat(),
    }
    if channels and channels[0] in results:
        updates["message_id_1"] = str(results[channels[0]].get("message_id", ""))
    if len(channels) > 1 and channels[1] in results:
        updates["message_id_2"] = str(results[channels[1]].get("message_id", ""))

    db.update_post(post_id, **updates)
    logger.info(f"Post {post_id} → {'published' if success else 'failed'}")


async def auto_post():
    posts = db.get_scheduled_posts()
    if posts:
        await publish_post(posts[0]["id"])


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    sched.start(publish_callback=publish_post)

    settings = db.get_settings()
    times = json.loads(settings.get("auto_post_times", '["10:00","19:00"]'))
    enabled = settings.get("auto_post_enabled", "false") == "true"
    sched.apply_auto_post(times, enabled, auto_post)

    yield
    sched.stop()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Seven-X Content Factory", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/images", StaticFiles(directory=str(IMAGES_DIR)), name="images")


@app.get("/")
async def root():
    return FileResponse("static/index.html")


# ── Settings ──────────────────────────────────────────────────────────────────

@app.get("/api/settings")
async def get_settings():
    s = db.get_settings()
    if s.get("openai_api_key"):
        k = s["openai_api_key"]
        s["openai_api_key_masked"] = k[:7] + "..." + k[-4:] if len(k) > 11 else "***"
    if s.get("telegram_bot_token"):
        t = s["telegram_bot_token"]
        s["telegram_bot_token_masked"] = t[:8] + "..." if len(t) > 8 else "***"
    return s


class SettingsIn(BaseModel):
    openai_api_key: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    channel_1_id: Optional[str] = None
    channel_2_id: Optional[str] = None
    auto_post_enabled: Optional[str] = None
    auto_post_times: Optional[str] = None
    brand_voice: Optional[str] = None


@app.put("/api/settings")
async def save_settings(data: SettingsIn):
    updates = {k: v for k, v in data.dict().items() if v is not None}
    for k, v in updates.items():
        db.update_setting(k, v)

    if "auto_post_enabled" in updates or "auto_post_times" in updates:
        s = db.get_settings()
        times = json.loads(s.get("auto_post_times", '["10:00","19:00"]'))
        enabled = s.get("auto_post_enabled", "false") == "true"
        sched.apply_auto_post(times, enabled, auto_post)

    return {"success": True}


@app.post("/api/test-telegram")
async def test_telegram():
    s = db.get_settings()
    token = os.getenv("TELEGRAM_BOT_TOKEN") or s.get("telegram_bot_token", "")
    if not token:
        raise HTTPException(400, "Bot token not configured")
    return await test_connection(token)


# ── Currency ──────────────────────────────────────────────────────────────────

@app.get("/api/currency")
async def currency():
    return await get_cbr_rates()


# ── Generate ──────────────────────────────────────────────────────────────────

class GenerateIn(BaseModel):
    topic: str
    style: str = "expert"
    include_rates: bool = False
    brand_voice: Optional[str] = None


@app.post("/api/generate")
async def generate(req: GenerateIn):
    from openai import AsyncOpenAI
    from openai_service import generate_text_variants

    s = db.get_settings()
    api_key = os.getenv("OPENAI_API_KEY") or s.get("openai_api_key", "")
    if not api_key:
        raise HTTPException(400, "OpenAI API key not configured")

    currency_text = ""
    if req.include_rates:
        rates = await get_cbr_rates()
        currency_text = format_rates_for_post(rates)

    brand_voice = req.brand_voice or s.get("brand_voice", "")
    client = AsyncOpenAI(api_key=api_key)

    try:
        variants = await generate_text_variants(
            topic=req.topic,
            style=req.style,
            brand_voice=brand_voice,
            currency_text=currency_text,
            client=client,
        )
        return {"variants": variants}
    except Exception as e:
        logger.error(f"Generate error: {e}")
        raise HTTPException(500, str(e))


class GenerateImageIn(BaseModel):
    topic: str
    post_text: Optional[str] = ""


@app.post("/api/generate/image")
async def generate_image(req: GenerateImageIn):
    from openai import AsyncOpenAI
    from openai_service import generate_image as gen_img

    s = db.get_settings()
    api_key = os.getenv("OPENAI_API_KEY") or s.get("openai_api_key", "")
    if not api_key:
        raise HTTPException(400, "OpenAI API key not configured")

    client = AsyncOpenAI(api_key=api_key)
    try:
        url = await gen_img(req.topic, req.post_text, client)
        return {"image_url": url}
    except Exception as e:
        logger.error(f"Image error: {e}")
        raise HTTPException(500, str(e))


# ── Posts CRUD ────────────────────────────────────────────────────────────────

class PostIn(BaseModel):
    topic: Optional[str] = ""
    text: str
    image_path: Optional[str] = ""
    style: Optional[str] = ""
    hashtags: Optional[str] = ""
    status: str = "draft"
    scheduled_at: Optional[str] = None


@app.get("/api/posts")
async def list_posts(status: Optional[str] = None):
    return {"posts": db.get_posts(status)}


@app.get("/api/posts/{post_id}")
async def get_post(post_id: int):
    post = db.get_post(post_id)
    if not post:
        raise HTTPException(404, "Not found")
    return post


@app.post("/api/posts")
async def create_post(req: PostIn):
    pid = db.create_post(
        topic=req.topic,
        text=req.text,
        image_path=req.image_path,
        style=req.style,
        hashtags=req.hashtags,
        status=req.status,
        scheduled_at=req.scheduled_at,
    )
    return {"id": pid, "success": True}


@app.put("/api/posts/{post_id}")
async def update_post(post_id: int, req: PostIn):
    if not db.get_post(post_id):
        raise HTTPException(404, "Not found")
    db.update_post(
        post_id,
        text=req.text,
        image_path=req.image_path,
        style=req.style,
        hashtags=req.hashtags,
        status=req.status,
        scheduled_at=req.scheduled_at,
    )
    return {"success": True}


@app.delete("/api/posts/{post_id}")
async def delete_post(post_id: int):
    db.delete_post(post_id)
    return {"success": True}


@app.post("/api/posts/{post_id}/publish")
async def publish_now(post_id: int):
    if not db.get_post(post_id):
        raise HTTPException(404, "Not found")
    await publish_post(post_id)
    post = db.get_post(post_id)
    return {"success": post["status"] == "published", "status": post["status"]}


class ScheduleIn(BaseModel):
    scheduled_at: str


@app.post("/api/posts/{post_id}/schedule")
async def schedule_post(post_id: int, req: ScheduleIn):
    if not db.get_post(post_id):
        raise HTTPException(404, "Not found")
    db.update_post(post_id, status="scheduled", scheduled_at=req.scheduled_at)
    return {"success": True}


# ── Calendar ──────────────────────────────────────────────────────────────────

@app.get("/api/calendar")
async def calendar():
    posts = db.get_calendar_posts()
    result: dict[str, list] = {}
    for post in posts:
        date = ""
        if post.get("scheduled_at"):
            date = post["scheduled_at"][:10]
        elif post.get("published_at"):
            date = post["published_at"][:10]
        if not date:
            continue
        result.setdefault(date, []).append({
            "id": post["id"],
            "text": post["text"][:100],
            "status": post["status"],
            "image_path": post.get("image_path", ""),
            "topic": post.get("topic", ""),
        })
    return result
