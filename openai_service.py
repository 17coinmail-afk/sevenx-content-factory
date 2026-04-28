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

# Font search order: app-bundled → downloaded → system → PIL default
_FONT_SEARCH = [
    Path(__file__).parent / "fonts" / "Bold.ttf",           # committed to repo
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    Path("/usr/share/fonts/opentype/open-sans/OpenSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/open-sans/OpenSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
]
_FONT_REGULAR_SEARCH = [
    Path(__file__).parent / "fonts" / "Regular.ttf",
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]


def _find_font_file(paths: list) -> Path | None:
    for p in paths:
        if p.exists():
            return p
    return None


def _get_font(size: int, bold: bool = True):
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]

    from PIL import ImageFont

    paths = _FONT_SEARCH if bold else _FONT_REGULAR_SEARCH
    font_file = _find_font_file(paths)

    font = None
    if font_file:
        try:
            font = ImageFont.truetype(str(font_file), size)
        except Exception:
            pass

    if font is None:
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
        from PIL import Image, ImageDraw, ImageFilter
        import re

        img = Image.open(filepath).convert("RGB")
        W, H = img.size

        # ── Sizes ─────────────────────────────────────────────────────────
        title_sz = max(66, W // 13)       # dominant headline
        sub_sz   = max(22, W // 42)       # small contact line
        brand_sz = max(28, W // 32)       # SEVEN-X wordmark
        font_t = _get_font(title_sz, bold=True)
        font_s = _get_font(sub_sz,   bold=False)
        font_b = _get_font(brand_sz, bold=True)

        # ── Text content ──────────────────────────────────────────────────
        clean = re.sub(r"<[^>]+>", "", headline).strip()
        first = re.split(r"[.!?\n]", clean)[0].strip()
        title = first.upper()             # ALL CAPS like the reference

        # ── Layer 1: full-image subtle dark veil ──────────────────────────
        veil = Image.new("RGBA", (W, H), (0, 0, 0, 90))
        img  = Image.alpha_composite(img.convert("RGBA"), veil)

        # ── Layer 2: heavy gradient bottom 55% → near-black ──────────────
        grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd   = ImageDraw.Draw(grad)
        g0   = int(H * 0.30)
        for y in range(g0, H):
            t = (y - g0) / (H - g0)
            a = int(215 * (t ** 0.55))
            gd.line([(0, y), (W, y)], fill=(4, 12, 8, a))
        img  = Image.alpha_composite(img, grad).convert("RGB")
        draw = ImageDraw.Draw(img)

        pad_x  = int(W * 0.07)
        pad_b  = int(H * 0.06)           # bottom padding
        max_tw = W - pad_x * 2

        # ── Bottom anchor: SEVEN-X centered ──────────────────────────────
        bw      = _tw(draw, "SEVEN-X", font_b)
        brand_y = H - pad_b - brand_sz
        draw.text(((W - bw) // 2, brand_y), "SEVEN-X",
                  fill=(255, 255, 255), font=font_b)

        # ── Thin emerald rule above brand ─────────────────────────────────
        rule_y = brand_y - int(H * 0.022)
        draw.rectangle([(pad_x, rule_y), (W - pad_x, rule_y + max(2, int(H*0.003)))],
                       fill=(82, 183, 136))

        # ── Contact line above rule ───────────────────────────────────────
        sub_text = "seven-x.ru  ·  Артём +7 967 202-55-54"
        sub_y    = rule_y - int(H * 0.016) - sub_sz
        draw.text((pad_x, sub_y), sub_text, fill=(160, 160, 160), font=font_s)

        # ── Headline: ALL CAPS, white, large, left — the hero element ─────
        lines   = _wrap(draw, title, font_t, max_tw)[:3]
        lh      = int(title_sz * 1.18)
        total_h = len(lines) * lh
        title_y = sub_y - int(H * 0.038) - total_h

        for i, line in enumerate(lines):
            y = title_y + i * lh
            # Tight shadow for depth (1 px offset, semi-transparent)
            draw.text((pad_x + 2, y + 2), line, fill=(0, 0, 0, 160), font=font_t)
            draw.text((pad_x, y),         line, fill=(255, 255, 255), font=font_t)

        # ── Emerald left accent bar alongside headline ─────────────────────
        bar_x = pad_x - int(W * 0.025)
        bar_w = max(6, int(W * 0.009))
        draw.rectangle(
            [(bar_x, title_y - 4), (bar_x + bar_w, title_y + total_h + 4)],
            fill=(82, 183, 136),
        )

        img.save(filepath, "JPEG", quality=93)
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
