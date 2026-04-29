import os
import json
import random
import logging
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
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

# Mapping: settings DB key → environment variable name
_ENV_MAP = {
    "openai_api_key":    "OPENAI_API_KEY",
    "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
    "channel_1_id":      "CHANNEL_1_ID",
    "channel_2_id":      "CHANNEL_2_ID",
    "pexels_api_key":    "PEXELS_API_KEY",
    "ai_base_url":       "AI_BASE_URL",
    "ai_model":          "AI_MODEL",
    "contact_info":      "CONTACT_INFO",
    "brand_voice":       "BRAND_VOICE",
}


def _effective_settings() -> dict:
    """Return DB settings; env vars only fill in where DB value is empty."""
    s = db.get_settings()
    for key, env_name in _ENV_MAP.items():
        env_val = os.getenv(env_name, "").strip()
        if env_val and not s.get(key, "").strip():
            s[key] = env_val
    return s

# Topics organised by category — ensures autopilot rotates through diverse angles
TOPIC_POOL: dict[str, list[str]] = {
    "механика": [
        "Как устроена агентская схема: деньги идут через посредника — это безопасно?",
        "Цепочка платежа от рублей до иностранного поставщика — пошагово",
        "Договор поставки vs агентская схема: что выгоднее в вашей ситуации",
        "Что происходит с деньгами после оплаты и до отгрузки товара",
        "Валютный контроль в 2025: что требует банк и как это обойти законно",
        "Почему платёжное поручение можно получить в день оплаты",
        "Как работает зеркальный платёж без российского следа",
    ],
    "китай": [
        "Юань или доллар: что выгоднее для импорта из Китая прямо сейчас",
        "Alipay и WeChat Pay для бизнес-переводов: реальная практика 2025",
        "Возврат до 40% НДС из Китая рублями: кто имеет право и как получить",
        "Почему платежи в Китай через российские банки почти перестали работать",
        "Как найти надёжного китайского поставщика и не потерять деньги на платеже",
        "Юаневые расчёты: нужен ли счёт в юанях или можно без него",
        "Работа с фабриками Китая напрямую: главные ошибки при первом платеже",
        "Почему Chinese New Year каждый год ломает цепочки поставок",
    ],
    "оаэ_европа": [
        "Дирхам ОАЭ: почему AED стал главной валютой обхода санкций",
        "Платежи через Дубай: как это работает для российского импортёра",
        "Как платить в евро когда SWIFT закрыт для большинства российских банков",
        "Турция, ОАЭ, Гонконг: где лучше проводить платежи в 2025",
        "Почему счёт в ОАЭ — не роскошь, а инструмент для ВЭД",
    ],
    "санкции": [
        "Санкционные товары без российского следа: что это значит на практике",
        "Вторичные санкции: чем рискуют иностранные партнёры и как это влияет на вас",
        "Двойное использование товаров: как провести платёж без проблем",
        "Почему «серый» импорт — это не то же самое, что незаконный",
        "Как 40+ компаний-плательщиков защищают ваш бизнес от блокировок",
        "Что будет если контрагент попадёт под санкции в середине сделки",
    ],
    "выручка_конвертация": [
        "Выкуп валютной выручки с бонусом 1–3%: почему это выгоднее банка",
        "Как вернуть экспортную выручку в Россию в 2025 году",
        "Зачем доплачивать сверх рынка за выкуп валюты — и когда это окупается",
        "Конвертация юань-рубль: где теряются деньги и как этого избежать",
        "Почему ставить рубль вперёд выгоднее, чем ждать конвертации",
    ],
    "сервис": [
        "Менеджер 24/7 vs банк: три реальных случая когда это спасло сделку",
        "Рубли утром — платёжное поручение вечером: как это технически возможно",
        "12 лет на рынке и $4 млрд оборот: почему опыт важнее обещаний",
        "Что значит «персональный менеджер» в ВЭД — и чем он отличается от операциониста",
        "Скорость платежа как конкурентное преимущество: реальные кейсы",
    ],
    "кейсы": [
        "Кейс: груз на таможне, поставщик требует оплату сегодня — как решили",
        "История клиента: перешли с банка на агентскую схему и сократили срок платежа в 4 раза",
        "Кейс: платёж за санкционный товар через три юрисдикции без единого отказа",
        "Реальная история: как потеряли $80 000 на ненадёжном агенте и что изменили",
        "Кейс: как небольшой импортёр получил условия крупного клиента",
        "История клиента: первый платёж через Seven-X после двух отказов от банков",
    ],
    "советы_чеклисты": [
        "5 вопросов, которые нужно задать платёжному агенту до первого перевода",
        "Чеклист: как подготовить документы для ВЭД-платежа за 2 часа",
        "Топ-5 причин почему платёж в Китай задерживается — и как их устранить",
        "Главные ошибки при первом импорте через третьи страны",
        "Как проверить надёжность платёжного агента: конкретные критерии",
        "Что должно быть в договоре с агентом: минимальный чеклист",
    ],
    "крипта": [
        "Криптовалюта в ВЭД: где это законно и где нет в 2025",
        "USDT для бизнес-расчётов: риски и реальная практика",
        "Как компании используют крипту для международных платежей — и почему не все",
        "Стейблкоины как инструмент ВЭД: плюсы, минусы, регуляторные риски",
    ],
    "тренды": [
        "Как санкции 2022–2025 полностью изменили рынок международных платежей",
        "Что происходит с курсом юаня и почему это важно для вашего бизнеса",
        "Почему российский бизнес массово уходит от банков к платёжным агентам",
        "Прогноз: как изменятся ВЭД-платежи в следующие 12 месяцев",
        "Де-долларизация: миф или реальность для российского импортёра",
        "Почему банки всё жёстче блокируют ВЭД-платежи — и что будет дальше",
    ],
    "фaq": [
        "FAQ: чем Seven-X принципиально отличается от банка при ВЭД",
        "Вопрос-ответ: можно ли работать с наличными в ВЭД легально",
        "FAQ: как устроена ответственность агента если платёж не дошёл",
        "Вопрос-ответ: нужно ли ИП или ООО для работы с платёжным агентом",
        "FAQ: что делать если поставщик отказывается от агентского платежа",
        "Вопрос-ответ: как рассчитывается комиссия агента и от чего она зависит",
    ],
}

# Flat list for legacy compatibility, built from pool
PRESET_TOPICS = [t for topics in TOPIC_POOL.values() for t in topics]

AUTOPILOT_STYLES = ["expert", "casual", "case", "faq"]
# Alternate promo and article — equal weight so channel gets both punchy and deep content
AUTOPILOT_FORMATS = ["promo", "article"]

# Category rotation state — tracked across calls via recently published category
_CATEGORY_ORDER = list(TOPIC_POOL.keys())


def _pick_autopilot_topic_and_style() -> tuple[str, str, str]:
    """Pick topic (category-aware), style, and format not matching recent posts."""
    recent = db.get_posts(status="published")

    # Determine which category to use next — avoid last 2 used categories
    recent_cats = []
    for p in recent[:10]:
        for cat, topics in TOPIC_POOL.items():
            if p.get("topic", "") in topics:
                recent_cats.append(cat)
                break
    avoid_cats = set(recent_cats[:2])
    available_cats = [c for c in _CATEGORY_ORDER if c not in avoid_cats] or _CATEGORY_ORDER
    category = random.choice(available_cats)

    # Pick topic from chosen category, avoiding recently published ones
    used_topics = {p.get("topic", "") for p in recent[:20]}
    cat_candidates = [t for t in TOPIC_POOL[category] if t not in used_topics]
    if not cat_candidates:
        cat_candidates = list(TOPIC_POOL[category])
    topic = random.choice(cat_candidates)

    # Rotate style — avoid the last used one
    last_style = recent[0].get("style", "") if recent else ""
    style_pool = [s for s in AUTOPILOT_STYLES if s != last_style] or AUTOPILOT_STYLES
    style = random.choice(style_pool)

    # Strictly alternate promo/article
    last_format = recent[0].get("format", "") if recent else ""
    post_format = "article" if last_format == "promo" else "promo"

    return topic, style, post_format


# ── Core publish logic ────────────────────────────────────────────────────────

def _resolve_image_path(image_path: str) -> str:
    if not image_path:
        return ""
    if image_path.startswith("/images/"):
        return str(IMAGES_DIR / image_path[8:])
    if image_path.startswith("/"):
        return image_path[1:]
    return image_path


async def publish_post(post_id: int) -> str:
    """Returns empty string on success, or error description on failure."""
    post = db.get_post(post_id)
    if not post or post["status"] == "published":
        return ""

    settings = _effective_settings()
    bot_token = settings.get("telegram_bot_token", "")
    ch1 = settings.get("channel_1_id", "")
    ch2 = settings.get("channel_2_id", "")
    channels = list(dict.fromkeys(c for c in [ch1, ch2] if c))

    if not bot_token or not channels:
        logger.error("Telegram not configured")
        db.update_post(post_id, status="failed")
        return "Telegram не настроен (нет токена или канала)"

    image_path = _resolve_image_path(post.get("image_path", ""))

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
    logger.info(f"Post {post_id} → {'published' if success else 'failed'} | results: {results}")

    if not success:
        errs = [r.get("error", "неизвестная ошибка") for r in results.values() if not r.get("success")]
        return " | ".join(errs)
    return ""


async def auto_generate_and_publish() -> int:
    from openai import AsyncOpenAI
    from openai_service import generate_text_variants, DEFAULT_MODELS

    settings = _effective_settings()
    api_key = settings.get("openai_api_key", "")
    if not api_key:
        raise ValueError("AI API ключ не настроен — добавьте его в Настройках")

    base_url = settings.get("ai_base_url", "").strip() or None
    model = settings.get("ai_model", "").strip() or DEFAULT_MODELS.get(base_url or "", "gpt-4o")
    brand_voice = settings.get("brand_voice", "")
    contact_info = settings.get("contact_info", "")
    pexels_key = settings.get("pexels_api_key", "").strip()
    image_provider = settings.get("image_provider", "pollinations")
    topic, style, post_format = _pick_autopilot_topic_and_style()

    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = AsyncOpenAI(**kwargs)

    rates = await get_cbr_rates()
    currency_text = format_rates_for_post(rates)

    variants = await generate_text_variants(
        topic, style, brand_voice, currency_text, client, model,
        contact_info=contact_info, post_format=post_format,
    )
    if not variants:
        raise ValueError("AI не вернул варианты текста")

    v = random.choice(variants)
    hook = v.get("image_hook", "")

    image_path = ""
    try:
        if image_provider == "pexels" and pexels_key:
            from openai_service import fetch_image_pexels
            image_path = await fetch_image_pexels(topic, pexels_key, contact_info=contact_info, hook=hook)
        elif image_provider == "openai":
            from openai_service import generate_image as gen_img, _add_branding
            from pathlib import Path as _Path
            img_path_str = await gen_img(topic, v["text"], client)
            # Apply branding to DALL-E images (saved as PNG, re-save with overlay)
            local = IMAGES_DIR / img_path_str[8:]
            _add_branding(local, topic, contact_info=contact_info, hook=hook)
            image_path = img_path_str
        else:
            from openai_service import generate_image_pollinations
            image_path = await generate_image_pollinations(topic, v["text"], contact_info=contact_info, hook=hook)
    except Exception as e:
        logger.warning(f"Auto-generate image failed (posting without image): {e}")

    post_id = db.create_post(
        topic=topic, text=v["text"], image_path=image_path,
        style=style, post_format=post_format, hashtags=v.get("hashtags", ""),
        status="draft", scheduled_at=None,
    )
    logger.info(f"Auto-generated post {post_id}: [{post_format}/{style}] {topic}")
    tg_error = await publish_post(post_id)
    return post_id, tg_error


async def auto_post():
    posts = db.get_scheduled_posts()
    if posts:
        await publish_post(posts[0]["id"])  # return value intentionally ignored for scheduler
        return

    settings = _effective_settings()
    if settings.get("auto_generate_enabled", "false") == "true":
        await auto_generate_and_publish()


# ── Week generation (background) ─────────────────────────────────────────────

async def _generate_week_bg(settings: dict):
    """Generate 7 scheduled posts over the next 7 days. Runs in background."""
    from openai import AsyncOpenAI
    from openai_service import generate_text_variants, DEFAULT_MODELS
    from zoneinfo import ZoneInfo
    from datetime import timedelta

    api_key = settings.get("openai_api_key", "")
    if not api_key:
        logger.error("Week gen: no API key")
        return

    base_url = settings.get("ai_base_url", "").strip() or None
    model = settings.get("ai_model", "").strip() or DEFAULT_MODELS.get(base_url or "", "gpt-4o")
    brand_voice = settings.get("brand_voice", "")
    contact_info = settings.get("contact_info", "")
    pexels_key = settings.get("pexels_api_key", "").strip()
    image_provider = settings.get("image_provider", "pollinations")
    times_raw = json.loads(settings.get("auto_post_times", '["10:00","19:00"]'))

    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = AsyncOpenAI(**kwargs)

    MOSCOW_TZ = ZoneInfo("Europe/Moscow")
    now = datetime.now(MOSCOW_TZ)

    used_topics: set = set()
    created = 0

    for day_offset in range(1, 8):
        target_day = (now + timedelta(days=day_offset)).date()
        time_str = times_raw[(day_offset - 1) % len(times_raw)] if times_raw else "10:00"
        hour, minute = map(int, time_str.split(":"))
        scheduled_at = datetime(
            target_day.year, target_day.month, target_day.day, hour, minute
        ).isoformat()

        # Pick unique topic within this batch
        recent = db.get_posts(status="published")
        avoid = used_topics | {p.get("topic", "") for p in recent[:len(PRESET_TOPICS) - 1]}
        candidates = [t for t in PRESET_TOPICS if t not in avoid]
        if not candidates:
            candidates = [t for t in PRESET_TOPICS if t not in used_topics] or list(PRESET_TOPICS)
        topic = random.choice(candidates)
        used_topics.add(topic)

        last_style = recent[0].get("style", "") if recent else ""
        style = random.choice([s for s in AUTOPILOT_STYLES if s != last_style] or AUTOPILOT_STYLES)
        post_format = random.choice(AUTOPILOT_FORMATS)

        try:
            rates = await get_cbr_rates()
            currency_text = format_rates_for_post(rates)
            variants = await generate_text_variants(
                topic, style, brand_voice, currency_text, client, model,
                contact_info=contact_info, post_format=post_format,
            )
            if not variants:
                logger.warning(f"Week gen day {day_offset}: no variants returned")
                continue

            v = random.choice(variants)
            hook = v.get("image_hook", "")

            image_path = ""
            try:
                if image_provider == "pexels" and pexels_key:
                    from openai_service import fetch_image_pexels
                    image_path = await fetch_image_pexels(topic, pexels_key, contact_info=contact_info, hook=hook)
                elif image_provider == "openai":
                    from openai_service import generate_image as gen_img, _add_branding
                    img_path_str = await gen_img(topic, v["text"], client)
                    local = IMAGES_DIR / img_path_str[8:]
                    _add_branding(local, topic, contact_info=contact_info, hook=hook)
                    image_path = img_path_str
                else:
                    from openai_service import generate_image_pollinations
                    image_path = await generate_image_pollinations(topic, v["text"], contact_info=contact_info, hook=hook)
            except Exception as img_e:
                logger.warning(f"Week gen image failed day {day_offset}: {img_e}")

            db.create_post(
                topic=topic, text=v["text"], image_path=image_path,
                style=style, post_format=post_format, hashtags=v.get("hashtags", ""),
                status="scheduled", scheduled_at=scheduled_at,
            )
            created += 1
            logger.info(f"Week gen: day +{day_offset} → {topic[:50]} @ {scheduled_at}")
        except Exception as e:
            logger.error(f"Week gen failed day {day_offset}: {e}")

    logger.info(f"Week gen complete: {created}/7 posts scheduled")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    sched.start(publish_callback=publish_post)

    settings = _effective_settings()
    times = json.loads(settings.get("auto_post_times", '["10:00","19:00"]'))
    enabled = settings.get("auto_post_enabled", "false") == "true"
    sched.apply_auto_post(times, enabled, auto_post)

    yield
    sched.stop()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Seven-X Content Factory", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/images", StaticFiles(directory=str(IMAGES_DIR)), name="images")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
async def health():
    return {"ok": True, "storage": "postgresql" if db.IS_PG else "sqlite_ephemeral"}


@app.get("/")
async def root():
    return FileResponse("static/index.html")


# ── Settings ──────────────────────────────────────────────────────────────────

@app.get("/api/settings")
async def get_settings():
    s = _effective_settings()

    def _mask(val: str, n: int) -> str:
        suffix = " (env)" if any(os.getenv(e, "") == val for e in _ENV_MAP.values()) else ""
        return (val[:n] + "..." + val[-4:] if len(val) > n + 4 else val[:n] + "...") + suffix

    if s.get("openai_api_key"):
        s["openai_api_key_masked"] = _mask(s["openai_api_key"], 7)
    if s.get("telegram_bot_token"):
        s["telegram_bot_token_masked"] = _mask(s["telegram_bot_token"], 8)
    if s.get("pexels_api_key"):
        s["pexels_api_key_masked"] = _mask(s["pexels_api_key"], 6)
    return s


class SettingsIn(BaseModel):
    openai_api_key: Optional[str] = None
    ai_base_url: Optional[str] = None
    ai_model: Optional[str] = None
    image_provider: Optional[str] = None
    pexels_api_key: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    channel_1_id: Optional[str] = None
    channel_2_id: Optional[str] = None
    auto_post_enabled: Optional[str] = None
    auto_post_times: Optional[str] = None
    auto_generate_enabled: Optional[str] = None
    brand_voice: Optional[str] = None
    contact_info: Optional[str] = None


@app.put("/api/settings")
async def save_settings(data: SettingsIn):
    updates = {k: v for k, v in data.dict().items() if v is not None}
    for k, v in updates.items():
        db.update_setting(k, v)

    if "auto_post_enabled" in updates or "auto_post_times" in updates:
        s = _effective_settings()
        times = json.loads(s.get("auto_post_times", '["10:00","19:00"]'))
        enabled = s.get("auto_post_enabled", "false") == "true"
        sched.apply_auto_post(times, enabled, auto_post)

    return {"success": True}


@app.post("/api/test-telegram")
async def test_telegram():
    s = _effective_settings()
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
    post_format: str = "promo"
    include_rates: bool = False
    brand_voice: Optional[str] = None


def _make_ai_client(s: dict):
    from openai import AsyncOpenAI
    api_key = os.getenv("OPENAI_API_KEY") or s.get("openai_api_key", "")
    base_url = s.get("ai_base_url", "").strip() or None
    if not api_key:
        raise HTTPException(400, "API key not configured")
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return AsyncOpenAI(**kwargs), base_url


def _resolve_model(s: dict, base_url: Optional[str]) -> str:
    from openai_service import DEFAULT_MODELS
    model = s.get("ai_model", "").strip()
    if model:
        return model
    return DEFAULT_MODELS.get(base_url or "", "gpt-4o")


@app.post("/api/generate")
async def generate(req: GenerateIn):
    from openai_service import generate_text_variants

    s = _effective_settings()
    client, base_url = _make_ai_client(s)
    model = _resolve_model(s, base_url)

    currency_text = ""
    if req.include_rates:
        rates = await get_cbr_rates()
        currency_text = format_rates_for_post(rates)

    brand_voice = req.brand_voice or s.get("brand_voice", "")
    contact_info = s.get("contact_info", "")

    try:
        variants = await generate_text_variants(
            topic=req.topic, style=req.style, brand_voice=brand_voice,
            currency_text=currency_text, client=client, model=model,
            contact_info=contact_info, post_format=req.post_format,
        )
        return {"variants": variants}
    except Exception as e:
        logger.error(f"Generate error: {e}")
        raise HTTPException(500, str(e))


class GenerateImageIn(BaseModel):
    topic: str
    post_text: Optional[str] = ""
    image_hook: Optional[str] = ""


@app.post("/api/generate/image")
async def generate_image(req: GenerateImageIn):
    from openai_service import generate_image as gen_img, generate_image_pollinations, fetch_image_pexels

    s = _effective_settings()
    image_provider = s.get("image_provider", "pollinations")
    contact_info = s.get("contact_info", "")
    pexels_key = s.get("pexels_api_key", "").strip()
    hook = req.image_hook or ""

    try:
        if image_provider == "pexels" and pexels_key:
            url = await fetch_image_pexels(req.topic, pexels_key, contact_info=contact_info, hook=hook)
        elif image_provider == "openai":
            from openai_service import _add_branding
            client, _ = _make_ai_client(s)
            url = await gen_img(req.topic, req.post_text, client)
            local = IMAGES_DIR / url[8:]
            _add_branding(local, req.topic, contact_info=contact_info, hook=hook)
        else:
            url = await generate_image_pollinations(req.topic, req.post_text or req.topic, contact_info=contact_info, hook=hook)
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
    post_format: Optional[str] = "promo"
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
        topic=req.topic, text=req.text, image_path=req.image_path,
        style=req.style, post_format=req.post_format or "promo",
        hashtags=req.hashtags, status=req.status,
        scheduled_at=req.scheduled_at,
    )
    return {"id": pid, "success": True}


@app.put("/api/posts/{post_id}")
async def update_post(post_id: int, req: PostIn):
    if not db.get_post(post_id):
        raise HTTPException(404, "Not found")
    db.update_post(
        post_id, text=req.text, image_path=req.image_path, style=req.style,
        hashtags=req.hashtags, status=req.status, scheduled_at=req.scheduled_at,
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
    tg_err = await publish_post(post_id)
    post = db.get_post(post_id)
    return {"success": post["status"] == "published", "status": post["status"], "error": tg_err}


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


# ── Autopilot test trigger ────────────────────────────────────────────────────

@app.post("/api/autopilot/trigger")
async def trigger_autopilot():
    settings = _effective_settings()
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or settings.get("telegram_bot_token", "")
    ch1 = os.getenv("CHANNEL_1_ID") or settings.get("channel_1_id", "")

    if not bot_token or not ch1:
        raise HTTPException(400, "Telegram не настроен (нет токена или канала)")

    try:
        post_id, tg_error = await auto_generate_and_publish()
    except Exception as e:
        logger.error(f"Autopilot trigger error: {e}")
        raise HTTPException(500, str(e))

    if not tg_error:
        return {"success": True, "message": "Пост опубликован в Telegram ✓"}
    raise HTTPException(500, f"Telegram: {tg_error}")


@app.post("/api/autopilot/generate-week")
async def generate_week_endpoint(background_tasks: BackgroundTasks):
    settings = _effective_settings()
    if not settings.get("openai_api_key", ""):
        raise HTTPException(400, "AI API ключ не настроен — добавьте его в Настройках")
    background_tasks.add_task(_generate_week_bg, settings)
    return {"message": "Запущено! 7 постов создаются в фоне — проверьте Календарь через 1–2 минуты."}
