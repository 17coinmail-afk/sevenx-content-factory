import os
import uuid
import json
import httpx
import logging
import urllib.parse
from pathlib import Path
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

IMAGES_DIR = Path(os.getenv("IMAGES_DIR", "images"))
IMAGES_DIR.mkdir(exist_ok=True, parents=True)

STYLE_PROMPTS = {
    "expert": """\
Экспертный продающий стиль.
Структура:
1. Первая строка — острый заголовок: боль/вопрос + эмодзи
2. 2-3 конкретных преимущества Seven-X (цифры, скорость, выгода)
3. Призыв к действию — написать Артёму

Используй <b>жирный</b> для заголовка и ключевых фактов.
Эмодзи — только по делу, не более 4 штук.""",

    "casual": """\
Живой разговорный стиль — как друг, который в теме.
Структура:
1. Реальная ситуация / проблема предпринимателя — с иронией или сочувствием
2. «Вот как это решает Seven-X» — просто и конкретно
3. Мягкий призыв — «напиши Артёму, расскажет»

Используй <b>жирный</b> для ключевых моментов. Разговорные обороты, без канцелярита.""",

    "case": """\
Формат мини-кейса.
Структура:
1. <b>Ситуация:</b> конкретная проблема реального клиента (без имён)
2. <b>Решение:</b> что сделала Seven-X — конкретные шаги
3. <b>Результат:</b> цифры, скорость, выгода
4. CTA: «У вас похожая задача? → Артём»

Всё конкретно, правдоподобно, без воды.""",

    "faq": """\
Формат вопрос-ответ.
Структура:
1. <b>❓ Вопрос</b> — реальный вопрос предпринимателя о ВЭД/платежах
2. <b>💡 Ответ</b> — чёткий, экспертный, с конкретикой от Seven-X
3. Финал: «Остались вопросы? Пишите Артёму»

Вопрос должен быть острым, ответ — исчерпывающим.""",
}

SYSTEM_PROMPT = """\
Ты — опытный копирайтер Telegram-канала компании Seven-X, ведущего платёжного агента для ВЭД.

ФАКТЫ о компании (используй их):
• 12 лет на рынке, $4 млрд+ оборот импортных сделок
• 40+ компаний-плательщиков по всему миру
• Валюты: USD, EUR, CNY (юань), AED (дирхам)
• Рубли утром → платёжное поручение вечером
• Агентская схема и договор поставки
• Санкционные товары — без российского следа
• Выкуп валютной выручки с доплатой 1–3%
• Возврат до 40% НДС из Китая рублями в РФ
• Переводы: Alipay, WeChat, наличные, крипта
• Контакт: Артём, +7 967 202-55-54, artem@seven-x.ru
• Менеджер на связи 24/7

ПРАВИЛА:
- Пиши на русском
- Форматирование HTML: <b>жирный</b>, <i>курсив</i>
- Длина поста: 300–600 символов (это лимит подписи к фото в Telegram)
- Хэштеги: 3–4 штуки, отдельной строкой в поле hashtags
- Каждый вариант — уникальная структура и подача
- Всегда заканчивай CTA с контактом Артёма"""

IMAGE_PROMPT_BASE = (
    "Professional business illustration for a Russian foreign trade payment company. "
    "Deep forest green (#0f2018) background, gold and emerald accent colors. "
    "Concepts: international money transfer, global trade routes, currency exchange. "
    "Style: modern flat design with subtle geometric patterns, globe or world map elements, "
    "currency symbols (¥ $ € ₽), clean corporate look. High quality. NO text or letters."
)

DEFAULT_MODELS = {
    "https://api.groq.com/openai/v1": "llama-3.3-70b-versatile",
    "https://api.deepseek.com": "deepseek-chat",
}


async def generate_text_variants(
    topic: str,
    style: str,
    brand_voice: str,
    currency_text: str,
    client: AsyncOpenAI,
    model: str = "gpt-4o",
) -> list[dict]:
    style_prompt = STYLE_PROMPTS.get(style, STYLE_PROMPTS["expert"])
    currency_block = f"\n\nВключи в пост актуальные курсы валют:\n{currency_text}" if currency_text else ""

    system = brand_voice.strip() if brand_voice.strip() else SYSTEM_PROMPT

    user_prompt = f"""Напиши 3 разных продающих Telegram-поста на тему: «{topic}»

{style_prompt}{currency_block}

Ответ строго в JSON (ничего лишнего):
{{
  "variants": [
    {{"text": "текст поста с HTML-тегами", "hashtags": "#тег1 #тег2 #тег3"}},
    {{"text": "текст поста с HTML-тегами", "hashtags": "#тег1 #тег2 #тег3"}},
    {{"text": "текст поста с HTML-тегами", "hashtags": "#тег1 #тег2 #тег3"}}
  ]
}}"""

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.85,
    )

    result = json.loads(response.choices[0].message.content)
    return result.get("variants", [])


async def generate_image(topic: str, post_text: str, client: AsyncOpenAI) -> str:
    prompt = f"{IMAGE_PROMPT_BASE} Topic context: '{topic}'."

    response = await client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size="1024x1024",
        quality="standard",
        n=1,
    )

    image_url = response.data[0].url
    filename = f"{uuid.uuid4()}.png"
    filepath = IMAGES_DIR / filename

    async with httpx.AsyncClient(timeout=60) as http:
        img_resp = await http.get(image_url)
        img_resp.raise_for_status()
        filepath.write_bytes(img_resp.content)

    return f"/images/{filename}"


_font_cache: dict = {}

# Directories where we look for / store fonts
_FONTS_DIR   = Path(__file__).parent / "fonts"
_BOLD_FILE   = _FONTS_DIR / "Bold.ttf"
_REG_FILE    = _FONTS_DIR / "Regular.ttf"

# System-font fallback paths (Render Ubuntu / Debian)
_SYS_BOLD = [
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/open-sans/OpenSans-Bold.ttf"),
    Path("/usr/share/fonts/opentype/open-sans/OpenSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
]
_SYS_REG = [
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    Path("/usr/share/fonts/truetype/open-sans/OpenSans-Regular.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]

# Remote TTF sources tried in order
_BOLD_URLS = [
    "https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-Bold.ttf",
    "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf",
]
_REG_URLS = [
    "https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-Regular.ttf",
]


def _try_download_font(urls: list, dest: Path) -> bool:
    """Download the first URL that works into dest. Returns True on success."""
    import urllib.request
    _FONTS_DIR.mkdir(exist_ok=True, parents=True)
    for url in urls:
        try:
            tmp = dest.with_suffix(".tmp")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = r.read()
            if len(data) < 10_000:
                continue
            tmp.write_bytes(data)
            tmp.replace(dest)
            logger.info(f"Font downloaded: {dest.name} ({len(data)//1024}KB) from {url}")
            return True
        except Exception as e:
            logger.debug(f"Font download failed ({url}): {e}")
    return False


def _resolve_font_path(committed: Path, sys_paths: list, dl_urls: list) -> Path | None:
    # 1) committed to git repo
    if committed.exists() and committed.stat().st_size > 10_000:
        logger.info(f"Using committed font: {committed}")
        return committed
    # 2) system fonts (installed via apt in build)
    for p in sys_paths:
        if p.exists():
            logger.info(f"Using system font: {p}")
            return p
    # 3) download at runtime
    if _try_download_font(dl_urls, committed):
        return committed
    logger.warning("No usable font found — PIL default will be used (text may look small)")
    return None


# Resolve once at module load so the first image doesn't pay the I/O cost
_BOLD_PATH: Path | None = _resolve_font_path(_BOLD_FILE, _SYS_BOLD, _BOLD_URLS)
_REG_PATH:  Path | None = _resolve_font_path(_REG_FILE,  _SYS_REG,  _REG_URLS)


def _get_font(size: int, bold: bool = True):
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]

    from PIL import ImageFont

    path = _BOLD_PATH if bold else _REG_PATH
    font = None
    if path:
        try:
            font = ImageFont.truetype(str(path), size)
        except Exception as e:
            logger.warning(f"truetype load failed ({path}): {e}")

    if font is None:
        # size= is ignored by load_default in old Pillow, but try anyway
        try:
            font = ImageFont.load_default(size=size)
        except TypeError:
            font = ImageFont.load_default()

    _font_cache[key] = font
    return font


def _tw(draw, text, font):
    try:
        return int(draw.textlength(text, font=font))
    except AttributeError:
        return draw.textsize(text, font=font)[0]


def _wrap(draw, text, font, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if _tw(draw, cand, font) <= max_w:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [text]


def _add_branding(filepath: Path, headline: str):
    try:
        from PIL import Image, ImageDraw
        import re

        img = Image.open(filepath).convert("RGB")
        W, H = img.size

        logger.info(f"_add_branding: bold_font={_BOLD_PATH}, reg_font={_REG_PATH}")

        # ── Font sizes ────────────────────────────────────────────────────
        title_sz = max(72, W // 12)    # very large — fills ~30% width per word
        sub_sz   = max(24, W // 38)
        brand_sz = max(32, W // 28)
        font_t = _get_font(title_sz, bold=True)
        font_s = _get_font(sub_sz,   bold=False)
        font_b = _get_font(brand_sz, bold=True)

        # ── Extract first sentence → headline ─────────────────────────────
        clean = re.sub(r"<[^>]+>", "", headline).strip()
        first = re.split(r"[.!?\n]", clean)[0].strip()
        title = first.upper()

        # ── Dark gradient: only bottom 60%, photo stays clear on top ─────
        grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd   = ImageDraw.Draw(grad)
        g0   = int(H * 0.38)
        for y in range(g0, H):
            t = (y - g0) / (H - g0)
            a = int(230 * (t ** 0.45))   # aggressive curve → dark quickly
            gd.line([(0, y), (W, y)], fill=(3, 10, 6, a))
        img = Image.alpha_composite(img.convert("RGBA"), grad).convert("RGB")
        draw = ImageDraw.Draw(img)

        # ── Layout: anchor everything from the bottom up ──────────────────
        px    = int(W * 0.07)           # left margin
        max_w = W - px * 2

        # SEVEN-X — bottom-left, emerald
        brand_y = H - int(H * 0.055) - brand_sz
        draw.text((px, brand_y), "SEVEN-X", fill=(82, 183, 136), font=font_b)

        # Thin horizontal rule above SEVEN-X
        rule_y = brand_y - int(H * 0.02)
        draw.rectangle(
            [(px, rule_y), (W - px, rule_y + max(3, int(H * 0.003)))],
            fill=(82, 183, 136),
        )

        # Contact line above rule — left-aligned
        sub_y = rule_y - int(H * 0.015) - sub_sz
        draw.text(
            (px, sub_y),
            "seven-x.ru  ·  Артём: +7 967 202-55-54",
            fill=(170, 170, 170),
            font=font_s,
            anchor="la",
        )

        # Headline — left-aligned, white, ALL CAPS, hero size
        lines   = _wrap(draw, title, font_t, max_w)[:3]
        lh      = int(title_sz * 1.15)
        total_h = len(lines) * lh
        title_y = sub_y - int(H * 0.04) - total_h

        for i, line in enumerate(lines):
            y = title_y + i * lh
            # Black stroke for contrast on any background
            draw.text(
                (px, y), line,
                fill=(255, 255, 255),
                font=font_t,
                anchor="la",
                stroke_width=max(3, title_sz // 20),
                stroke_fill=(0, 0, 0),
            )

        img.save(filepath, "JPEG", quality=93)
        logger.info(f"_add_branding done: title='{title[:40]}' lines={len(lines)}")
    except Exception as e:
        logger.warning(f"Branding overlay failed: {e}")


async def generate_image_pollinations(topic: str, post_text: str) -> str:
    import random
    prompt  = f"{IMAGE_PROMPT_BASE} Topic: {topic}."
    encoded = urllib.parse.quote(prompt)
    seed    = random.randint(1, 999_999)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=1024&height=1024&nologo=true&model=flux&seed={seed}"
    )

    filename = f"{uuid.uuid4()}.jpg"
    filepath = IMAGES_DIR / filename

    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as http:
        resp = await http.get(url)
        resp.raise_for_status()
        if len(resp.content) < 5000:
            raise ValueError(f"Pollinations returned too-small response ({len(resp.content)} bytes)")
        filepath.write_bytes(resp.content)

    _add_branding(filepath, post_text or topic)
    return f"/images/{filename}"
